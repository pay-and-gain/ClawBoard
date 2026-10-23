"""History invariants across duplicate copies, edits, and protected retention."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clawboard.history import HistoryService, prepare_text
from clawboard.models import default_data
from clawboard.privacy import display_text


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.data = default_data()
        self.time = 1000
        self.identity = 0
        def uid():
            self.identity += 1
            return str(self.identity)
        self.history = HistoryService(self.data, clock=lambda: self.time, identity=uid)

    def test_duplicate_copy_preserves_first_timestamp_and_identity(self):
        first = self.history.ingest(prepare_text('hello')).item
        self.time = 2000
        self.history.ingest(prepare_text('another'))
        self.time = 3000
        result = self.history.ingest(prepare_text('hello'), source_app='editor')
        self.assertFalse(result.created)
        self.assertIs(result.item, first)
        self.assertEqual(first['created_at'], 1000)
        self.assertEqual(first['updated_at'], 3000)
        self.assertEqual(first['copy_count'], 2)
        self.assertEqual(self.data['clip'][0]['source_app'], 'editor')

    def test_edit_rebuilds_tags_masks_and_kind_without_changing_first_timestamp(self):
        item = self.history.ingest(prepare_text('{"a":1}')).item
        item['mask_off'] = True
        self.time = 5000
        self.history.replace_text(item, 'password=synthetic_secret_123')
        self.assertEqual(item['created_at'], 1000)
        self.assertEqual(item['updated_at'], 5000)
        self.assertIn('密码', item['sens'])
        self.assertIn('password', item['tags'])
        self.assertNotIn('mask_off', item)
        self.assertNotEqual(item['kind_auto'], 'json')
        self.assertNotIn('synthetic_secret_123', display_text(item['text'], item['sens']))
        self.history.replace_text(item, 'ordinary note')
        self.assertNotIn('sens', item)
        self.assertNotIn('password', item.get('tags', []))

    def test_retention_exempts_favorites_and_reports_only_removed_records(self):
        keep = self.history.ingest(prepare_text('favorite')).item
        keep['fav'] = 1
        old = self.history.ingest(prepare_text('old')).item
        change = self.history.ingest(prepare_text('new'), limit=1)
        self.assertEqual({it['text'] for it in self.data['clip']}, {'favorite', 'new'})
        self.assertEqual(change.removed, (old,))

    def test_literal_image_placeholder_never_overwrites_image_metadata(self):
        image = {'id': 'image', 'text': '[图片]', 'content_type': 'image',
                 'created_at': 1, 'image_path': 'existing.png'}
        self.data['clip'].append(image)
        result = self.history.ingest(prepare_text('[图片]'))
        self.assertTrue(result.created)
        self.assertEqual(image['content_type'], 'image')
        self.assertEqual(len(self.data['clip']), 2)


if __name__ == '__main__':
    unittest.main()
