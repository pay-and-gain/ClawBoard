"""Bounded, portable backup packages; no application or platform state."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import tempfile
import zipfile

from clawboard.config import APP_VER, SCHEMA_VERSION

MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_MEMBERS = 10002
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_ARCHIVE_BYTES = MAX_TOTAL_BYTES + MAX_MANIFEST_BYTES + 2 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024
FORMAT = 'clawboard-backup'
FORMAT_VERSION = 1


class BackupError(OSError):
    """The package or transaction was rejected without silently losing data."""


class BackupCancelled(BackupError):
    """The requested operation was cancelled."""


@dataclass(frozen=True)
class BackupPreview:
    archive: Path
    sha256: str
    created_at: str
    app_version: str
    clip_count: int
    phrase_count: int
    image_count: int
    total_bytes: int
    external_file_count: int


@dataclass(frozen=True)
class Package:
    preview: BackupPreview
    manifest: dict
    data: bytes


def check_cancel(cancelled):
    if cancelled and cancelled():
        raise BackupCancelled('操作已取消，原数据未丢弃。')


def safe_name(name):
    """Windows names are checked on every OS, before any filesystem access."""
    if not isinstance(name, str) or not name or len(name.encode('utf-8')) > 240:
        raise BackupError('备份包含无效文件名。')
    if name in ('.', '..') or name[-1:] in ('.', ' '):
        raise BackupError('备份包含不安全路径。')
    if any(ord(char) < 32 or char in '<>:"/\\|?*' for char in name):
        raise BackupError('备份包含不安全路径。')
    stem = name.split('.')[0].rstrip(' ').upper()
    if stem in ('CON', 'PRN', 'AUX', 'NUL', 'CLOCK$', 'CONIN$', 'CONOUT$') or re.fullmatch(r'(COM|LPT)[1-9¹²³]', stem):
        raise BackupError('备份使用了 Windows 保留文件名。')
    return name


def safe_member(name):
    if name in ('manifest.json', 'data.json'):
        return name
    if isinstance(name, str) and name.startswith('images/') and name.count('/') == 1:
        safe_name(name[7:])
        return name
    raise BackupError('备份包含未允许的成员路径。')


def plain_path(path, *, missing_ok=False):
    """Never follow a symlink/junction supplied as an image or transaction path."""
    path = Path(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        if missing_ok:
            return path
        raise BackupError('备份所需文件不存在：' + path.name)
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise BackupError('数据位置包含链接或重解析点：' + path.name)
    return path


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BackupError('JSON 包含重复字段。')
        result[key] = value
    return result


def parse_json(raw):
    try:
        return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_object,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (UnicodeError, ValueError, RecursionError) as error:
        raise BackupError('JSON 内容无效或嵌套过深。') from error


def data_details(raw):
    data = parse_json(raw)
    if not isinstance(data, dict):
        raise BackupError('数据根节点必须是对象。')
    version = data.get('schema_version', 1)
    if type(version) is not int or not 1 <= version <= SCHEMA_VERSION:
        raise BackupError('备份的数据格式版本不兼容当前程序。')
    if 'settings' in data and not isinstance(data['settings'], dict):
        raise BackupError('备份中的设置必须是对象。')
    clips, groups = data.get('clip', []), data.get('groups', [])
    if not isinstance(clips, list) or not isinstance(groups, list):
        raise BackupError('历史或常用语结构无效。')
    phrases = []
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get('name'), str):
            raise BackupError('常用语分组结构无效。')
        items = group.get('items', [])
        if not isinstance(items, list):
            raise BackupError('常用语条目结构无效。')
        phrases.extend(items)
    names, external = set(), 0
    folded = {}
    for item in (*clips, *phrases):
        if not isinstance(item, dict) or not isinstance(item.get('text'), str):
            raise BackupError('数据包含无效条目。')
        name = item.get('image_path')
        if name:
            safe_name(name)
            other = folded.setdefault(name.casefold(), name)
            if other != name:
                raise BackupError('图片名称存在大小写冲突。')
            names.add(name)
        elif item.get('content_type') == 'image':
            raise BackupError('图片条目缺少图片文件引用。')
        external += item.get('content_type') in ('filelist', 'files')
    if len(names) + 2 > MAX_MEMBERS:
        raise BackupError('图片成员数量超过上限。')
    return dict(schema_version=version, clip_count=len(clips), phrase_count=len(phrases),
                external_file_count=external), sorted(names)


def read_file(path, limit, cancelled=None):
    path = plain_path(path)
    if not path.is_file() or path.stat().st_size > limit:
        raise BackupError('文件类型无效或大小超过上限：' + path.name)
    chunks, size = [], 0
    with path.open('rb') as stream:
        while True:
            check_cancel(cancelled)
            chunk = stream.read(min(CHUNK_SIZE, limit + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise BackupError('文件大小超过上限：' + path.name)
            chunks.append(chunk)
    return b''.join(chunks)


def stream_hash(stream, limit, cancelled=None):
    result, size = hashlib.sha256(), 0
    while True:
        check_cancel(cancelled)
        chunk = stream.read(min(CHUNK_SIZE, limit + 1 - size))
        if not chunk:
            return result.hexdigest(), size
        size += len(chunk)
        if size > limit:
            raise BackupError('文件大小超过上限。')
        result.update(chunk)


def write_package(destination, raw, image_paths, *, details=None, safety=False,
                  data_present=True, cancelled=None):
    """Atomic package publication; only the injected source paths are read."""
    destination = Path(destination)
    if len(raw) > MAX_JSON_BYTES or len(image_paths) + 2 > MAX_MEMBERS:
        raise BackupError('数据大小或成员数量超过备份上限。')
    details = details or dict(schema_version=0, clip_count=0, phrase_count=0, external_file_count=0)
    manifest = dict(format=FORMAT, format_version=FORMAT_VERSION,
                    created_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                    app_version=APP_VER, kind='safety-snapshot' if safety else 'backup',
                    data_present=data_present, external_files_included=False, **details)
    destination.parent.mkdir(parents=True, exist_ok=True)
    plain_path(destination.parent)
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix='.backup-', suffix='.tmp', dir=destination.parent)
        os.close(fd)
        entries, total, folded = [], 0, set()
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=False) as archive:
            sources = [('data.json', raw)] + [('images/' + safe_name(name), path)
                                             for name, path in image_paths]
            for member, source in sources:
                check_cancel(cancelled)
                key = member.casefold()
                if key in folded:
                    raise BackupError('备份成员名称重复。')
                folded.add(key)
                hasher, size = hashlib.sha256(), 0
                if isinstance(source, bytes):
                    archive.writestr(member, source)
                    hasher.update(source)
                    size = len(source)
                else:
                    source = plain_path(source)
                    if not source.is_file() or source.stat().st_size > MAX_IMAGE_BYTES:
                        raise BackupError('图片类型无效或大小超过上限。')
                    with source.open('rb') as reader, archive.open(member, 'w') as writer:
                        while True:
                            check_cancel(cancelled)
                            chunk = reader.read(CHUNK_SIZE)
                            if not chunk:
                                break
                            size += len(chunk)
                            if size > MAX_IMAGE_BYTES or total + size > MAX_TOTAL_BYTES:
                                raise BackupError('备份大小超过上限。')
                            hasher.update(chunk)
                            writer.write(chunk)
                total += size
                if total > MAX_TOTAL_BYTES:
                    raise BackupError('备份大小超过上限。')
                entries.append(dict(path=member, size=size, sha256=hasher.hexdigest()))
            manifest.update(members=entries, image_count=len(image_paths), total_bytes=total)
            encoded = json_bytes(manifest)
            if len(encoded) > MAX_MANIFEST_BYTES or total + len(encoded) > MAX_TOTAL_BYTES:
                raise BackupError('备份清单或总大小超过上限。')
            archive.writestr('manifest.json', encoded)
        with open(temporary, 'r+b') as stream:
            os.fsync(stream.fileno())
            digest, _ = stream_hash(stream, MAX_ARCHIVE_BYTES, cancelled)
        check_cancel(cancelled)
        os.replace(temporary, destination)
        return BackupPreview(destination, digest, manifest['created_at'], APP_VER,
                             details['clip_count'], details['phrase_count'], len(image_paths),
                             total, details['external_file_count'])
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as error:
        if isinstance(error, BackupError):
            raise
        raise BackupError('创建备份失败：' + str(error)) from error
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def _central_directory(stream):
    """Bound the directory before ZipFile allocates one object per member."""
    stream.seek(0, 2)
    size = stream.tell()
    if size > MAX_ARCHIVE_BYTES or size < 22:
        raise BackupError('备份包大小无效。')
    stream.seek(max(0, size - 65557))
    tail = stream.read(65557)
    index = tail.rfind(b'PK\x05\x06')
    if index < 0 or index + 22 != len(tail):
        raise BackupError('ZIP 目录或尾部无效。')
    _, disk, start_disk, count_disk, count, directory_size, offset, comment = struct.unpack(
        '<4s4H2LH', tail[index:index + 22])
    if (disk or start_disk or comment or count != count_disk or count > MAX_MEMBERS
            or count < 2 or directory_size > MAX_MEMBERS * 1024
            or offset + directory_size != size - 22):
        raise BackupError('ZIP 分卷、ZIP64、成员数量或目录大小不受支持。')
    stream.seek(offset)
    actual = 0
    while stream.tell() < offset + directory_size:
        header = stream.read(46)
        if len(header) != 46 or header[:4] != b'PK\x01\x02':
            raise BackupError('ZIP 中央目录记录无效。')
        name_size, extra_size, comment_size = struct.unpack('<3H', header[28:34])
        actual += 1
        if (actual > MAX_MEMBERS or name_size > 300 or extra_size > 1024 or comment_size
                or stream.tell() + name_size + extra_size > offset + directory_size):
            raise BackupError('ZIP 中央目录成员数量或元数据超过上限。')
        stream.seek(name_size + extra_size, 1)
    if actual != count or stream.tell() != offset + directory_size:
        raise BackupError('ZIP 成员数量与目录不一致。')
    return offset


def _zip_read(archive, info, limit, cancelled, destination=None):
    if info.file_size > limit:
        raise BackupError('备份成员大小超过上限。')
    hasher, size, chunks = hashlib.sha256(), 0, []
    with archive.open(info, 'r') as reader:
        writer = destination.open('wb') if destination else None
        try:
            while True:
                check_cancel(cancelled)
                chunk = reader.read(min(CHUNK_SIZE, limit + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > limit or size > info.file_size:
                    raise BackupError('备份成员实际大小超过上限。')
                hasher.update(chunk)
                if writer:
                    writer.write(chunk)
                elif info.filename in ('data.json', 'manifest.json'):
                    chunks.append(chunk)
            if writer:
                writer.flush()
                os.fsync(writer.fileno())
        finally:
            if writer:
                writer.close()
    if size != info.file_size:
        raise BackupError('备份成员大小不一致。')
    return b''.join(chunks), hasher.hexdigest(), size


def read_package(path, *, staging=None, expected_sha256=None, cancelled=None):
    path = plain_path(path)
    try:
        with path.open('rb') as source:
            digest, _ = stream_hash(source, MAX_ARCHIVE_BYTES, cancelled)
            if expected_sha256 is not None and digest != expected_sha256:
                raise BackupError('备份包已变化，请重新预览。')
            central = _central_directory(source)
            with zipfile.ZipFile(source, 'r', allowZip64=False) as archive:
                infos, folded, offsets = {}, set(), set()
                total = 0
                for info in archive.infolist():
                    safe_member(info.orig_filename)
                    mode = info.external_attr >> 16
                    if (info.filename != info.orig_filename or info.is_dir()
                            or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                            or info.flag_bits & ~0x808
                            or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                            or len(info.extra) > 1024 or info.comment
                            or not 0 <= info.header_offset < central
                            or info.header_offset in offsets or info.filename.casefold() in folded):
                        raise BackupError('ZIP 成员属性、名称或压缩方式无效。')
                    total += info.file_size
                    if total > MAX_TOTAL_BYTES:
                        raise BackupError('备份解压总大小超过上限。')
                    infos[info.filename] = info
                    folded.add(info.filename.casefold())
                    offsets.add(info.header_offset)
                if 'manifest.json' not in infos or 'data.json' not in infos:
                    raise BackupError('备份缺少清单或数据文件。')
                raw, _, _ = _zip_read(archive, infos['manifest.json'], MAX_MANIFEST_BYTES, cancelled)
                manifest = parse_json(raw)
                if (not isinstance(manifest, dict) or manifest.get('format') != FORMAT
                        or type(manifest.get('format_version')) is not int
                        or manifest['format_version'] != FORMAT_VERSION
                        or manifest.get('kind') not in ('backup', 'safety-snapshot')
                        or manifest.get('external_files_included') is not False):
                    raise BackupError('备份格式或版本不兼容。')
                members = manifest.get('members')
                if not isinstance(members, list) or len(members) != len(infos) - 1:
                    raise BackupError('备份清单成员不一致。')
                declared, payload = set(), None
                payload_total = 0
                for member in members:
                    if not isinstance(member, dict):
                        raise BackupError('备份清单成员无效。')
                    name = safe_member(member.get('path'))
                    if (name == 'manifest.json' or name in declared or name not in infos
                            or type(member.get('size')) is not int or member['size'] < 0
                            or not isinstance(member.get('sha256'), str)
                            or not re.fullmatch('[0-9a-f]{64}', member['sha256'])):
                        raise BackupError('备份清单成员无效或重复。')
                    declared.add(name)
                    target = None
                    if staging:
                        target = Path(staging) / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                    limit = MAX_JSON_BYTES if name == 'data.json' else MAX_IMAGE_BYTES
                    raw, member_hash, size = _zip_read(archive, infos[name], limit, cancelled, target)
                    if size != member['size'] or member_hash != member['sha256']:
                        raise BackupError('备份校验失败：' + name)
                    payload_total += size
                    if name == 'data.json':
                        payload = read_file(target, MAX_JSON_BYTES, cancelled) if target else raw
                details, image_names = data_details(payload)
                expected = {'data.json'} | {'images/' + name for name in image_names}
                if (not expected.issubset(declared)
                        or manifest['kind'] == 'backup' and declared != expected):
                    raise BackupError('图片引用与备份成员不一致，可能缺少图片。')
                image_count = len(declared) - 1
                for key, value in dict(details, image_count=image_count, total_bytes=payload_total).items():
                    if type(manifest.get(key)) is not int or manifest[key] != value:
                        raise BackupError('备份清单统计与内容不一致。')
                for key in ('created_at', 'app_version'):
                    if not isinstance(manifest.get(key), str) or len(manifest[key]) > 100:
                        raise BackupError('备份元数据无效。')
                source.seek(0)
                final_digest, _ = stream_hash(source, MAX_ARCHIVE_BYTES, cancelled)
                if digest != final_digest:
                    raise BackupError('读取期间备份包发生变化。')
                preview = BackupPreview(path, digest, manifest['created_at'], manifest['app_version'],
                    details['clip_count'], details['phrase_count'], image_count, payload_total,
                    details['external_file_count'])
                return Package(preview, manifest, payload)
    except (OSError, ValueError, zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError) as error:
        if isinstance(error, BackupError):
            raise
        raise BackupError('读取备份失败：' + str(error)) from error
