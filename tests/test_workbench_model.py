"""Synthetic workbench domain regressions; no Tk, native input or data files."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clawboard.workbench_model import WorkbenchModel, collect_entries, full_preview, metadata


def record(identifier, text, **extra):
    return dict(id=identifier, text=text, content_size=len(text.encode()),
                source_app='SyntheticApp', content_type='text', **extra)


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.data = dict(clip=[record('c1', 'hello 你好', fav=1), record('c2', 'second')],
                         groups=[dict(name='one', items=[record('p1', 'phrase', name='Greeting')]),
                                 dict(name='two', items=[record('p2', 'another phrase')])])
        self.model = WorkbenchModel()

    def test_collection_keeps_group_identity_without_mutation(self):
        before = deepcopy(self.data)
        entries = collect_entries(self.data, 'phrase')
        self.assertEqual([entry.key for entry in entries], [('phrase', 'p1'), ('phrase', 'p2')])
        self.assertEqual([entry.group_index for entry in entries], [0, 1])
        self.assertIs(entries[0].record, self.data['groups'][0]['items'][0])
        self.assertEqual(self.data, before)

    def test_shared_query_and_favorite_filters(self):
        entries = collect_entries(self.data)
        result, errors = self.model.prepare(entries, '你好 app:SyntheticApp', {}, favorites=True)
        self.assertFalse(errors)
        self.assertEqual([entry.record['id'] for entry, _ in result], ['c1'])
        self.assertNotIn('SyntheticApp', result[0][1])
        result, _ = self.model.prepare(entries, '-hello', {})
        self.assertEqual([entry.record['id'] for entry, _ in result], ['c2'])

    def test_type_filter_uses_common_search_contract(self):
        self.data['clip'][1]['content_type'] = 'image'
        self.data['clip'][1].update(image_w=20, image_h=10)
        result, _ = self.model.prepare(collect_entries(self.data), '', {}, 'image')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0].record['id'], 'c2')
        self.assertIn('图片', result[0][1])

    def test_full_preview_does_not_use_truncated_or_masked_list_text(self):
        text = 'prefix ' * 1000 + '完整末尾'
        self.data['clip'][0]['text'] = text
        entry = collect_entries(self.data)[0]
        rows, _ = self.model.prepare([entry], '', {})
        self.assertNotIn('完整末尾', rows[0][1])
        self.assertEqual(full_preview(entry, {}), text)
        entry.record['text'] = 'password=synthetic-secret-value'
        self.assertNotIn('synthetic-secret-value', full_preview(entry, {}))
        self.assertEqual(full_preview(entry, {'mask_sensitive': False}), entry.record['text'])

    def test_metadata_hidden_by_default_and_explicit_expand(self):
        entry = collect_entries(self.data)[0]
        self.assertEqual(metadata(entry, {}), '')
        self.assertIn('SyntheticApp', metadata(entry, {'show_source': True}))
        self.assertNotIn('大小', metadata(entry, {'show_source': True}))
        self.assertIn('大小', metadata(entry, {'show_size': True}))
        self.assertNotIn('SyntheticApp', metadata(entry, {'show_size': True}))
        self.assertIn('来源', metadata(entry, {}, expanded=True))

    def test_cancelled_work_does_not_scan_or_return_stale_rows(self):
        rows, errors = self.model.prepare(collect_entries(self.data), '', {}, cancelled=lambda: True)
        self.assertEqual(rows, [])
        self.assertEqual(errors, [])

    def test_legacy_record_fields_and_settings_remain_unchanged(self):
        before = deepcopy(self.data)
        settings = {'show_source': True, 'show_size': True, 'future': 'keep'}
        self.model.prepare(collect_entries(self.data), '', settings)
        self.assertEqual(self.data, before)
        self.assertEqual(settings, {'show_source': True, 'show_size': True, 'future': 'keep'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
