"""Lazy, bounded projection from history records to list-row presentation.

Creating rows never scans the clipboard body. Only a visible consumer requesting
presentation fields pays classification, masking and subtitle costs. Raw text
remains available unchanged for paste/export; presentation fields are read-only.
"""
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass

from clawboard.classify import byte_size, classify, human_size, kind_icon, preview
from clawboard import privacy
from clawboard.tag import TAG_LABELS
from clawboard.timefmt import now_ms, rel_time


_PRESENTATION = frozenset(('disp', 'sub', 'badge', 'kind_auto', 'sens'))
_OUTPUT_FIELDS = ('id', 'text', 'fav', 'pinned', 'disp', 'sub', 'badge', 'kind',
                  'sens', 'kind_auto', 'created_at', 'source_app', 'est', 'app',
                  'image_path', 'image_w', 'image_h')
_OPTIONAL_RAW = frozenset(('created_at', 'image_path', 'image_w', 'image_h'))


def _number(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _strings(value):
    return tuple(v for v in value if isinstance(v, str)) if isinstance(value, (list, tuple)) else ()


def _text(record):
    value = record.get('text')
    return value if isinstance(value, str) else ''


def _source(record):
    value = record.get('source_app')
    return value if isinstance(value, str) and value else 'unknown'


@dataclass
class _CacheEntry:
    signature: tuple
    # Retain the immutable source so Python cannot reuse its id for different
    # content while a matching cache signature remains alive.
    text: str
    fields: dict
    weight: int


class ProjectedRow(Mapping):
    """Read-only mapping compatible with existing vlist/menu `.get()` callers.

    The record remains owned by the main application thread. Direct fields read
    its current value; accessing presentation fields revalidates cached metadata.
    """
    __slots__ = ('_projection', '_record', '_tab', '_settings')

    def __init__(self, projection, record, tab, settings):
        self._projection = projection
        self._record = record
        self._tab = tab
        self._settings = settings

    def __getitem__(self, key):
        if key in _PRESENTATION:
            return self._projection._fields(self)[key]
        if key == 'text':
            return _text(self._record)
        if key == 'kind':
            return self._tab
        if key in ('app', 'source_app'):
            return _source(self._record)
        if key == 'est':
            return self._record.get('is_estimated')
        if key in ('fav', 'pinned'):
            return self._record.get(key, 0)
        if key in _OPTIONAL_RAW:
            return self._record.get(key)
        return self._record[key]

    def __iter__(self):
        yield from _OUTPUT_FIELDS
        yield from (key for key in self._record if key not in _OUTPUT_FIELDS)

    def __len__(self):
        return len(_OUTPUT_FIELDS) + sum(key not in _OUTPUT_FIELDS for key in self._record)


class ViewProjection:
    """Project cheaply, then derive visible rows through an LRU cache.

    Entry count and retained source-character budgets bound the cache. Sources
    are referenced, never copied. `clock` controls the relative-time cache epoch;
    formatting still uses the common timefmt policy.
    """
    def __init__(self, max_entries=256, preview_chars=2048, *, clock=now_ms,
                 max_cache_chars=2_000_000):
        self.max_entries = max(0, _number(max_entries))
        self.preview_chars = max(1, min(2048, _number(preview_chars, 2048)))
        self.max_cache_chars = max(0, _number(max_cache_chars))
        self.clock = clock
        self._cache = OrderedDict()
        self._cache_chars = 0

    @property
    def cache_size(self):
        return len(self._cache)

    @property
    def cache_chars(self):
        return self._cache_chars

    def clear(self):
        self._cache.clear()
        self._cache_chars = 0

    def project(self, items, tab, settings):
        """Return proxies without classifying, masking or scanning any body."""
        return [ProjectedRow(self, item, tab, settings) for item in items]

    def _signature(self, row):
        record = row._record
        text = _text(record)
        name = record.get('name')
        name = name if isinstance(name, str) else ''
        show_time = bool(row._settings.get('show_time', False))
        signature = (
            id(text), name, _strings(record.get('sens')), _strings(record.get('tags')),
            record.get('kind_auto'), record.get('content_type'), _source(record),
            _number(record.get('content_size')), _number(record.get('created_at')),
            bool(record.get('is_estimated')), _number(record.get('copy_count'), 1),
            bool(record.get('fav')), bool(record.get('pinned')), bool(record.get('mask_off')),
            record.get('image_w'), record.get('image_h'),
            bool(row._settings.get('mask_sensitive', True)), show_time,
            _number(self.clock()) // 60_000 if show_time else None,
        )
        return signature, text

    def _fields(self, row):
        record = row._record
        # Including identity separates malformed records with duplicate IDs.
        key = (row._tab, id(record))
        signature, text = self._signature(row)
        cached = self._cache.get(key)
        if cached is not None and cached.signature == signature and cached.text is text:
            self._cache.move_to_end(key)
            return cached.fields
        if cached is not None:
            self._cache_chars -= cached.weight
            del self._cache[key]
        fields = self._derive(row, text)
        weight = len(text) + sum(len(value) for value in fields.values() if isinstance(value, str))
        if self.max_entries and weight <= self.max_cache_chars:
            self._cache[key] = _CacheEntry(signature, text, fields, weight)
            self._cache_chars += weight
            while len(self._cache) > self.max_entries or self._cache_chars > self.max_cache_chars:
                _, old = self._cache.popitem(last=False)
                self._cache_chars -= old.weight
        return fields

    def _derive(self, row, text):
        record = row._record
        settings = row._settings
        is_image = record.get('content_type') == 'image'
        masked = bool(settings.get('mask_sensitive', True))
        reveal = bool(record.get('mask_off'))
        hits = list(_strings(record.get('sens')))
        if not hits and masked and not reveal and not is_image:
            hits = privacy.scan_sensitive(text)
        # Mask before clipping: a cut through a password/token must not prevent
        # its regex from matching and expose an unmasked partial secret.
        display = ('图片 %s×%s' % (record.get('image_w'), record.get('image_h'))
                   if is_image else privacy.display_text(text, hits, masked=masked, reveal=reveal))
        prefix = ('📌 ' if record.get('pinned') else '') + ('★ ' if record.get('fav') else '')
        display = prefix + display[:max(0, self.preview_chars - len(prefix))]
        kind = record.get('kind_auto')
        if is_image:
            kind = 'image'
        elif not isinstance(kind, str) or not kind:
            # Existing content_type distinguishes JSON even if a preview prefix
            # is no longer a complete JSON document. Other legacy rows classify
            # only a bounded prefix; no path scans are done while projecting.
            content_type = record.get('content_type')
            kind = (content_type if content_type in ('json', 'url')
                    else classify(text[:self.preview_chars], check_paths=False)[0])
        if row._tab == 'phrase':
            name = record.get('name')
            if isinstance(name, str) and name:
                subtitle = privacy.display_text(name, masked=masked, reveal=reveal)[:self.preview_chars]
            else:
                subtitle = preview(privacy.display_text(text, hits, masked=masked, reveal=reveal)
                                   [:self.preview_chars], 28)
            badge = human_size(byte_size(text))
        elif is_image:
            subtitle = '%s · 图片' % _source(record)
            badge = '%s×%s' % (record.get('image_w'), record.get('image_h'))
        else:
            parts = []
            if settings.get('show_time', False):
                parts.append(rel_time(_number(record.get('created_at')), record.get('is_estimated')))
            parts.append(_source(record))
            newline_count = text.count('\n')
            if newline_count:
                parts.append('+%d 行' % newline_count)
            copies = _number(record.get('copy_count'), 1)
            if copies > 1:
                parts.append('×%d' % copies)
            if hits:
                parts.append('⚠' + '/'.join(hits))
            tags = _strings(record.get('tags'))[:3]
            if tags:
                parts.append('🏷' + '/'.join(TAG_LABELS.get(tag, tag) for tag in tags))
            subtitle = ' · '.join(parts)[:self.preview_chars]
            badge = '%s %s' % (kind_icon(kind), human_size(_number(record.get('content_size'))))
        return {'disp': display, 'sub': subtitle, 'badge': badge, 'kind_auto': kind, 'sens': hits}
