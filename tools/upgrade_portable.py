# -*- coding: utf-8 -*-
"""开发工具，不参与产品运行：备份后原位替换便携 exe，不安装、不启动、不写注册表。

plan 只读并给出审阅摘要与 plan_sha256；backup 必须提供该摘要标识；
apply/rollback 必须提供已审阅的 plan_sha256 和私密备份 manifest.json。
备份仅含指定旧 exe、同层 ClawBoard数据.json、images/ 的直接普通文件。
没有 App 构造；JsonStore 只用于只读核对，任何归一化导致原值改变都会中止。
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import sys
import time
import uuid
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clawboard.storage import JsonStore


class UpgradeError(RuntimeError):
    """仅使用不含用户正文、标题或任意字段值的错误消息。"""


def _safe_path(value, directory=False):
    path = Path(value)
    if (not path.is_absolute() or '..' in path.parts or
            str(path).startswith(('\\\\', '//')) or
            any(':' in part for part in path.parts[1:])):
        raise UpgradeError('unsafe path')
    for node in reversed((path, *path.parents)):
        try:
            info = node.lstat()
        except OSError as error:
            raise UpgradeError('required path is unavailable') from error
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise UpgradeError('symlink or reparse point rejected')
    info = path.lstat()
    if directory:
        valid = stat.S_ISDIR(info.st_mode)
    else:
        valid = stat.S_ISREG(info.st_mode) and info.st_nlink == 1
    if not valid:
        raise UpgradeError('expected a plain directory or unlinked regular file')
    return path


def _file_record(path):
    path = _safe_path(path)
    first = path.stat()
    digest = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (first.st_dev, first.st_ino):
            raise UpgradeError('source changed while opening')
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    last = _safe_path(path).stat()
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size,
                              value.st_mtime_ns, value.st_ctime_ns)
    if identity(first) != identity(last):
        raise UpgradeError('source changed while reading')
    return dict(sha256=digest.hexdigest(), size=last.st_size, mtime_ns=last.st_mtime_ns,
                ctime_ns=last.st_ctime_ns, device=last.st_dev, inode=last.st_ino)


def _open_source(path, expected):
    path = _safe_path(path)
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    stream = os.fdopen(os.open(path, flags), 'rb')
    try:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) !=
                tuple(expected[key] for key in ('device', 'inode', 'size', 'mtime_ns'))):
            raise UpgradeError('source changed before archive read')
        # Windows 的 stat/fstat 对 ctime 可能报告不同时间；ctime 只与同一套路径 API 比较。
        if _safe_path(path).stat().st_ctime_ns != expected['ctime_ns']:
            raise UpgradeError('source metadata changed before archive read')
        return stream
    except Exception:
        stream.close()
        raise


def _exe(path):
    path = _safe_path(path)
    if path.suffix.lower() != '.exe':
        raise UpgradeError('expected an exe file')
    with path.open('rb') as stream:
        header = stream.read(64)
        if len(header) != 64 or header[:2] != b'MZ':
            raise UpgradeError('invalid executable header')
        offset = struct.unpack_from('<I', header, 60)[0]
        if offset < 64 or offset > path.stat().st_size - 4:
            raise UpgradeError('invalid executable header')
        stream.seek(offset)
        if stream.read(4) != b'PE\0\0':
            raise UpgradeError('invalid executable header')
    return path


def _assert_idle(current):
    """只读枚举进程；同名进程也保守阻止，不读取窗口标题或结束进程。"""
    if os.name != 'nt':
        raise UpgradeError('process inspection requires Windows')
    from ctypes import wintypes
    class Entry(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                    ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.c_size_t),
                    ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
                    ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', wintypes.LONG),
                    ('dwFlags', wintypes.DWORD), ('szExeFile', wintypes.WCHAR * 260)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ('Process32FirstW', 'Process32NextW'):
        function = getattr(kernel, name)
        function.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
        function.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle in (None, ctypes.c_void_p(-1).value):
        raise UpgradeError('process inspection failed')
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(entry)
        if not kernel.Process32FirstW(handle, ctypes.byref(entry)):
            raise UpgradeError('process inspection failed')
        while True:
            if entry.szExeFile.casefold() == current.name.casefold():
                raise UpgradeError('current executable process is running')
            if not kernel.Process32NextW(handle, ctypes.byref(entry)):
                if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
                    raise UpgradeError('process inspection incomplete')
                break
    finally:
        kernel.CloseHandle(handle)


def _paths(current):
    current = _exe(current)
    parent = _safe_path(current.parent, directory=True)
    if (parent == parent.parent or parent == Path.home() or
            not re.fullmatch(r'ClawBoard(?:-[A-Za-z0-9][A-Za-z0-9._-]*)?\.exe', current.name, re.I)):
        raise UpgradeError('unsafe portable executable location')
    paths = [current, _safe_path(parent / 'ClawBoard数据.json')]
    images = parent / 'images'
    if os.path.lexists(images):
        _safe_path(images, directory=True)
        paths.extend(_safe_path(item) for item in sorted(images.iterdir(), key=lambda p: p.name))
    return paths


def _snapshot(current):
    return {path.relative_to(current.parent).as_posix(): _file_record(path)
            for path in _paths(current)}


def _preserved(original, normalized):
    if type(original) is not type(normalized):
        return False
    if isinstance(original, dict):
        return all(key in normalized and _preserved(value, normalized[key])
                   for key, value in original.items())
    if isinstance(original, list):
        return len(original) == len(normalized) and all(map(lambda pair: _preserved(*pair),
                                                          zip(original, normalized)))
    return original == normalized


def _semantics(current, files):
    data_path = current.parent / 'ClawBoard数据.json'
    try:
        raw = json.loads(data_path.read_text(encoding='utf-8-sig'))
        loaded = JsonStore(data_path).load()
    except (OSError, ValueError, RecursionError) as error:
        raise UpgradeError('data cannot be read safely') from error
    if loaded.recovery_required or not isinstance(raw, dict) or not _preserved(raw, loaded.data):
        raise UpgradeError('normalization would alter an existing value or structure')
    data = loaded.data
    records = data['clip'] + [item for group in data['groups'] for item in group['items']]
    references = set()
    for item in records:
        name = item.get('image_path')
        if item.get('content_type') == 'image' and not name:
            raise UpgradeError('image record has no file reference')
        if name:
            if (not isinstance(name, str) or Path(name).name != name or
                    '/' in name or '\\' in name or ':' in name or name in ('.', '..')):
                raise UpgradeError('unsafe image reference')
            relative = 'images/' + name
            if relative not in files:
                raise UpgradeError('referenced image is missing')
            references.add(relative)
    return dict(schema_version=data['schema_version'], history_count=len(data['clip']),
                group_count=len(data['groups']), phrase_count=sum(len(g['items']) for g in data['groups']),
                image_count=sum(name.startswith('images/') for name in files),
                referenced_image_count=len(references))


def plan_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                     separators=(',', ':')).encode()).hexdigest()


def _match_hash(actual, expected):
    if expected is not None and (not isinstance(expected, str) or
                                 not re.fullmatch('[0-9a-fA-F]{64}', expected) or
                                 actual != expected.lower()):
        raise UpgradeError('reviewed hash does not match')


def _reviewed(value, expected):
    if expected is None:
        raise UpgradeError('reviewed plan hash is required')
    _match_hash(plan_sha256(value), expected)


def plan(current, candidate, *, expected_old_sha=None, expected_new_sha=None):
    """只读：不创建目录、不备份、不修改 JSON，不输出正文。"""
    current, candidate = _exe(current), _exe(candidate)
    _paths(current)
    if candidate.is_relative_to(current.parent):
        raise UpgradeError('candidate must be outside the portable directory')
    _assert_idle(current)
    files = _snapshot(current)
    replacement = _file_record(candidate)
    _match_hash(files[current.name]['sha256'], expected_old_sha)
    _match_hash(replacement['sha256'], expected_new_sha)
    semantics = _semantics(current, files)
    value = dict(format=1, current=str(current), candidate=str(candidate),
                 files=files, replacement=replacement, semantics=semantics)
    _same_source(value)
    return value


def summary(value):
    current = Path(value['current'])
    return dict(plan_sha256=plan_sha256(value), old_exe_sha256=value['files'][current.name]['sha256'],
                new_exe_sha256=value['replacement']['sha256'],
                data_sha256=value['files']['ClawBoard数据.json']['sha256'], **value['semantics'])


def _same_source(value):
    current = Path(value['current'])
    _assert_idle(current)
    if (_snapshot(current) != value['files'] or
            _file_record(Path(value['candidate'])) != value['replacement']):
        raise UpgradeError('source changed since the reviewed plan')


def _verify_archive(archive_path, value):
    expected = value['files']
    try:
        with zipfile.ZipFile(_safe_path(archive_path)) as archive:
            names = [item.filename for item in archive.infolist()]
            if len(names) != len(expected) or set(names) != set(expected) or archive.testzip() is not None:
                raise UpgradeError('backup archive entries or CRC do not match')
            for info in archive.infolist():
                if info.is_dir() or stat.S_ISLNK(info.external_attr >> 16):
                    raise UpgradeError('unsafe backup archive entry')
                digest = hashlib.sha256()
                with archive.open(info) as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(block)
                if (info.file_size != expected[info.filename]['size'] or
                        digest.hexdigest() != expected[info.filename]['sha256']):
                    raise UpgradeError('backup archive item hash does not match')
    except (OSError, zipfile.BadZipFile, RuntimeError, zlib.error) as error:
        if isinstance(error, UpgradeError):
            raise
        raise UpgradeError('backup archive validation failed') from error


def _write_json(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=True, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())


def backup(value, *, expected_plan_sha):
    """只新建一个私密备份目录；失败没有 ready manifest，不改变任何源文件。"""
    _reviewed(value, expected_plan_sha)
    _same_source(value)
    current = Path(value['current'])
    directory = current.parent / ('backup-' + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:12])
    directory.mkdir(mode=0o700)
    archive_path = directory / 'portable-backup.zip'
    try:
        # Windows 的只读 fd 不能 fsync，必须在新建写句柄关闭前完成 ZIP 尾部与落盘。
        with archive_path.open('xb') as output:
            with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for name, expected in value['files'].items():
                    with _open_source(current.parent / name, expected) as source, archive.open(name, 'w') as target:
                        shutil.copyfileobj(source, target, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        _same_source(value)
        _verify_archive(archive_path, value)
        _same_source(value)
        manifest = directory / 'manifest.json'
        _write_json(manifest, dict(format=1, state='ready', plan_sha256=expected_plan_sha,
                                   plan=value, archive_sha256=_file_record(archive_path)['sha256']))
        return manifest
    except Exception:
        _write_json(directory / 'aborted.json', dict(state='aborted', reason='backup did not validate'))
        raise


def _read_backup(manifest, expected_plan_sha):
    manifest = _safe_path(manifest)
    try:
        document = json.loads(manifest.read_text(encoding='utf-8'))
        value = document['plan']
        _reviewed(value, expected_plan_sha)
        if document['plan_sha256'] != expected_plan_sha or document['state'] != 'ready':
            raise UpgradeError('backup is not ready or not reviewed')
        current = _exe(Path(value['current']))
        if (manifest.name != 'manifest.json' or manifest.parent.parent != current.parent or
                not manifest.parent.name.startswith('backup-')):
            raise UpgradeError('backup is outside the portable backup directory')
        archive = manifest.parent / 'portable-backup.zip'
        _match_hash(_file_record(archive)['sha256'], document['archive_sha256'])
        _verify_archive(archive, value)
        return value, archive
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise UpgradeError('backup manifest validation failed') from error


def _stage(current, reader, expected_sha):
    staged = current.parent / ('.ClawBoard-upgrade-' + uuid.uuid4().hex + '.tmp')
    try:
        with staged.open('xb') as output, reader() as source:
            shutil.copyfileobj(source, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        _match_hash(_file_record(staged)['sha256'], expected_sha)
        return staged
    except Exception:
        staged.unlink(missing_ok=True)
        raise


def apply(manifest, *, expected_plan_sha):
    """只原子替换旧同名 exe；旧 exe 永久保留在已逐项校验的私密 ZIP 中。"""
    value, _ = _read_backup(manifest, expected_plan_sha)
    current, candidate = Path(value['current']), _exe(Path(value['candidate']))
    _same_source(value)
    staged = _stage(current, lambda: candidate.open('rb'), value['replacement']['sha256'])
    try:
        _same_source(value)
        os.replace(staged, current)
        _match_hash(_file_record(current)['sha256'], value['replacement']['sha256'])
        remaining = _snapshot(current)
        if ({k: v for k, v in remaining.items() if k != current.name} !=
                {k: v for k, v in value['files'].items() if k != current.name}):
            raise UpgradeError('data changed during executable replacement; backup retained')
    finally:
        staged.unlink(missing_ok=True)
    return dict(state='applied', executable_sha256=value['replacement']['sha256'], backup_retained=True)


def rollback(manifest, *, expected_plan_sha):
    """只恢复旧 exe；允许升级后新增历史，始终保留当前 JSON/images 原样。"""
    value, archive_path = _read_backup(manifest, expected_plan_sha)
    current = Path(value['current'])
    _assert_idle(current)
    before = _snapshot(current)
    _match_hash(before[current.name]['sha256'], value['replacement']['sha256'])
    with zipfile.ZipFile(archive_path) as archive:
        staged = _stage(current, lambda: archive.open(current.name), value['files'][current.name]['sha256'])
    try:
        _assert_idle(current)
        if _snapshot(current) != before:
            raise UpgradeError('source changed during rollback preparation')
        os.replace(staged, current)
        _match_hash(_file_record(current)['sha256'], value['files'][current.name]['sha256'])
        after = _snapshot(current)
        if ({k: v for k, v in after.items() if k != current.name} !=
                {k: v for k, v in before.items() if k != current.name}):
            raise UpgradeError('data changed during rollback; backup retained')
    finally:
        staged.unlink(missing_ok=True)
    return dict(state='rolled_back', executable_sha256=value['files'][current.name]['sha256'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('plan', 'backup'):
        command = commands.add_parser(name)
        command.add_argument('--current', required=True, type=Path)
        command.add_argument('--candidate', required=True, type=Path)
        command.add_argument('--expect-old-sha')
        command.add_argument('--expect-new-sha')
        if name == 'backup':
            command.add_argument('--expect-plan-sha', required=True)
    for name in ('apply', 'rollback'):
        command = commands.add_parser(name)
        command.add_argument('--manifest', required=True, type=Path)
        command.add_argument('--expect-plan-sha', required=True)
    arguments = parser.parse_args(argv)
    try:
        if arguments.command in ('plan', 'backup'):
            value = plan(arguments.current, arguments.candidate, expected_old_sha=arguments.expect_old_sha,
                         expected_new_sha=arguments.expect_new_sha)
            result = summary(value)
            if arguments.command == 'backup':
                result['manifest'] = str(backup(value, expected_plan_sha=arguments.expect_plan_sha))
        else:
            result = globals()[arguments.command](arguments.manifest, expected_plan_sha=arguments.expect_plan_sha)
        print(json.dumps(result, ensure_ascii=True), flush=True)
        return 0
    except (UpgradeError, OSError, ValueError) as error:
        # 文件系统异常可能带用户路径；只输出错误类型，不打印任意原始异常或数据。
        message = str(error) if isinstance(error, UpgradeError) else type(error).__name__
        print(json.dumps(dict(state='aborted', reason=message)), file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
