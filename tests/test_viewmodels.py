"""View-model regressions use synthetic records; no Tk, Win32 or data writes."""
from collections.abc import Mapping
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from copy import deepcopy
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clawboard.viewmodels import ProjectedRow, ViewProjection


def item(index=0, text='hello world', **extra):
    return dict(id=str(index), text=text, source_app='chrome', created_at=1700000000000,
                content_size=len(text.encode()), **extra)


class ProjectionTests(unittest.TestCase):
    def test_projection_and_raw_fields_never_derive(self):
        records = [item(index, 'long text ' * 500) for index in range(1000)]
        with patch('clawboard.viewmodels.classify') as classify, \
                patch('clawboard.viewmodels.privacy.display_text') as display, \
                patch('clawboard.viewmodels.privacy.scan_sensitive') as scan:
            projection = ViewProjection()
            rows = projection.project(records, 'clip', {})
            self.assertEqual(len(rows), 1000)
            for row, raw in zip(rows, records):
                self.assertIsInstance(row, Mapping)
                self.assertIs(row['text'], raw['text'])
                self.assertEqual(row['id'], raw['id'])
                self.assertEqual(row.get('source_app'), 'chrome')
                self.assertEqual(row.get('image_path'), None)
                self.assertEqual(row.get('fav'), 0)
            classify.assert_not_called()
            display.assert_not_called()
            scan.assert_not_called()
            self.assertEqual(projection.cache_size, 0)

    def test_only_two_accessed_rows_derive_and_repeated_fields_reuse(self):
        rows = ViewProjection().project([item(i) for i in range(1000)], 'clip',
                                        {'show_source': True, 'show_size': True})
        with patch('clawboard.viewmodels.classify', return_value=('text', {})) as classify, \
                patch('clawboard.viewmodels.privacy.display_text', side_effect=lambda text, *a, **k: text) as display:
            self.assertEqual(rows[4]['disp'], 'hello world')
            self.assertIn('chrome', rows[4]['sub'])
            self.assertEqual(rows[4]['kind_auto'], 'text')
            self.assertTrue(rows[900]['badge'])
            self.assertEqual(classify.call_count, 2)
            self.assertEqual(display.call_count, 2)

    def test_complete_raw_text_survives_display_cap(self):
        raw = item(text='hello ' * 40000, fav=1, pinned=1)
        row = ViewProjection().project([raw], 'clip', {})[0]
        self.assertIs(row['text'], raw['text'])
        self.assertLessEqual(len(row['disp']), 2048)
        self.assertTrue(row['disp'].startswith('📌 ★ '))
        self.assertEqual(row['fav'], 1)
        self.assertEqual(row['pinned'], 1)

    def test_changes_to_text_metadata_and_settings_invalidate(self):
        raw = item()
        settings = {'mask_sensitive': True}
        projection = ViewProjection()
        row = projection.project([raw], 'clip', settings)[0]
        self.assertEqual(row['disp'], 'hello world')
        raw['text'] = 'password=synthetic_secret_value'
        self.assertNotIn('synthetic_secret_value', row['disp'])
        raw['copy_count'] = 3
        raw['tags'] = ['email']
        self.assertIn('×3', row['sub'])
        self.assertIn('邮箱', row['sub'])
        raw['tags'][0] = 'phone'
        self.assertIn('手机号', row['sub'])
        raw['mask_off'] = True
        self.assertIn('synthetic_secret_value', row['disp'])
        raw['mask_off'] = False
        settings['mask_sensitive'] = False
        self.assertIn('synthetic_secret_value', row['disp'])
        settings['mask_sensitive'] = True
        self.assertNotIn('synthetic_secret_value', row['disp'])

    def test_default_mask_and_truncation_boundary_are_safe(self):
        secret = 'password=very_secret_value'
        text = 'x' * 2038 + ' ' + secret
        row = ViewProjection().project([item(text=text, sens=['密码'])], 'clip', {})[0]
        self.assertNotIn('very', row['disp'])
        self.assertNotEqual(row['disp'], text[:2048])
        self.assertEqual(row['text'], text)

    def test_phrase_name_and_unnamed_preview_are_masked(self):
        projection = ViewProjection()
        named = projection.project([item(name='password=synthetic_secret')], 'phrase',
                                   {'show_size': True})[0]
        unnamed = projection.project([item(text='password=synthetic_secret')], 'phrase', {})[0]
        self.assertNotIn('synthetic_secret', named['sub'])
        self.assertNotIn('synthetic_secret', unnamed['sub'])
        self.assertEqual(named['badge'], '11 B')

    def test_image_semantics_and_direct_metadata(self):
        raw = item(text='[图片]', content_type='image', image_path='example.png', image_w=1920, image_h=1080)
        row = ViewProjection().project([raw], 'clip', {'show_source': True, 'show_size': True})[0]
        self.assertEqual(row['disp'], '图片 1920×1080')
        self.assertEqual(row['badge'], '1920×1080')
        self.assertEqual(row['kind_auto'], 'image')
        self.assertEqual(row['sub'], 'chrome · 图片')
        self.assertEqual(row.get('image_path'), 'example.png')
        self.assertEqual(row['kind'], 'clip')
        self.assertEqual(row['app'], 'chrome')

    def test_display_switches_are_independent_and_invalidate_existing_rows(self):
        raw = item(text='first\nsecond', copy_count=3, tags=['email'])
        before = deepcopy(raw)
        settings = {}
        row = ViewProjection().project([raw], 'clip', settings)[0]
        for source, size in ((False, False), (True, False), (True, True),
                             (False, True), (False, False)):
            settings.update(show_source=source, show_size=size)
            self.assertEqual('chrome' in row['sub'], source)
            self.assertEqual(bool(row['badge']), size)
            for marker in ('+1 行', '×3', '邮箱'):
                self.assertIn(marker, row['sub'])
            self.assertEqual(row['source_app'], 'chrome')
            self.assertEqual(row['text'], raw['text'])
        self.assertEqual(raw, before)

    def test_default_hidden_preserves_phrase_names_and_image_metadata(self):
        projection = ViewProjection()
        phrase = projection.project([item(name='Synthetic name')], 'phrase', {})[0]
        image = projection.project([item(content_type='image', image_w=320, image_h=200)],
                                   'clip', {})[0]
        self.assertEqual(phrase['sub'], 'Synthetic name')
        self.assertEqual(phrase['badge'], '')
        self.assertEqual(image['sub'], '图片')
        self.assertEqual(image['badge'], '')
        self.assertEqual(image['image_w'], 320)

    def test_legacy_settings_default_off_and_persist_without_metadata_changes(self):
        from clawboard.models import default_data
        from clawboard.storage import JsonStore
        import json
        data = default_data()
        self.assertFalse(data['settings'].pop('show_source'))
        self.assertFalse(data['settings'].pop('show_size'))
        data['settings']['future_setting'] = 'preserved'
        data['clip'] = [item()]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'synthetic.json'
            path.write_text(json.dumps(data), encoding='utf-8')
            before = path.read_bytes()
            store = JsonStore(path)
            loaded = store.load().data
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse(loaded['settings']['show_source'])
            self.assertFalse(loaded['settings']['show_size'])
            raw = deepcopy(loaded['clip'])
            loaded['settings'].update(show_source=True, show_size=True)
            store.save(loaded)
            restored = JsonStore(path).load().data
            self.assertTrue(restored['settings']['show_source'])
            self.assertTrue(restored['settings']['show_size'])
            self.assertEqual(restored['clip'], raw)
            self.assertEqual(restored['settings']['future_setting'], 'preserved')

    def test_lru_limits_entry_count_and_characters(self):
        projection = ViewProjection(max_entries=2)
        rows = projection.project([item(i) for i in range(5)], 'clip', {})
        for row in rows:
            self.assertTrue(row['disp'])
        self.assertEqual(projection.cache_size, 2)
        small = ViewProjection(max_entries=20, max_cache_chars=100)
        for row in small.project([item(i, text='a' * 50) for i in range(3)], 'clip', {}):
            self.assertTrue(row['disp'])
        self.assertLessEqual(small.cache_chars, 100)
        projection.clear()
        self.assertEqual(projection.cache_size, 0)
        self.assertEqual(projection.cache_chars, 0)

    def test_relative_time_cache_expires_by_minute(self):
        clock = [1700000000000]
        projection = ViewProjection(clock=lambda: clock[0])
        row = projection.project([item()], 'clip', {'show_time': True})[0]
        with patch('clawboard.viewmodels.rel_time', side_effect=['刚刚', '1 分钟前']) as relative:
            self.assertIn('刚刚', row['sub'])
            self.assertIn('刚刚', row['sub'])
            clock[0] += 60000
            self.assertIn('1 分钟前', row['sub'])
            self.assertEqual(relative.call_count, 2)

    def test_mapping_is_read_only_and_preserves_optional_raw_fields(self):
        raw = item(future_field='kept', is_estimated=1)
        row = ViewProjection().project([raw], 'clip', {})[0]
        self.assertIsInstance(row, ProjectedRow)
        self.assertEqual(row['future_field'], 'kept')
        self.assertEqual(row['est'], 1)
        self.assertEqual(row.get('missing', 'fallback'), 'fallback')
        self.assertEqual(len(row), len(set(row)))
        with self.assertRaises(TypeError):
            row['text'] = 'changed'


if __name__ == '__main__':
    unittest.main(verbosity=2)
