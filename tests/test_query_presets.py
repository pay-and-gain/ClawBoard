"""Visible filters retain unrelated advanced search conditions; synthetic data."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clawboard.query_presets import clear_visual_filters, has_favorite, set_filter
from clawboard.search import match


class VisualFilterTests(unittest.TestCase):
    def test_type_replaces_positive_family_but_keeps_negatives_and_terms(self):
        query = '报告 app:记事本 type:text -type:json size:>10 TYPE:url'
        self.assertEqual(set_filter(query, 'type', 'image'),
                         '报告 app:记事本 -type:json size:>10 type:image')

    def test_favorites_do_not_discard_pin_sensitive_or_excluded_favorites(self):
        query = 'is:pin IS:FAV -is:fav is:sens test'
        self.assertTrue(has_favorite(query))
        self.assertEqual(set_filter(query, 'favorite'), 'is:pin -is:fav is:sens test')
        self.assertFalse(has_favorite('-is:fav'))
        self.assertEqual(set_filter('is:pin', 'favorite', True), 'is:pin is:fav')

    def test_clear_preserves_keywords_sources_sizes_and_other_flags(self):
        query = '你好 type:image time:<1d is:fav app:chrome size:>10 is:pin -type:url'
        self.assertEqual(clear_visual_filters(query), '你好 app:chrome size:>10 is:pin -type:url')

    def test_filter_query_uses_existing_search_results(self):
        items = [dict(id='text', text='sample', content_type='text', fav=0),
                 dict(id='image', text='sample', content_type='image', fav=1)]
        query = set_filter('sample', 'type', 'image')
        query = set_filter(query, 'favorite', True)
        result, _ = match(query, items)
        self.assertEqual([item['id'] for item in result], ['image'])
        result, _ = match(clear_visual_filters(query), items)
        self.assertEqual(len(result), 2)

    def test_repeat_is_idempotent_and_unknown_control_is_rejected(self):
        once = set_filter('a type:image', 'type', 'url')
        self.assertEqual(set_filter(once, 'type', 'url'), once)
        with self.assertRaises(ValueError):
            set_filter('a', 'execute', 'anything')


if __name__ == '__main__':
    unittest.main(verbosity=2)
