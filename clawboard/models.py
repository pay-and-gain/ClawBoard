# -*- coding: utf-8 -*-
"""JSON 数据契约的纯函数边界；保留未知字段，允许两版程序平滑升级。

归一化沿用旧 validate/norm_item 的原地更新约定，不读写文件、不接触 Tk/Win32。
调用者如需保留输入快照，应先复制容器；存储层只把新读出的 JSON 交给这里。
"""
import time
import uuid

from clawboard.classify import byte_size, detect_content_type
from clawboard.config import DEFAULT_SETTINGS, SCHEMA_VERSION, UI_SCALE_LEVELS


LEGACY_CONTENT_TYPES = {0: 'text', 1: 'url', 2: 'json', 3: 'multiline'}


def default_data():
    """每次返回独立默认值；不会让测试或实例之间共享可变配置。"""
    return {'clip': [], 'groups': [{'name': '默认', 'items': []}], 'gi': 0,
            'geom': None, 'settings': dict(DEFAULT_SETTINGS),
            'schema_version': SCHEMA_VERSION}


def _integer(value, default=0, minimum=None):
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(minimum, number) if minimum is not None else number


def _timestamp(value, default):
    if value is None:
        return default
    number = _integer(value, default, 0)
    if number is None:
        return default
    try:
        time.localtime(number / 1000.0)
    except (OverflowError, OSError, ValueError):
        return default
    return number


def normalize_item(item, seq):
    """补齐有效条目并修复已知坏类型；不可用的条目返回 None。"""
    if not isinstance(item, dict) or not isinstance(item.get('text'), str):
        return None
    estimated = int(time.time() * 1000) - max(0, _integer(seq)) * 1000
    original_created = item.get('created_at')
    created = _timestamp(original_created, 0)
    if not created:
        created = estimated
        item['is_estimated'] = 1
    item['created_at'] = created
    item['seq'] = _integer(item.get('seq'), _integer(seq), 0)
    item['updated_at'] = (None if 'updated_at' in item and item['updated_at'] is None
                          else _timestamp(item.get('updated_at'), created))
    last_used = item.get('last_used_at')
    item['last_used_at'] = _timestamp(last_used, None) if last_used is not None else None
    for key, default, minimum in (('copy_count', 1, 1), ('use_count', 0, 0)):
        item[key] = _integer(item.get(key), default, minimum)
    for key in ('fav', 'pinned', 'is_estimated'):
        item[key] = int(bool(_integer(item.get(key))))
    source = item.get('source_app')
    item['source_app'] = source if isinstance(source, str) and source else 'unknown'
    title = item.get('source_title')
    item['source_title'] = title if isinstance(title, str) else None
    item.setdefault('meta', None)
    sens = item.get('sens')
    item['sens'] = [x for x in sens if isinstance(x, str)] if isinstance(sens, list) else None
    for key in ('tags',):
        if key in item:
            values = item[key]
            item[key] = [x for x in values if isinstance(x, str)] if isinstance(values, list) else []
    if 'name' in item and not isinstance(item['name'], str):
        item['name'] = ''
    content_type = item.get('content_type')
    # C 版把枚举数字写入 JSON；查询层要求字符串，在边界统一后业务无需分支。
    if type(content_type) is int:
        content_type = LEGACY_CONTENT_TYPES.get(content_type)
    if not isinstance(content_type, str) or not content_type.strip():
        content_type = detect_content_type(item['text'])
    item['content_type'] = content_type.lower()
    item['content_size'] = _integer(item.get('content_size'), 0, 0) or byte_size(item['text'])
    if not isinstance(item.get('id'), (str, int)) or isinstance(item.get('id'), bool):
        item['id'] = uuid.uuid4().hex
    else:
        item['id'] = str(item['id'])
        if not item['id']:
            item['id'] = uuid.uuid4().hex
    if not isinstance(item.get('time'), str):
        item['time'] = time.strftime('%m-%d %H:%M', time.localtime(created / 1000.0))
    return item


def normalize_data(data):
    """修复已知契约字段，同时完整保留未来版本的扩展字段。"""
    if not isinstance(data, dict):
        return default_data()
    clips = data.get('clip')
    clips = clips if isinstance(clips, list) else []
    seq = 0
    normalized = []
    for raw in clips:
        seq += 1
        item = normalize_item(raw, seq)
        if item is not None:
            normalized.append(item)
    data['clip'] = normalized
    groups = data.get('groups')
    groups = groups if isinstance(groups, list) else []
    normalized_groups = []
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get('name'), str):
            continue
        items = group.get('items')
        items = items if isinstance(items, list) else []
        normalized_items = []
        for raw in items:
            seq += 1
            item = normalize_item(raw, seq)
            if item is not None:
                normalized_items.append(item)
        group['items'] = normalized_items
        normalized_groups.append(group)
    data['groups'] = normalized_groups or [{'name': '默认', 'items': []}]
    data['gi'] = min(_integer(data.get('gi'), 0, 0), len(data['groups']) - 1)
    supplied = data.get('settings')
    supplied = supplied if isinstance(supplied, dict) else {}
    settings = dict(supplied)
    for key, value in DEFAULT_SETTINGS.items():
        # bool 是 int 的子类，必须按精确类型判断，避免 true 被当作条数。
        if key not in settings or type(settings[key]) is not type(value):
            settings[key] = value
    if settings['theme'] not in ('dark', 'light'):
        settings['theme'] = DEFAULT_SETTINGS['theme']
    settings['max_items'] = min(5000, max(10, settings['max_items']))
    if settings.get('ui_scale') not in UI_SCALE_LEVELS:
        settings['ui_scale'] = DEFAULT_SETTINGS['ui_scale']
    data['settings'] = settings
    if not isinstance(data.get('geom'), str):
        data['geom'] = None
    # 读取未来 schema 时不降级编号，否则下一次保存会伪装成旧格式。
    data['schema_version'] = max(SCHEMA_VERSION, _integer(data.get('schema_version'), 1, 1))
    return data
