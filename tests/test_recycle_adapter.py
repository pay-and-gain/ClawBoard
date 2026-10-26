"""Deletion entry wiring without an App, a Tk root, clipboard or disk writes."""
from copy import deepcopy
import os
from types import SimpleNamespace
import unittest

if os.name != 'nt':
    raise unittest.SkipTest('Tk shell adapters import native Windows integration')

from clawboard.app_interact import InteractionMixin
from clawboard.app_ui import UiMixin
from clawboard.history import HistoryService
from clawboard.models import default_data, normalize_item
from clawboard.recycle_adapter import RecycleMixin
from clawboard.trash import TrashService, TrashError


class Harness(RecycleMixin):
    del_item = InteractionMixin.del_item
    clear_list = InteractionMixin.clear_list
    del_group = UiMixin.del_group

    def __init__(self):
        self.data = default_data()
        self.st = self.data['settings']
        self.tab = 'clip'
        self.sel_clip = self.sel_phrase = None
        self.messages, self.confirmed, self.queued = [], [], []
        self.saved = self.rendered = self.trigger_refreshes = 0
        self._trigger_engine = object()
        self.application = SimpleNamespace(store=SimpleNamespace(recovery_required=False),
            history=HistoryService(self.data), trash=TrashService(self.data))

    def cur_group(self):
        return self.data['groups'][self.data['gi']]

    def _purge_image_files(self, records):
        self.queued.extend(records)

    def save(self, later=False):
        self.saved += 1

    def render(self):
        self.rendered += 1

    def _refresh_triggers(self):
        self.trigger_refreshes += 1

    def tip(self, text):
        self.messages.append(text)

    def confirm(self, text, callback):
        self.confirmed.append(text)
        callback()


class RecycleAdapterTests(unittest.TestCase):
    def setUp(self):
        self.host = Harness()

    def test_single_delete_and_restore_preserve_metadata_and_refresh_once(self):
        h = self.host
        original = normalize_item(dict(id='one', text='synthetic', seq=700,
            created_at=1700000000000, future={'kept': True}), 700)
        h.data['clip'] = [deepcopy(original)]
        h.sel_clip = 'one'
        h.del_item('one', 'clip')
        self.assertFalse(h.data['clip'])
        self.assertIsNone(h.sel_clip)
        self.assertFalse(h.queued, 'soft delete must not schedule image removal')
        restored = h.recycle_restore([h.application.trash.entries()[0]['id']])
        self.assertEqual(restored, [original])
        self.assertEqual(h.application.history.sequence, 700)
        self.assertEqual(h.trigger_refreshes, 2)
        self.assertEqual(h.saved, 2)

    def test_clear_history_preserves_favorites_and_recycles_the_rest(self):
        h = self.host
        h.st['keep_on_clear'] = True
        h.data['clip'] = [dict(id='fav', text='kept', fav=1), dict(id='gone', text='trash')]
        h.clear_list()
        self.assertEqual([item['id'] for item in h.data['clip']], ['fav'])
        self.assertEqual(h.application.trash.entries()[0]['item']['id'], 'gone')
        self.assertIn('30天', h.confirmed[0])
        self.assertNotIn('不可撤销', h.confirmed[0])

    def test_phrase_clear_recycles_images_and_refreshes_triggers(self):
        h = self.host
        h.tab = 'phrase'
        group = h.cur_group()
        group['items'] = [dict(id='phrase', text='[image]', image_path='synthetic.png',
                               content_type='image', trigger='cb_phrase')]
        h.clear_list()
        self.assertFalse(group['items'])
        self.assertFalse(h.queued)
        self.assertEqual(h.trigger_refreshes, 1)
        restored = h.recycle_restore([h.application.trash.entries()[0]['id']])
        self.assertEqual(restored[0]['image_path'], 'synthetic.png')
        self.assertEqual(len(group['items']), 1)

    def test_delete_group_uses_confirmed_group_even_when_selection_changes(self):
        h = self.host
        h.data['groups'] = [dict(name='first', items=[dict(id='x', text='first')]),
                            dict(name='second', items=[dict(id='y', text='second')])]
        original = h.data['groups'][0]
        def confirm(text, callback):
            h.data['gi'] = 1
            callback()
        h.confirm = confirm
        h.del_group()
        self.assertEqual([g['name'] for g in h.data['groups']], ['second'])
        entry = h.application.trash.entries()[0]
        self.assertEqual(entry['group']['name'], original['name'])
        h.recycle_restore([entry['id']])
        self.assertEqual([g['name'] for g in h.data['groups']], ['second', 'first'])

    def test_permanent_purge_queues_images_and_saves(self):
        h = self.host
        h.data['clip'] = [dict(id='img', text='image', content_type='image', image_path='one.png')]
        entry = h.application.trash.move(['img'])[0]
        removed = h.recycle_purge([entry['id']])
        self.assertEqual(removed[0]['image_path'], 'one.png')
        self.assertEqual(h.queued, removed)
        self.assertEqual(h.saved, 1)

    def test_readonly_and_invalid_trash_leave_source_and_selection_intact(self):
        h = self.host
        h.data['clip'] = [dict(id='x', text='protected')]
        h.sel_clip = 'x'
        h.application.store.recovery_required = True
        h.del_item('x', 'clip')
        self.assertEqual(h.sel_clip, 'x')
        self.assertFalse(h.saved)
        with self.assertRaises(TrashError):
            h.recycle_restore(['unknown'])
        h.application.store.recovery_required = False
        h.data['trash'] = {'version': 999, 'items': []}
        before = deepcopy(h.data)
        h.del_item('x', 'clip')
        self.assertEqual(h.data, before)
        self.assertEqual(h.sel_clip, 'x')
        self.assertFalse(h.saved)


if __name__ == '__main__':
    unittest.main()
