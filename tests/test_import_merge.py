"""Additive import invariants on synthetic objects; no App or clipboard."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clawboard.import_merge import plan_merge
from clawboard.import_source import ImportEntry, ImportError, ImportSource
from clawboard.models import default_data
from clawboard.viewmodels import ViewProjection


def item(text, **extra):
    return dict(id='old-source-id', text=text, **extra)


def source(*records, hashes=None):
    entries = []
    for index, value in enumerate(records):
        if isinstance(value, ImportEntry):
            entries.append(value)
        else:
            entries.append(ImportEntry('c:%d' % index, 'clip', '', '', value, ()))
    return ImportSource(Path('/synthetic/source.json'), 'a' * 64, 'json-library',
                        tuple(entries), hashes or {})


def phrase(key, text, group='source-group', name='默认', **extra):
    return ImportEntry(key, 'phrase', group, name, item(text, **extra), ())


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.current = default_data()
        self.counter = 0

    def identity(self):
        self.counter += 1
        return 'generated-' + str(self.counter)

    def plan(self, incoming, selected=None, **options):
        options.setdefault('identity', self.identity)
        return plan_merge(self.current, incoming, selected, **options)

    def test_addition_keeps_existing_data_and_both_inputs_unchanged(self):
        self.current['clip'] = [item('existing', seq=82, custom={'keep': [1]})]
        self.current['future'] = {'keep': ['root']}
        self.current['trash'] = {'version': 99, 'opaque': ['keep']}
        incoming = source(item('new', future={'keep': [2]}))
        before, input_before = deepcopy(self.current), deepcopy(incoming)
        result = self.plan(incoming)
        self.assertFalse(result.error)
        self.assertEqual((result.imported_count, result.duplicate_count), (1, 0))
        self.assertEqual(result.data['clip'][1], before['clip'][0])
        for key in ('settings', 'trash', 'future', 'gi', 'geom'):
            self.assertEqual(result.data[key], before[key])
        self.assertEqual(self.current, before)
        self.assertEqual(incoming, input_before)
        self.assertEqual(result.data['clip'][0]['future'], {'keep': [2]})
        result.data['clip'][1]['custom']['keep'].append('isolated')
        self.assertEqual(self.current, before)

    def test_existing_duplicates_and_source_duplicates_are_skipped(self):
        self.current['clip'] = [item('same', content_type='text')]
        result = self.plan(source(item('same'), item('new'), item('new')))
        self.assertEqual((result.imported_count, result.duplicate_count), (1, 2))
        self.assertEqual([row.status for row in result.rows], ['duplicate', 'ready', 'duplicate'])

    def test_content_type_is_part_of_text_equality(self):
        self.current['clip'] = [item('same', content_type='text')]
        result = self.plan(source(item('same', content_type='filelist')))
        self.assertEqual(result.imported_count, 1)

    def test_legacy_content_types_normalize_for_duplicate_comparison(self):
        self.current['clip'] = [item('same', content_type=0)]
        result = self.plan(source(item('same', content_type='text')))
        self.assertEqual((result.imported_count, result.duplicate_count), (0, 1))

    def test_clip_and_phrase_do_not_deduplicate_each_other(self):
        self.current['clip'] = [item('same')]
        result = self.plan(source(phrase('g:0:0', 'same')))
        self.assertEqual(result.imported_count, 1)
        self.assertEqual(result.data['groups'][-1]['items'][0]['text'], 'same')

    def test_selection_is_explicit_and_source_order_is_stable(self):
        incoming = source(item('first'), item('second'), item('third'))
        result = self.plan(incoming, ['c:2', 'c:0'])
        self.assertEqual([value['text'] for value in result.data['clip']], ['first', 'third'])
        self.assertEqual([row.key for row in result.rows], ['c:0', 'c:2'])

    def test_empty_selection_is_exact_noop(self):
        incoming = source(item('new'))
        result = self.plan(incoming, [])
        self.assertEqual(result.data, self.current)
        self.assertEqual((result.rows, result.imported_count, result.image_map), ((), 0, {}))

    def test_invalid_and_duplicate_selection_rejected_without_mutation(self):
        incoming = source(item('new'))
        before = deepcopy(self.current)
        for selected in ('c:0', ['c:0', 'c:0'], ['missing'], [True], [[]], 42):
            with self.subTest(selected=selected), self.assertRaises(ImportError):
                self.plan(incoming, selected)
            self.assertEqual(self.current, before)

    def test_unknown_or_duplicate_source_keys_rejected(self):
        incoming = source(item('one'))
        for altered in (replace(incoming, entries=incoming.entries * 2),
                        replace(incoming, entries=(replace(incoming.entries[0], key=''),))):
            with self.assertRaises(ImportError):
                self.plan(altered)

    def test_one_blocked_selected_record_rejects_entire_batch(self):
        incoming = source(item('valid'), item('unavailable'))
        incoming = replace(incoming, entries=(incoming.entries[0],
                           replace(incoming.entries[1], issue='缺少图片')))
        result = self.plan(incoming)
        self.assertTrue(result.error)
        self.assertEqual(result.data, self.current)
        self.assertEqual((result.imported_count, result.image_map), (0, {}))
        selected = self.plan(incoming, ['c:0'])
        self.assertEqual(selected.imported_count, 1)

    def test_new_ids_cannot_collide_with_live_trash_or_group_identifiers(self):
        self.current['clip'] = [dict(id='generated-1', text='old')]
        self.current['trash'] = {'version': 1, 'items': [
            {'id': 'generated-2', 'item': dict(id='generated-3', text='old-trash'),
             'group': {'recycle_id': 'generated-4'}}]}
        self.current['groups'][0]['recycle_id'] = 'generated-5'
        result = self.plan(source(item('new')))
        self.assertEqual(result.data['clip'][0]['id'], 'generated-6')
        self.assertNotEqual(result.data['clip'][0]['id'], 'old-source-id')

    def test_faulty_identity_source_fails_instead_of_looping_or_overwriting(self):
        self.current['clip'] = [dict(id='constant', text='old')]
        with self.assertRaises(ImportError):
            self.plan(source(item('new')), identity=lambda: 'constant')
        self.assertEqual(self.current['clip'][0]['text'], 'old')

    def test_source_ids_are_never_reused_even_when_not_yet_live(self):
        result = self.plan(source(item('one'), item('two')))
        ids = [value['id'] for value in result.data['clip']]
        self.assertEqual(len(set(ids)), 2)
        self.assertNotIn('old-source-id', ids)
        self.assertGreater(result.data['clip'][1]['seq'], result.data['clip'][0]['seq'])

    def test_same_named_groups_are_created_separately_with_unique_names(self):
        self.current['groups'][0]['future'] = {'keep': True}
        self.current['groups'].append(dict(name='默认（导入）', items=[]))
        before = deepcopy(self.current['groups'])
        result = self.plan(source(phrase('g:0:0', 'one'),
                                  phrase('g:1:0', 'two', group='other')))
        self.assertEqual(result.data['groups'][:2], before)
        self.assertEqual([group['name'] for group in result.data['groups'][2:]],
                         ['默认（导入 2）', '默认（导入 3）'])
        self.assertNotEqual(result.data['groups'][2]['recycle_id'],
                            result.data['groups'][3]['recycle_id'])

    def test_duplicate_phrase_does_not_create_empty_imported_group(self):
        self.current['groups'][0]['items'] = [item('same')]
        result = self.plan(source(phrase('g:0:0', 'same')))
        self.assertEqual(result.data['groups'], self.current['groups'])
        self.assertEqual(result.duplicate_count, 1)

    def test_trigger_conflicts_are_disabled_and_original_value_is_retained(self):
        self.current['groups'][0]['items'] = [item('old', trigger=' hello ')]
        result = self.plan(source(phrase('g:0:0', 'new one', trigger=' hello '),
                                  phrase('g:0:1', 'new two', trigger='HELLO'),
                                  phrase('g:0:2', 'new three', trigger='HELLO')))
        values = result.data['groups'][-1]['items']
        self.assertEqual(values[0]['trigger'], '')
        self.assertEqual(values[0]['import_disabled_trigger'], ' hello ')
        self.assertEqual(values[1]['trigger'], 'HELLO')
        self.assertEqual(values[2]['trigger'], '')
        self.assertEqual(result.disabled_trigger_count, 2)
        self.assertEqual([row.status for row in result.rows],
                         ['trigger_disabled', 'ready', 'trigger_disabled'])
        self.assertEqual(self.current['groups'][0]['items'][0]['trigger'], ' hello ')

    def test_bad_trigger_type_cannot_reach_trigger_engine(self):
        result = self.plan(source(phrase('g:0:0', 'new', trigger=42)))
        self.assertTrue(result.error)
        self.assertEqual(result.imported_count, 0)

    def test_import_cannot_carry_reveal_or_forged_labels_past_daily_masking(self):
        token = 'sk-synthetic_import_token_123456789'
        raw = 'Synthetic token: ' + token
        self.current['clip'] = [item('existing', mask_off=True, sens=['keep-original'])]
        incoming = source(item(raw, mask_off=True, sens=['无效'], future={'keep': [1]}))
        before = deepcopy(incoming)
        result = self.plan(incoming)
        added = result.data['clip'][0]
        self.assertNotIn('mask_off', added)
        self.assertIn('Token', added['sens'])
        self.assertIn('无效', added['sens'])
        self.assertEqual(added['text'], raw)
        self.assertEqual(added['future'], {'keep': [1]})
        row = ViewProjection().project([added], 'clip', result.data['settings'])[0]
        self.assertNotIn(token, row['disp'])
        self.assertEqual(row['text'], raw)
        self.assertTrue(result.data['clip'][1]['mask_off'])
        self.assertEqual(result.data['clip'][1]['sens'], ['keep-original'])
        self.assertEqual(incoming, before)

    def test_imported_phone_is_masked_in_phrase_display_and_subtitle(self):
        phone = '13912345678'
        incoming = source(phrase('g:0:0', 'Synthetic phone: ' + phone,
                                  mask_off=True, sens=['邮箱']))
        result = self.plan(incoming)
        added = result.data['groups'][-1]['items'][0]
        self.assertNotIn('mask_off', added)
        self.assertEqual(added['sens'], ['邮箱', '手机号'])
        row = ViewProjection().project([added], 'phrase', {'mask_sensitive': True})[0]
        self.assertNotIn(phone, row['disp'])
        self.assertNotIn(phone, row['sub'])
        self.assertIn(phone, row['text'])

    def test_import_respects_current_user_masking_setting(self):
        self.current['settings']['mask_sensitive'] = False
        token = 'sk-synthetic_import_token_123456789'
        result = self.plan(source(item(token, mask_off=True, sens=['无效'])))
        added = result.data['clip'][0]
        self.assertNotIn('mask_off', added)
        self.assertIn('Token', added['sens'])
        row = ViewProjection().project([added], 'clip', result.data['settings'])[0]
        self.assertEqual(row['disp'], token)

    def test_existing_optional_import_metadata_is_not_overwritten(self):
        self.current['groups'][0]['items'] = [item('old', trigger='used')]
        result = self.plan(source(phrase('g:0:0', 'new', trigger='used',
                                         import_disabled_trigger={'future': [1]})))
        added = result.data['groups'][-1]['items'][0]
        self.assertEqual(added['trigger'], '')
        self.assertEqual(added['import_disabled_trigger'], {'future': [1]})

    def test_image_hash_equality_works_across_different_filenames(self):
        self.current['clip'] = [item('[图片]', content_type='image', image_path='old.png')]
        incoming = source(item('different label', content_type='image', image_path='new.png'),
                          hashes={'new.png': 'same-bytes'})
        result = self.plan(incoming, current_image_hashes={'old.png': 'same-bytes'})
        self.assertEqual((result.imported_count, result.duplicate_count, result.image_map), (0, 1, {}))

    def test_missing_current_image_hash_is_not_assumed_equal(self):
        self.current['clip'] = [item('[图片]', content_type='image', image_path='same.png')]
        incoming = source(item('[图片]', content_type='image', image_path='same.png'),
                          hashes={'same.png': 'new-bytes'})
        result = self.plan(incoming)
        self.assertEqual(result.imported_count, 1)
        self.assertNotEqual(result.data['clip'][0]['image_path'], 'same.png')

    def test_source_image_duplicates_are_skipped_without_extra_assets(self):
        incoming = source(item('[图片]', content_type='image', image_path='one.png'),
                          item('[图片]', content_type='image', image_path='two.png'),
                          hashes={'one.png': 'same', 'two.png': 'same'})
        result = self.plan(incoming)
        self.assertEqual((result.imported_count, result.duplicate_count), (1, 1))
        self.assertEqual(set(result.image_map), {'one.png'})

    def test_nested_optional_image_references_are_renamed_consistently(self):
        old = 'picture.png'
        incoming = source(item('text stays picture.png', image_path=old,
                          future={'image_path': old, 'text': old, 'array': [{'image_path': old}]}),
                          item('second', image_path=old), hashes={old: 'bytes'})
        result = self.plan(incoming)
        new = result.image_map[old]
        first, second = result.data['clip']
        self.assertEqual(first['image_path'], second['image_path'])
        self.assertEqual(first['future']['image_path'], new)
        self.assertEqual(first['future']['array'][0]['image_path'], new)
        self.assertEqual(first['future']['text'], old)
        self.assertEqual(first['text'], 'text stays picture.png')
        self.assertNotEqual(new, old)

    def test_missing_source_images_cannot_be_imported_by_bypassing_preview(self):
        result = self.plan(source(item('text', future={'image_path': 'missing.png'})))
        self.assertTrue(result.error)
        self.assertEqual(result.data, self.current)

    def test_capacity_never_crops_existing_records_or_changes_settings(self):
        self.current['settings']['max_items'] = 10
        self.current['clip'] = [dict(id=str(index), text=str(index)) for index in range(10)]
        result = self.plan(source(item('new')))
        self.assertIn('容量', result.error)
        self.assertEqual(result.data, self.current)
        self.assertEqual(result.imported_count, 0)

    def test_favorite_overflow_matches_existing_crop_contract(self):
        self.current['settings']['max_items'] = 10
        self.current['clip'] = [dict(id=str(index), text=str(index), fav=1) for index in range(10)]
        result = self.plan(source(item('new')))
        self.assertFalse(result.error)
        self.assertEqual(len(result.data['clip']), 11)
        self.assertEqual(result.data['settings'], self.current['settings'])

    def test_capacity_also_protects_new_nonfavorite_records(self):
        self.current['settings']['max_items'] = 10
        result = self.plan(source(*(item(str(index)) for index in range(11))))
        self.assertTrue(result.error)
        self.assertEqual(result.data, self.current)

    def test_phrase_only_import_is_independent_of_history_capacity(self):
        self.current['settings']['max_items'] = 10
        self.current['clip'] = [dict(id=str(index), text=str(index)) for index in range(11)]
        result = self.plan(source(phrase('g:0:0', 'new phrase')))
        self.assertFalse(result.error)
        self.assertEqual(result.data['clip'], self.current['clip'])

    def test_incompatible_current_data_is_not_silently_repaired(self):
        for key, value in (('schema_version', 99), ('clip', {}), ('groups', 'bad'), ('settings', [])):
            with self.subTest(key=key):
                data = deepcopy(self.current)
                data[key] = value
                before = deepcopy(data)
                with self.assertRaises(ImportError):
                    plan_merge(data, source(item('new')))
                self.assertEqual(data, before)


if __name__ == '__main__':
    unittest.main()
