"""Bounded, read-only ClawBoard import sources; no UI or library writes.

JSON exports contain references rather than image bytes. They deliberately do
not grant permission to read adjacent files; complete ZIP packages are the only
source of imported image bodies.
"""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

from clawboard.backup_format import (
    BackupCancelled, BackupError, MAX_JSON_BYTES, check_cancel, json_bytes,
    parse_json, plain_path, read_file, read_package, safe_name,
)
from clawboard.config import APP_NAME, APP_VER, SCHEMA_VERSION
from clawboard.trash import image_references


MAX_IMPORT_ITEMS = 10000


class ImportError(BackupError):
    """The source was rejected before any library data was changed."""


@dataclass(frozen=True)
class ImportEntry:
    key: str
    section: str
    group_key: str
    group_name: str
    item: dict
    images: tuple[str, ...]
    issue: str = ''


@dataclass(frozen=True)
class ImportSource:
    path: Path
    sha256: str
    kind: str
    entries: tuple[ImportEntry, ...]
    image_hashes: dict[str, str]


def _schema(value):
    if type(value) is not int or not 1 <= value <= SCHEMA_VERSION:
        raise ImportError('导入文件的数据格式版本不兼容。')


def _app_version(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,6}(?:\.\d{1,6}){0,3}', value):
        raise ImportError('导出文件的程序版本无效。')
    version = tuple(int(part) for part in value.split('.'))
    current = tuple(int(part) for part in APP_VER.split('.'))
    if version + (0,) * (4 - len(version)) > current + (0,) * (4 - len(current)):
        raise ImportError('导出文件来自更新版本，请先更新程序。')


def _payload(data, *, backup=False):
    if not isinstance(data, dict):
        raise ImportError('导入文件根节点必须是对象。')
    if 'items' in data:
        if backup or 'clip' in data or 'groups' in data:
            raise ImportError('导入文件同时包含不同导出结构。')
        _schema(data.get('version'))
        if 'schema_version' in data:
            _schema(data['schema_version'])
        return 'json-items', data['items'], []
    if 'clip' not in data and 'groups' not in data:
        raise ImportError('未找到 ClawBoard 历史或常用语资料。')
    _schema(data.get('schema_version', 1))
    if backup:
        kind = 'backup'
    elif 'app' in data:
        if data['app'] != APP_NAME:
            raise ImportError('当前仅支持 ClawBoard 自身的导出文件。')
        _app_version(data.get('version'))
        kind = 'json-all'
    else:
        kind = 'json-library'
    return kind, data.get('clip', []), data.get('groups', [])


def _image_names(item):
    # The conservative GC helper also recognizes optional nested metadata.
    # Validate every explicit reference before using those same references.
    pending = [item]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            name = value.get('image_path')
            if name is not None and not isinstance(name, str):
                raise ImportError('导入条目的图片引用结构无效。')
            if name:
                safe_name(name)
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    return tuple(sorted(image_references({'clip': [item]})))


def _entry(raw, key, section, group_key, group_name, image_hashes):
    if not isinstance(raw, dict) or not isinstance(raw.get('text'), str):
        raise ImportError('导入文件包含无效条目，未忽略或修改任何内容。')
    item = deepcopy(raw)
    # Escaped lone surrogates can parse as JSON but cannot be safely saved by
    # the product's UTF-8 writer. Reject them before presenting an import.
    json_bytes(item)
    images = _image_names(item)
    missing = any(name not in image_hashes for name in images)
    image_without_path = item.get('content_type') == 'image' and not item.get('image_path')
    issue = ('缺少图片正文，请使用包含图片的完整备份包。'
             if missing or image_without_path else '')
    return ImportEntry(key, section, group_key, group_name, item, images, issue)


def _entries(clips, groups, image_hashes, cancelled):
    if not isinstance(clips, list) or not isinstance(groups, list):
        raise ImportError('历史或常用语列表结构无效。')
    if len(clips) > MAX_IMPORT_ITEMS or len(groups) > MAX_IMPORT_ITEMS:
        raise ImportError('导入条目或分组数量超过上限。')
    count = len(clips)
    for group in groups:
        if (not isinstance(group, dict) or not isinstance(group.get('name'), str)
                or not isinstance(group.get('items', []), list)):
            raise ImportError('常用语分组结构无效。')
        group['name'].encode('utf-8')
        count += len(group.get('items', []))
        if count > MAX_IMPORT_ITEMS:
            raise ImportError('导入条目数量超过上限。')
    result, folded = [], {}

    def append(raw, key, section, group_key='', group_name=''):
        check_cancel(cancelled)
        entry = _entry(raw, key, section, group_key, group_name, image_hashes)
        for name in entry.images:
            other = folded.setdefault(name.casefold(), name)
            if other != name:
                raise ImportError('图片名称存在大小写冲突。')
        result.append(entry)

    for index, item in enumerate(clips):
        append(item, 'c:%d' % index, 'clip')
    for group_index, group in enumerate(groups):
        group_key = 'g:%d' % group_index
        for item_index, item in enumerate(group.get('items', [])):
            append(item, '%s:%d' % (group_key, item_index), 'phrase', group_key, group['name'])
    return tuple(result)


def _staging(path):
    """Extraction may fill only an empty, caller-owned temporary directory."""
    if path is None:
        return None
    directory = Path(path).absolute()
    plain_path(directory.parent)
    plain_path(directory, missing_ok=True)
    if directory.exists():
        if not directory.is_dir() or any(directory.iterdir()):
            raise ImportError('导入暂存目录必须为空。')
    else:
        directory.mkdir()
    return directory


def read_source(path, *, expected_sha256=None, staging=None, cancelled=None):
    """Return detached records; JSON never reads or writes adjacent assets.

    ZIP extraction is optional and only accepts a fresh empty caller-owned
    directory. The caller owns disposal of that directory on success/failure.
    """
    try:
        source = Path(path).absolute()
        if expected_sha256 is not None:
            if not isinstance(expected_sha256, str) or not re.fullmatch('[0-9a-fA-F]{64}', expected_sha256):
                raise ImportError('导入文件校验值无效，请重新预览。')
            expected_sha256 = expected_sha256.lower()
        check_cancel(cancelled)
        if source.suffix.lower() == '.zip':
            package = read_package(source, expected_sha256=expected_sha256,
                                   staging=_staging(staging), cancelled=cancelled)
            _app_version(package.preview.app_version)
            data = parse_json(package.data)
            kind, clips, groups = _payload(data, backup=True)
            image_hashes = {member['path'][7:]: member['sha256']
                            for member in package.manifest['members']
                            if member['path'].startswith('images/')}
            digest = package.preview.sha256
        elif source.suffix.lower() == '.json':
            raw = read_file(source, MAX_JSON_BYTES, cancelled)
            digest = hashlib.sha256(raw).hexdigest()
            if expected_sha256 is not None and digest != expected_sha256:
                raise ImportError('导入文件已变化，请重新预览。')
            kind, clips, groups = _payload(parse_json(raw))
            image_hashes = {}
        else:
            raise ImportError('请选择 ClawBoard JSON 导出或完整 ZIP 备份包。')
        entries = _entries(clips, groups, image_hashes, cancelled)
        check_cancel(cancelled)
        return ImportSource(source, digest, kind, entries, image_hashes)
    except BackupCancelled:
        raise
    except ImportError:
        raise
    except (OSError, ValueError, TypeError, RecursionError, UnicodeError):
        # Imported values and private paths must never become error messages.
        raise ImportError('导入文件无法读取，或格式、图片引用及校验无效。') from None
