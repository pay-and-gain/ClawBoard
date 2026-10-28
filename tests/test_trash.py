"""Recycle-bin service invariants; synthetic objects only, no desktop or I/O."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clawboard.models import default_data, normalize_data
from clawboard.history import HistoryService
from clawboard.trash import (TrashService, TrashError, TRASH_LIMIT,
                             RETENTION_MS, image_references, trash_items)


def record(identifier, text=None, **extra):
    return dict(id=identifier, text=text or str(identifier), **extra)


class TrashTests(unittest.TestCase):
    def setUp(self):
        self.data = default_data()
        self.now = RETENTION_MS * 2
        self.counter = 0
        def identity():
            self.counter += 1
            return 'new-' + str(self.counter)
        self.trash = TrashService(self.data, clock=lambda: self.now, identity=identity)

    def seed(self, *items):
        self.data['clip'].extend(items)

    def rejected_unchanged(self, method, *args, **kwargs):
        before = deepcopy(self.data)
        with self.assertRaises(TrashError):
            method(*args, **kwargs)
        self.assertEqual(self.data, before)

    def test_read_only_open_and_noop_operations_do_not_create_extension(self):
        before = deepcopy(self.data)
        self.assertEqual(self.trash.entries(), [])
        self.assertEqual(self.trash.move([]), [])
        self.assertEqual(self.trash.restore([]), [])
        self.assertEqual(self.trash.purge(), [])
        self.assertEqual(self.trash.expire(), [])
        self.assertEqual(self.data, before)

    def test_move_preserves_original_item_fields_and_survivor_objects(self):
        one = record('a', created_at=5, seq=90, future={'n': [1, 2]}, fav=1)
        two = record('b')
        self.seed(one, two)
        moved = self.trash.move(['a'])
        self.assertEqual(self.data['clip'], [two])
        self.assertIs(self.data['clip'][0], two)
        self.assertEqual(moved[0]['item'], one)
        self.assertIsNone(moved[0]['group'])
        one['future']['n'].append(3)
        self.assertEqual(self.trash.entries()[0]['item']['future']['n'], [1, 2])
        moved[0]['item']['text'] = 'external mutation'
        self.assertEqual(self.trash.entries()[0]['item']['text'], 'a')

    def test_entries_are_detached_and_wrapper_extensions_survive(self):
        self.seed(record('a'))
        self.trash.move(['a'])
        self.data['trash']['future'] = {'enabled': True}
        self.data['trash']['items'][0]['future'] = {'keep': 1}
        shown = self.trash.entries()
        shown[0]['future']['keep'] = 2
        self.assertEqual(self.trash.entries()[0]['future'], {'keep': 1})
        self.trash.restore([shown[0]['id']])
        self.assertEqual(self.data['trash']['future'], {'enabled': True})

    def test_batch_order_new_deletions_first_and_restore_keeps_source_order(self):
        self.seed(*(record(name) for name in ('a', 'b', 'c')))
        first = self.trash.move(['a', 'b'])
        second = self.trash.move(['c'])
        self.assertEqual([entry['item']['id'] for entry in self.trash.entries()], ['c', 'a', 'b'])
        self.trash.restore([entry['id'] for entry in first])
        self.assertEqual([item['id'] for item in self.data['clip']], ['a', 'b'])
        self.assertEqual(self.trash.entries(), second)

    def test_restore_collision_never_overwrites_live_record(self):
        self.seed(record('same', 'deleted text', seq=900, created_at=3))
        moved = self.trash.move(['same'])
        live = record('same', 'new live text')
        self.seed(live)
        result = self.trash.restore([moved[0]['id']])
        self.assertNotEqual(result[0]['id'], 'same')
        self.assertEqual((result[0]['text'], result[0]['seq'], result[0]['created_at']),
                         ('deleted text', 900, 3))
        self.assertIs(self.data['clip'][1], live)
        self.assertEqual(self.trash.restore([moved[0]['id']]), [])

    def test_phrase_move_assigns_stable_origin_and_restore_uses_id_not_name(self):
        original = self.data['groups'][0]
        original.update(future={'group-setting': 1})
        original['items'] = [record('p', trigger='hello')]
        moved = self.trash.move(['p'], original)
        stable = original['recycle_id']
        self.assertEqual(moved[0]['group']['recycle_id'], stable)
        self.assertNotIn('items', moved[0]['group'])
        original['name'] = 'renamed'
        duplicate_name = dict(name='默认', items=[])
        self.data['groups'].append(duplicate_name)
        self.trash.restore([moved[0]['id']])
        self.assertEqual([item['id'] for item in original['items']], ['p'])
        self.assertEqual(duplicate_name['items'], [])
        self.assertEqual(original['name'], 'renamed')

    def test_deleted_group_is_recreated_with_unknown_metadata(self):
        group = self.data['groups'][0]
        group.update(future={'flag': ['opaque']})
        group['items'] = [record('p1'), record('p2')]
        moved = self.trash.move(['p1', 'p2'], group)
        self.data['groups'] = [dict(name=group['name'], items=[])]
        result = self.trash.restore([entry['id'] for entry in moved])
        self.assertEqual(len(self.data['groups']), 2)
        restored = self.data['groups'][1]
        self.assertEqual(restored['future'], {'flag': ['opaque']})
        self.assertEqual(restored['recycle_id'], group['recycle_id'])
        self.assertEqual(restored['items'], result)

    def test_foreign_equal_group_is_rejected_without_mutating_any_group(self):
        group = self.data['groups'][0]
        group['items'] = [record('p')]
        self.rejected_unchanged(self.trash.move, ['p'], deepcopy(group))

    def test_restore_trigger_collision_rejects_entire_mixed_batch(self):
        self.seed(record('clip'))
        group = self.data['groups'][0]
        group['items'] = [record('phrase', trigger='  key  ')]
        moved_phrase = self.trash.move(['phrase'], group)
        moved_clip = self.trash.move(['clip'])
        group['items'].append(record('new-phrase', trigger='key'))
        self.rejected_unchanged(self.trash.restore,
                               [moved_clip[0]['id'], moved_phrase[0]['id']])

    def test_duplicate_triggers_within_restore_batch_are_rejected(self):
        group = self.data['groups'][0]
        group['items'] = [record('p1', trigger='key'), record('p2', trigger='key')]
        moved = self.trash.move(['p1', 'p2'], group)
        self.rejected_unchanged(self.trash.restore, [entry['id'] for entry in moved])

    def test_trigger_comparison_matches_case_sensitive_live_engine(self):
        group = self.data['groups'][0]
        group['items'] = [record('p1', trigger='Key'), record('p2', trigger='key')]
        moved = self.trash.move(['p1'], group)
        self.trash.restore([moved[0]['id']])
        self.assertEqual(len(group['items']), 2)

    def test_capacity_rejects_source_deletion_and_new_group_id_atomically(self):
        self.seed(*(record('c-' + str(i)) for i in range(TRASH_LIMIT)))
        self.trash.move([item['id'] for item in self.data['clip']])
        group = self.data['groups'][0]
        group['items'] = [record('phrase')]
        self.rejected_unchanged(self.trash.move, ['phrase'], group)
        self.assertNotIn('recycle_id', group)

    def test_expiry_includes_exact_thirty_day_boundary_and_keeps_future(self):
        self.seed(record('old', image_path='old.png'), record('young'), record('future'))
        moved = self.trash.move(['old', 'young', 'future'])
        entries = self.data['trash']['items']
        entries[0]['deleted_at'] = self.now - RETENTION_MS
        entries[1]['deleted_at'] = self.now - RETENTION_MS + 1
        entries[2]['deleted_at'] = self.now + 100
        removed = self.trash.expire()
        self.assertEqual([item['id'] for item in removed], ['old'])
        self.assertEqual([entry['id'] for entry in self.trash.entries()],
                         [moved[1]['id'], moved[2]['id']])

    def test_purge_selected_and_all_return_items_without_touching_live(self):
        self.seed(record('a', image_path='a.png'), record('b'))
        moved = self.trash.move(['a', 'b'])
        self.seed(record('live'))
        self.assertEqual([item['id'] for item in self.trash.purge([moved[0]['id']])], ['a'])
        self.assertEqual([item['id'] for item in self.trash.purge()], ['b'])
        self.assertEqual([item['id'] for item in self.data['clip']], ['live'])

    def test_invalid_or_future_container_is_preserved_for_every_operation(self):
        for invalid in (None, [], {}, dict(version=2, items=[]),
                        dict(version=True, items=[]), dict(version=1, items='bad')):
            self.data['trash'] = deepcopy(invalid)
            self.seed(record('a'))
            for method, args in ((self.trash.entries, ()), (self.trash.move, (['a'],)),
                                 (self.trash.restore, (['a'],)), (self.trash.purge, ()),
                                 (self.trash.expire, ())):
                self.rejected_unchanged(method, *args)
            self.data['clip'] = []

    def test_malformed_wrapper_and_duplicate_wrapper_ids_are_preserved(self):
        valid = dict(id='w', deleted_at=1, item=record('i'), group=None)
        cases = [dict(valid, deleted_at=True), dict(valid, deleted_at=-1),
                 dict(valid, item={'id': 'i'}), dict(valid, group={'name': 'x'}),
                 dict(valid, group={'name': 'x', 'recycle_id': 'g', 'items': []})]
        for wrapper in cases:
            self.data['trash'] = dict(version=1, items=[wrapper])
            self.rejected_unchanged(self.trash.entries)
        self.data['trash'] = dict(version=1, items=[valid, deepcopy(valid)])
        self.rejected_unchanged(self.trash.purge)

    def test_duplicate_live_group_ids_fail_before_restore(self):
        self.seed(record('a'))
        moved = self.trash.move(['a'])
        self.data['groups'] = [dict(name='x', recycle_id='same', items=[]),
                               dict(name='y', recycle_id='same', items=[])]
        self.rejected_unchanged(self.trash.restore, [moved[0]['id']])

    def test_bad_identity_or_clock_does_not_mutate_original_data(self):
        self.seed(record('a'))
        broken = TrashService(self.data, clock=lambda: -1, identity=lambda: 'new')
        self.rejected_unchanged(broken.move, ['a'])
        broken = TrashService(self.data, clock=lambda: self.now, identity=lambda: 'a')
        self.rejected_unchanged(broken.move, ['a'])

    def test_invalid_selection_does_not_create_trash(self):
        self.seed(record('a'))
        for invalid in ('a', None, [True], [None], ['']):
            self.rejected_unchanged(self.trash.move, invalid)

    def test_unknown_extension_survives_existing_model_normalization(self):
        self.seed(record('a', created_at=1234))
        self.trash.move(['a'])
        expected = deepcopy(self.data['trash'])
        normalized = normalize_data(deepcopy(self.data))
        self.assertEqual(normalized['schema_version'], 3)
        self.assertEqual(normalized['trash'], expected)

    def test_restoring_bad_known_fields_normalizes_before_item_becomes_live(self):
        bad = record('bad', 'synthetic copied URL', seq='bad',
                     created_at='bad', updated_at='bad', copy_count='bad',
                     use_count='bad', content_type=1, content_size='bad',
                     source_app=123, future={'keep': ['opaque']})
        self.data['trash'] = dict(version=1, items=[dict(id='wrapper', deleted_at=1,
                                                       item=deepcopy(bad), group=None)])
        restored = self.trash.restore(['wrapper'])[0]
        self.assertIsInstance(restored['seq'], int)
        self.assertIsInstance(restored['created_at'], int)
        self.assertGreater(restored['created_at'], 0)
        self.assertIsInstance(restored['updated_at'], int)
        self.assertEqual(restored['content_type'], 'url')
        self.assertEqual((restored['copy_count'], restored['use_count']), (1, 0))
        self.assertEqual(restored['source_app'], 'unknown')
        self.assertEqual(restored['future'], bad['future'])
        self.assertEqual(HistoryService(self.data).sequence, restored['seq'])

    def test_restoring_valid_normalized_fields_preserves_complete_record(self):
        self.seed(record('valid', 'synthetic 中文', seq=900, created_at=1234,
                         updated_at=None, last_used_at=5678, copy_count=3,
                         content_type='text', future={'precise': 9007199254740993}))
        normalized = normalize_data(deepcopy(self.data))['clip'][0]
        self.data['clip'] = [deepcopy(normalized)]
        moved = self.trash.move(['valid'])
        restored = self.trash.restore([moved[0]['id']])[0]
        self.assertEqual(restored, normalized)

    def test_normalized_copies_do_not_mutate_trash_when_later_trigger_conflicts(self):
        group = self.data['groups'][0]
        group['items'] = [record('p', trigger='conflict')]
        self.data['trash'] = dict(version=1, items=[
            dict(id='bad', deleted_at=1, item=record('bad', seq='bad'), group=None),
            dict(id='phrase', deleted_at=1, item=record('p2', trigger='conflict'),
                 group=dict(name='deleted', recycle_id='deleted'))])
        self.rejected_unchanged(self.trash.restore, ['bad', 'phrase'])

    def test_image_helpers_protect_opaque_future_data_without_mutating_it(self):
        self.seed(record('a', image_path='live.png'))
        self.data['groups'][0]['items'] = [record('p', image_path='phrase.png')]
        self.data['trash'] = dict(version=999, items=[dict(item=record('t', image_path='trash.png'))],
                                 future={'nested': [{'image_path': 'future.png'}]})
        before = deepcopy(self.data)
        self.assertEqual(image_references(self.data),
                         {'live.png', 'phrase.png', 'trash.png', 'future.png'})
        self.assertEqual([item['id'] for item in trash_items(self.data)], ['t'])
        self.assertEqual(self.data, before)


if __name__ == '__main__':
    unittest.main()
