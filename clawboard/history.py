"""In-memory history operations; no UI, operating-system access or persistence.

Expensive derived metadata can be prepared in a worker. Only the owner thread
commits a prepared value to the mutable history and decides when to persist it.
"""
from dataclasses import dataclass
from typing import Callable

from clawboard.classify import byte_size, classify, crop_items, detect_content_type
from clawboard.privacy import scan_sensitive
from clawboard.tag import detect_tags
from clawboard.runtime import uid
from clawboard.timefmt import now_ms


@dataclass(frozen=True)
class PreparedText:
    text: str
    hits: tuple
    content_type: str
    kind: str
    size: int
    tags: tuple
    line_count: int


@dataclass(frozen=True)
class HistoryChange:
    item: dict
    created: bool
    removed: tuple = ()


def prepare_text(text, hits=None):
    """Compute metadata once, before a UI-thread commit."""
    return PreparedText(text, tuple(scan_sensitive(text) if hits is None else hits),
                        detect_content_type(text), classify(text)[0], byte_size(text),
                        tuple(detect_tags(text)), text.count('\n'))


class HistoryService:
    def __init__(self, data, *, clock: Callable = now_ms, identity: Callable = uid):
        self.data = data
        self.clock = clock
        self.identity = identity
        self.sequence = max((int(x.get('seq') or 0) for x in data['clip']), default=0)

    def next_sequence(self):
        self.sequence += 1
        return self.sequence

    def ingest(self, prepared, *, source_app='unknown', source_title=None, limit=500):
        items = self.data['clip']
        stamp = self.clock()
        duplicate = next((it for it in items if it.get('content_type') != 'image'
                          and it.get('text') == prepared.text), None)
        created = duplicate is None
        if created:
            stamp = max(stamp, max((int(x.get('created_at') or 0) for x in items), default=0))
            record = {'id': self.identity(), 'text': prepared.text, 'created_at': stamp,
                      'seq': self.next_sequence(), 'copy_count': 1, 'fav': 0,
                      'is_estimated': 0, 'source_app': source_app}
        else:
            record = duplicate
            record['copy_count'] = int(record.get('copy_count') or 1) + 1
            items.remove(record)
        record.update(updated_at=stamp, content_type=prepared.content_type,
                      content_size=prepared.size, kind_auto=prepared.kind)
        if source_app != 'unknown':
            record['source_app'] = source_app
        if source_title:
            record['source_title'] = source_title
        if prepared.hits:
            record['sens'] = list(prepared.hits)
        else:
            record.pop('sens', None)
        if prepared.tags:
            record['tags'] = list(prepared.tags)
        else:
            record.pop('tags', None)
        items.insert(0, record)
        retained = crop_items(items, limit)
        kept_ids = {item['id'] for item in retained}
        removed = tuple(it for it in items if it['id'] not in kept_ids)
        self.data['clip'] = retained
        return HistoryChange(record, created, removed)

    def replace_text(self, item, text):
        """Editing invalidates every derived field, including sensitive masks."""
        prepared = prepare_text(text)
        item.update(text=text, updated_at=self.clock(), content_type=prepared.content_type,
                    content_size=prepared.size, kind_auto=prepared.kind)
        item.pop('mask_off', None)
        if prepared.hits:
            item['sens'] = list(prepared.hits)
        else:
            item.pop('sens', None)
        if prepared.tags:
            item['tags'] = list(prepared.tags)
        else:
            item.pop('tags', None)
        return item
