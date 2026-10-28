"""Owner-thread recycle bin; optional shared-JSON extension, no file I/O.

Manual deletions are reversible for thirty days. Capacity rejects a deletion
instead of evicting an unexpired record, so callers can promise a real window.
"""
from copy import deepcopy

from clawboard.models import normalize_item
from clawboard.runtime import uid
from clawboard.timefmt import now_ms

TRASH_VERSION = 1
TRASH_LIMIT = 5000
RETENTION_DAYS = 30
RETENTION_MS = RETENTION_DAYS * 24 * 60 * 60 * 1000


class TrashError(ValueError):
    """The operation was rejected before changing any user records."""


def trash_items(data):
    """Read recognized payloads without mutating even an unknown container."""
    container = data.get('trash') if isinstance(data, dict) else None
    wrappers = container.get('items') if isinstance(container, dict) else container
    if not isinstance(wrappers, list):
        return ()
    return tuple(wrapper['item'] for wrapper in wrappers
                 if isinstance(wrapper, dict) and isinstance(wrapper.get('item'), dict))


def image_references(data):
    """Conservatively protect images, including opaque/future trash metadata.

    Refusing edits of an unknown trash version must not let ordinary saves
    delete its assets. This helper consequently does not require version 1.
    """
    if not isinstance(data, dict):
        return set()
    pending = [data.get('clip'), data.get('groups'), data.get('trash')]
    names, seen = set(), set()
    while pending:
        value = pending.pop()
        if not isinstance(value, (dict, list)) or id(value) in seen:
            continue
        seen.add(id(value))
        if isinstance(value, dict):
            name = value.get('image_path')
            if isinstance(name, str) and name:
                names.add(name)
            pending.extend(value.values())
        else:
            pending.extend(value)
    return names


def _item(value):
    if (not isinstance(value, dict) or not isinstance(value.get('text'), str)
            or not isinstance(value.get('id'), (str, int))
            or isinstance(value.get('id'), bool) or not str(value['id'])):
        raise TrashError('条目结构无效，原数据已保留。')
    return value


def _ids(values):
    if isinstance(values, (str, bytes)) or values is None:
        raise TrashError('请选择要处理的条目。')
    try:
        result = set()
        for value in values:
            if (not isinstance(value, (str, int)) or isinstance(value, bool)
                    or not str(value)):
                raise TrashError('条目标识无效。')
            result.add(str(value))
        return result
    except TypeError as error:
        raise TrashError('条目标识无效。') from error


class TrashService:
    def __init__(self, data, *, clock=now_ms, identity=uid):
        if not isinstance(data, dict):
            raise TrashError('资料库结构无效。')
        self.data, self.clock, self.identity = data, clock, identity

    def _container(self):
        if 'trash' not in self.data:
            return None, []
        container = self.data['trash']
        if (not isinstance(container, dict) or type(container.get('version')) is not int
                or container['version'] != TRASH_VERSION
                or not isinstance(container.get('items'), list)):
            raise TrashError('回收站格式无法识别，原数据已保留，请先完整备份。')
        known = set()
        for wrapper in container['items']:
            if (not isinstance(wrapper, dict) or not isinstance(wrapper.get('id'), str)
                    or not wrapper['id'] or wrapper['id'] in known
                    or type(wrapper.get('deleted_at')) is not int
                    or wrapper['deleted_at'] < 0 or 'group' not in wrapper):
                raise TrashError('回收站条目结构无效，原数据已保留。')
            known.add(wrapper['id'])
            _item(wrapper.get('item'))
            group = wrapper['group']
            if group is not None and (
                    not isinstance(group, dict) or not isinstance(group.get('name'), str)
                    or not isinstance(group.get('recycle_id'), str)
                    or not group['recycle_id'] or 'items' in group):
                raise TrashError('回收站分组信息无效，原数据已保留。')
        return container, container['items']

    def _live(self):
        clips, groups = self.data.get('clip'), self.data.get('groups')
        if not isinstance(clips, list) or not isinstance(groups, list):
            raise TrashError('历史或常用语结构无效，原数据已保留。')
        for item in clips:
            _item(item)
        stable = set()
        for group in groups:
            if (not isinstance(group, dict) or not isinstance(group.get('name'), str)
                    or not isinstance(group.get('items'), list)):
                raise TrashError('常用语分组结构无效，原数据已保留。')
            for item in group['items']:
                _item(item)
            if 'recycle_id' in group:
                value = group['recycle_id']
                if not isinstance(value, str) or not value or value in stable:
                    raise TrashError('常用语分组标识冲突，原数据已保留。')
                stable.add(value)
        return clips, groups

    def _new_id(self, used):
        # A faulty injected identity source must fail, not loop forever or
        # overwrite a live record. The default source is process-unique.
        for attempt in range(100):
            value = self.identity()
            if isinstance(value, str) and value and value not in used:
                used.add(value)
                return value
        raise TrashError('无法生成唯一标识，原数据已保留。')

    def _stamp(self):
        value = self.clock()
        if type(value) is not int or value < 0:
            raise TrashError('系统时间无效，原数据已保留。')
        return value

    def entries(self):
        return deepcopy(self._container()[1])

    def move(self, ids, group=None):
        container, entries = self._container()
        selected = _ids(ids)
        clips, groups = self._live()
        if group is not None and not any(value is group for value in groups):
            raise TrashError('原常用语分组已改变，请刷新后重试。')
        source = clips if group is None else group['items']
        victims = [item for item in source if str(item['id']) in selected]
        if not victims:
            return []
        if len(entries) + len(victims) > TRASH_LIMIT:
            raise TrashError('回收站已达5000条上限，请先恢复或永久删除部分记录；本次未删除。')
        remaining = [item for item in source if str(item['id']) not in selected]
        used = {entry['id'] for entry in entries}
        used.update(str(item['id']) for item in clips)
        used.update(str(item['id']) for value in groups for item in value['items'])
        used.update(value['recycle_id'] for value in groups if 'recycle_id' in value)
        used.update(entry['group']['recycle_id'] for entry in entries if entry['group'])
        metadata = None
        if group is not None:
            metadata = deepcopy({key: value for key, value in group.items() if key != 'items'})
            if 'recycle_id' not in metadata:
                metadata['recycle_id'] = self._new_id(used)
        stamp = self._stamp()
        additions = [dict(id=self._new_id(used), deleted_at=stamp,
                          item=deepcopy(item), group=deepcopy(metadata)) for item in victims]
        replacement = additions + entries
        result = deepcopy(additions)
        # All checks and allocations above finish before the first mutation.
        if container is None:
            container = dict(version=TRASH_VERSION, items=replacement)
        if group is None:
            self.data['clip'] = remaining
        else:
            group['recycle_id'] = metadata['recycle_id']
            group['items'] = remaining
        container['items'] = replacement
        self.data['trash'] = container
        return result

    def restore(self, ids):
        container, entries = self._container()
        selected = _ids(ids)
        chosen = [entry for entry in entries if entry['id'] in selected]
        if not chosen:
            return []
        clips, groups = self._live()
        used = {str(item['id']) for item in clips}
        used.update(str(item['id']) for group in groups for item in group['items'])
        by_group = {group['recycle_id']: group for group in groups if 'recycle_id' in group}
        triggers = set()
        for group in groups:
            for item in group['items']:
                value = item.get('trigger')
                if isinstance(value, str) and value.strip():
                    triggers.add(value.strip())
        new_groups, additions, restored, clip_additions = [], {}, [], []
        # The optional trash extension stays opaque during ordinary model
        # loads. Cross its item boundary here, before moving anything live.
        # A bounded count fallback mirrors normalize_data without trusting a
        # corrupt historical seq when estimating a missing creation time.
        fallback = min(len(clips) + sum(len(group['items']) for group in groups), 1000000)
        for index, entry in enumerate(chosen, 1):
            item = normalize_item(deepcopy(entry['item']), fallback + index)
            if item is None:
                raise TrashError('待恢复条目结构无效，本批未恢复。')
            if str(item['id']) in used:
                item['id'] = self._new_id(used)
            else:
                used.add(str(item['id']))
            origin = entry['group']
            if origin is None:
                clip_additions.append(item)
            else:
                trigger = item.get('trigger')
                if trigger is not None and not isinstance(trigger, str):
                    raise TrashError('待恢复常用语的触发词无效，本批未恢复。')
                key = (trigger or '').strip()
                if key and key in triggers:
                    raise TrashError('待恢复常用语的触发词已被使用，本批未恢复。')
                if key:
                    triggers.add(key)
                stable = origin['recycle_id']
                target = by_group.get(stable)
                if target is None:
                    target = deepcopy(origin)
                    target['items'] = []
                    by_group[stable] = target
                    new_groups.append(target)
                additions.setdefault(stable, []).append(item)
            restored.append(item)
        replacement_clips = clip_additions + clips
        replacement_groups = groups + new_groups
        group_updates = [(by_group[key], values + by_group[key]['items'])
                         for key, values in additions.items()]
        remaining = [entry for entry in entries if entry['id'] not in selected]
        # Group reconstruction and duplicate-trigger checks are batch-atomic.
        for group, values in group_updates:
            group['items'] = values
        self.data['clip'] = replacement_clips
        self.data['groups'] = replacement_groups
        container['items'] = remaining
        return restored

    def purge(self, ids=None):
        container, entries = self._container()
        selected = None if ids is None else _ids(ids)
        removed = [entry for entry in entries if selected is None or entry['id'] in selected]
        if not removed:
            return []
        remaining = [entry for entry in entries if selected is not None and entry['id'] not in selected]
        result = [deepcopy(entry['item']) for entry in removed]
        container['items'] = remaining
        return result

    def expire(self):
        entries = self._container()[1]
        if not entries:
            return []
        cutoff = self._stamp() - RETENTION_MS
        return self.purge([entry['id'] for entry in entries if entry['deleted_at'] <= cutoff])
