"""Read-only workbench records and presentation; no Tk, Win32 or storage writes."""
from dataclasses import dataclass

from clawboard.classify import human_size
from clawboard.privacy import display_text
from clawboard.search import SearchService
from clawboard.timefmt import full_time
from clawboard.viewmodels import ViewProjection


@dataclass(frozen=True)
class WorkbenchEntry:
    record: dict
    kind: str = 'clip'
    group_index: int | None = None

    @property
    def key(self):
        # The tab disambiguates imported/legacy identifiers without altering IDs.
        return self.kind, self.record.get('id')


def collect_entries(data, mode='clip'):
    if mode == 'phrase':
        return [WorkbenchEntry(item, 'phrase', group_index)
                for group_index, group in enumerate(data.get('groups') or [])
                for item in group.get('items') or [] if isinstance(item, dict)]
    return [WorkbenchEntry(item) for item in data.get('clip') or [] if isinstance(item, dict)]


def full_preview(entry, settings):
    record = entry.record
    text = record.get('text')
    return display_text(text if isinstance(text, str) else '', record.get('sens') or None,
                        masked=bool(settings.get('mask_sensitive', True)),
                        reveal=bool(record.get('mask_off')))


def metadata(entry, settings, *, expanded=False):
    """Source/size stay hidden by default; expansion is an explicit user action."""
    record, parts = entry.record, []
    if expanded or settings.get('show_source', False):
        parts.append('来源：' + str(record.get('source_app') or '未知'))
    if expanded or settings.get('show_size', False):
        try:
            size = max(0, int(record.get('content_size') or 0))
        except (ValueError, TypeError, OverflowError):
            size = 0
        parts.append('大小：' + human_size(size))
        if record.get('content_type') == 'image':
            parts.append('图片：%s × %s' % (record.get('image_w') or '—', record.get('image_h') or '—'))
    if expanded or settings.get('show_time', False):
        try:
            when = full_time(int(record.get('created_at') or 0))
        except (ValueError, TypeError, OverflowError, OSError):
            when = '未知'
        parts.append('时间：' + when)
    return '  ·  '.join(parts)


class WorkbenchModel:
    """Reuse the common query/presentation contracts on immutable worker snapshots."""
    TYPES = {'all': '', 'text': 'type:text', 'url': 'type:url',
             'image': 'type:image', 'filelist': 'type:filelist'}

    def __init__(self):
        self.search = SearchService()

    def prepare(self, entries, query, settings, content_type='all', favorites=False, *, cancelled=lambda: False):
        if cancelled():
            return [], []
        suffix = self.TYPES.get(content_type, '')
        effective = ' '.join(part for part in (query.strip(), suffix, 'is:fav' if favorites else '') if part)
        records, condition = self.search.match(effective, [entry.record for entry in entries])
        identities = {id(item) for item in records}
        selected = [entry for entry in entries if id(entry.record) in identities]
        projection = ViewProjection()
        prepared = []
        for entry in selected:
            if cancelled():
                return [], []
            row = projection.project([entry.record], entry.kind, settings)[0]
            body = row['disp'].replace('\r', ' ').replace('\n', '  ')
            label = body[:110] or '（空内容）'
            if entry.kind == 'phrase' and row['sub']:
                label = row['sub'][:36] + '  —  ' + label
            if settings.get('show_source', False) and entry.kind != 'phrase':
                label += '  ·  ' + row['source_app']
            if row['badge']:
                label += '  ·  ' + row['badge']
            prepared.append((entry, label))
        return prepared, condition.get('errors') or []
