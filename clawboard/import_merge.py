"""Pure, additive import planning; callers persist only an error-free plan.

The entire existing library is copied intact. New records cross normalization
individually, so importing never changes settings or repairs an unrelated item.
"""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
from pathlib import PurePath

from clawboard.classify import crop_items
from clawboard.config import DEFAULT_SETTINGS, SCHEMA_VERSION
from clawboard.import_source import ImportError, MAX_IMPORT_ITEMS
from clawboard.models import normalize_item
from clawboard.privacy import scan_sensitive
from clawboard.runtime import uid
from clawboard.trash import image_references


@dataclass(frozen=True)
class MergeRow:
    key: str
    status: str
    message: str


@dataclass(frozen=True)
class MergePlan:
    data: dict
    rows: tuple[MergeRow, ...]
    imported_count: int
    duplicate_count: int
    disabled_trigger_count: int
    image_map: dict[str, str]
    error: str = ''


def _current(data):
    if (not isinstance(data, dict) or not isinstance(data.get('clip'), list)
            or not isinstance(data.get('groups'), list)):
        raise ImportError('当前历史或常用语结构无效，未开始导入。')
    version = data.get('schema_version', 1)
    if type(version) is not int or not 1 <= version <= SCHEMA_VERSION:
        raise ImportError('当前资料库格式不兼容，未开始导入。')
    items = list(data['clip'])
    for group in data['groups']:
        if (not isinstance(group, dict) or not isinstance(group.get('name'), str)
                or not isinstance(group.get('items'), list)):
            raise ImportError('当前常用语分组结构无效，未开始导入。')
        items.extend(group['items'])
    if any(not isinstance(item, dict) or not isinstance(item.get('text'), str)
           for item in items):
        raise ImportError('当前资料包含无效条目，未开始导入。')
    if 'settings' in data and not isinstance(data['settings'], dict):
        raise ImportError('当前设置结构无效，未开始导入。')
    return items


def _selected(entries, selected):
    if len(entries) > MAX_IMPORT_ITEMS:
        raise ImportError('导入条目数量超过上限。')
    known = set()
    for entry in entries:
        if not isinstance(entry.key, str) or not entry.key or entry.key in known:
            raise ImportError('导入条目标识无效。')
        known.add(entry.key)
    if selected is None:
        return entries
    if isinstance(selected, (str, bytes)):
        raise ImportError('请选择有效的导入条目。')
    chosen = set()
    try:
        for index, key in enumerate(selected):
            if (index >= MAX_IMPORT_ITEMS or not isinstance(key, str)
                    or key not in known or key in chosen):
                raise ImportError('所选条目标识无效，请重新预览。')
            chosen.add(key)
    except TypeError as error:
        raise ImportError('请选择有效的导入条目。') from error
    return tuple(entry for entry in entries if entry.key in chosen)


def _identifiers(data):
    pending, seen, result = [data], set(), set()
    while pending:
        value = pending.pop()
        if not isinstance(value, (dict, list)) or id(value) in seen:
            continue
        seen.add(id(value))
        if isinstance(value, dict):
            for key in ('id', 'recycle_id'):
                identifier = value.get(key)
                if isinstance(identifier, (str, int)) and not isinstance(identifier, bool):
                    result.add(str(identifier))
            pending.extend(value.values())
        else:
            pending.extend(value)
    return result


def _new_id(identity, used):
    for _ in range(100):
        value = identity()
        if isinstance(value, str) and value and value not in used:
            used.add(value)
            return value
    raise ImportError('无法生成唯一条目标识，本次未导入。')


def _references(item):
    return image_references({'clip': [item]})


def _fingerprint(item, hashes):
    record = normalize_item(deepcopy(item), 0)
    if record is None:
        return None
    names = _references(record)
    # Absent target image hashes are not proof of equality. Retain the record
    # instead of discarding a potentially different image with the same name.
    if any(not hashes.get(name) for name in names):
        return None
    assets = tuple(sorted(hashes[name] for name in names))
    kind = record['content_type']
    if kind == 'image':
        primary = hashes.get(record.get('image_path'))
        return (kind, primary, assets) if primary else None
    return kind, record['text'], assets


def _rename_images(item, mapping):
    pending, seen = [item], set()
    while pending:
        value = pending.pop()
        if not isinstance(value, (dict, list)) or id(value) in seen:
            continue
        seen.add(id(value))
        if isinstance(value, dict):
            name = value.get('image_path')
            if isinstance(name, str) and name in mapping:
                value['image_path'] = mapping[name]
            pending.extend(value.values())
        else:
            pending.extend(value)


def _image_name(name, identity, occupied):
    suffix = PurePath(name).suffix or '.asset'
    if len(suffix.encode('utf-8')) > 16:
        suffix = '.asset'
    # Identity values are safe as JSON identifiers but need not be file names.
    # Hashing keeps the generated filename portable even for an injected ID.
    for _ in range(100):
        value = identity()
        if not isinstance(value, str) or not value:
            continue
        token = hashlib.sha256(value.encode('utf-8')).hexdigest()[:32]
        candidate = 'import-' + token + suffix
        if candidate.casefold() not in occupied:
            occupied.add(candidate.casefold())
            return candidate
    raise ImportError('无法生成唯一图片名称，本次未导入。')


def _group_name(name, occupied):
    candidate, number = name, 1
    while candidate in occupied:
        candidate = name + ('（导入）' if number == 1 else '（导入 %d）' % number)
        number += 1
    occupied.add(candidate)
    return candidate


def plan_merge(current, source, selected=None, *, current_image_hashes=None, identity=uid):
    """Plan one selected batch without file I/O or mutating either input.

    Rows describe only selected entries. A non-empty ``error`` means data is
    an unchanged copy of the original and must not be committed by the caller.
    """
    live = _current(current)
    entries = _selected(source.entries, selected)
    result = deepcopy(current)
    if not entries:
        return MergePlan(result, (), 0, 0, 0, {})
    target_hashes = dict(current_image_hashes or {})
    fingerprints = {'clip': set(), 'phrase': set()}
    for section, items in (
            ('clip', current['clip']),
            ('phrase', [item for group in current['groups'] for item in group['items']])):
        for item in items:
            fingerprint = _fingerprint(item, target_hashes)
            if fingerprint is not None:
                fingerprints[section].add(fingerprint)
    used, occupied = _identifiers(current), set()
    occupied.update(name.casefold() for name in image_references(current))
    occupied.update(str(name).casefold() for name in target_hashes)
    sequence = max((item.get('seq', 0) for item in live
                    if type(item.get('seq', 0)) is int and item.get('seq', 0) >= 0), default=0)
    triggers = set()
    for group in current['groups']:
        for item in group['items']:
            trigger = item.get('trigger')
            if isinstance(trigger, str) and trigger.strip():
                triggers.add(trigger.strip())
    names = {group['name'] for group in result['groups']}
    groups, additions, rows, mapping = {}, [], [], {}
    duplicate_count = disabled_count = imported_count = 0
    blocked = False
    for entry in entries:
        if entry.section not in fingerprints:
            raise ImportError('导入条目分区无效。')
        if entry.section == 'phrase' and (
                not isinstance(entry.group_key, str) or not entry.group_key
                or not isinstance(entry.group_name, str)):
            raise ImportError('导入常用语分组无效。')
        if entry.issue:
            rows.append(MergeRow(entry.key, 'blocked', entry.issue))
            blocked = True
            continue
        item = normalize_item(deepcopy(entry.item), len(live) + imported_count + 1)
        if item is None:
            rows.append(MergeRow(entry.key, 'blocked', '条目内容无效'))
            blocked = True
            continue
        # Reveal is an explicit choice in the current library, never a choice
        # delegated to an imported file. Re-scan even non-empty supplied labels:
        # an unrecognized label must not suppress the normal privacy boundary.
        item.pop('mask_off', None)
        item['sens'] = list(dict.fromkeys((item.get('sens') or []) + scan_sensitive(item['text']))) or None
        refs = _references(item)
        if any(not source.image_hashes.get(name) for name in refs):
            rows.append(MergeRow(entry.key, 'blocked', '缺少图片内容，请使用完整备份包'))
            blocked = True
            continue
        fingerprint = _fingerprint(item, source.image_hashes)
        if fingerprint is not None and fingerprint in fingerprints[entry.section]:
            rows.append(MergeRow(entry.key, 'duplicate', '相同内容，跳过'))
            duplicate_count += 1
            continue
        if entry.section == 'phrase' and item.get('trigger') is not None and not isinstance(item['trigger'], str):
            rows.append(MergeRow(entry.key, 'blocked', '触发词格式无效'))
            blocked = True
            continue
        if fingerprint is not None:
            fingerprints[entry.section].add(fingerprint)
        item['id'] = _new_id(identity, used)
        sequence += 1
        item['seq'] = sequence
        for name in sorted(refs):
            if name not in mapping:
                mapping[name] = _image_name(name, identity, occupied)
        _rename_images(item, mapping)
        status, message = 'ready', '可以加入'
        if entry.section == 'clip':
            additions.append(item)
        else:
            trigger = (item.get('trigger') or '').strip()
            if trigger and trigger in triggers:
                item.setdefault('import_disabled_trigger', item['trigger'])
                item['trigger'] = ''
                status, message = 'trigger_disabled', '触发词已占用，导入后先停用'
                disabled_count += 1
            elif trigger:
                item['trigger'] = trigger
                triggers.add(trigger)
            if entry.group_key not in groups:
                group = dict(name=_group_name(entry.group_name, names), items=[],
                             recycle_id=_new_id(identity, used))
                groups[entry.group_key] = group
                result['groups'].append(group)
            groups[entry.group_key]['items'].append(item)
        imported_count += 1
        rows.append(MergeRow(entry.key, status, message))
    result['clip'] = additions + result['clip']
    error = '所选资料有不可导入的条目，请取消勾选后重试。' if blocked else ''
    if additions:
        limit = current.get('settings', {}).get('max_items', DEFAULT_SETTINGS['max_items'])
        if type(limit) is not int or not 10 <= limit <= 5000:
            error = '当前历史容量设置无效，请检查设置后重试。'
        elif len(crop_items(result['clip'], limit)) != len(result['clip']):
            error = '历史容量不足，请减少选择或先在设置中提高容量；本次未导入。'
    if error:
        return MergePlan(deepcopy(current), tuple(rows), 0, duplicate_count, 0, {}, error)
    return MergePlan(result, tuple(rows), imported_count, duplicate_count, disabled_count, mapping)
