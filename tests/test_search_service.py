# -*- coding: utf-8 -*-
"""Search/viewport regressions using synthetic records and a headless widget seam."""
import ast
import pathlib
import random
import sys
import types
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import query
from clawboard import search
from clawboard.classify import preview
from clawboard.config import FONT, FONT_MONO, FONT_SM, ITEM_H, CARD_GAP, scaled
from clawboard.theme import T


class SearchServiceTests(unittest.TestCase):
    def test_metadata_does_not_read_text_or_generate_pinyin(self):
        class MetadataOnly(dict):
            def get(self, key, default=None):
                if key in ('text', 'name'):
                    raise AssertionError('metadata filtering accessed body')
                return super().get(key, default)
        item = MetadataOnly(source_app='chrome', content_type='text', fav=1,
                            tags=['email'], content_size=200, created_at=1)
        with patch.object(search, 'to_pinyin', side_effect=AssertionError('pinyin called')):
            got, _ = search.SearchService().match('app:chrome type:text is:fav tag:email size:>100', [item])
        self.assertEqual(got, [item])

    def test_direct_match_does_not_generate_pinyin(self):
        with patch.object(search, 'to_pinyin', side_effect=AssertionError('pinyin called')):
            self.assertEqual(search.match('账号', [{'text': '项目账号'}])[0], [{'text': '项目账号'}])
            self.assertEqual(search.match('hello', [{'text': 'hello world'}])[0], [{'text': 'hello world'}])

    def test_ascii_miss_does_not_generate_pinyin(self):
        with patch.object(search, 'to_pinyin', side_effect=AssertionError('pinyin called')):
            self.assertEqual(search.match('missing', [{'text': 'hello world'}])[0], [])
            self.assertEqual(search.match('hello -missing', [{'text': 'hello world'}])[0], [{'text': 'hello world'}])

    def test_pinyin_and_exclusion_keep_original_semantics(self):
        items = [{'text': '账号'}, {'text': '银行账号'}, {'text': 'hello'}]
        self.assertEqual(search.match('zhanghao -yinhang', items)[0], [items[0]])
        self.assertEqual(search.match('zh', items)[0], items[:2])
        self.assertEqual(search.match('-zhanghao', items)[0], [items[2]])
        self.assertEqual(search.match('账号 -yinhang', items)[0], [items[0]])

    def test_cache_is_reused_and_edited_text_never_uses_old_value(self):
        service = search.SearchService()
        item = {'id': 'stable-id', 'text': '账号'}
        original = search.to_pinyin
        with patch.object(search, 'to_pinyin', wraps=original) as convert:
            self.assertEqual(service.match('zhanghao', [item])[0], [item])
            self.assertEqual(service.match('zh', [item])[0], [item])
            self.assertEqual(convert.call_count, 1)
            item['text'] = '银行'
            self.assertEqual(service.match('zhanghao', [item])[0], [])
            self.assertEqual(service.match('yinhang', [item])[0], [item])
            self.assertEqual(convert.call_count, 2)
        service.clear()
        self.assertEqual(service.cache_size, 0)
        self.assertEqual(service.cached_chars, 0)

    def test_cache_stays_inside_entry_and_character_budgets(self):
        service = search.SearchService(max_entries=2, max_chars=100)
        for text in ('账号', '银行', '邮件', '工程'):
            service.match('unlikelyterm', [{'text': text}])
            self.assertLessEqual(service.cache_size, 2)
            self.assertLessEqual(service.cached_chars, 100)
        service.match('unlikelyterm', [{'text': '账号' * 1000}])
        self.assertLessEqual(service.cache_size, 2)
        self.assertLessEqual(service.cached_chars, 100)

    def test_ascii_log_suffixes_share_small_pinyin_segments(self):
        service = search.SearchService()
        items = [{'id': str(i), 'text': '账号 log entry ' + str(i)} for i in range(50)]
        with patch.object(search, 'to_pinyin', wraps=search.to_pinyin) as convert:
            self.assertEqual(service.match('zhanghao', items)[0], items)
            self.assertEqual(convert.call_count, 1)
        self.assertEqual(service.cache_size, 1)
        self.assertLess(service.cached_chars, 40)

    def test_segment_derivation_preserves_full_pinyin_order(self):
        text = '重庆AI银行 中文 account123 账号'
        cache = search._PinyinCache()
        expected = search.to_pinyin(text) + ' ' + search.to_pinyin_initials(text)
        self.assertEqual(cache.get(text), expected)
        # A future mixed-script dictionary can use the complete conversion path.
        with patch.object(search, '_ASCII_SPLIT_SAFE', False):
            self.assertEqual(cache.get(text), expected)

    def test_randomized_text_predicate_matches_original_haystack(self):
        rng = random.Random(42)
        items = [{'text': ''.join(rng.choices(['账号', '银行', ' hello ', 'abc', '中文', ' '], k=5)),
                  'name': rng.choice(['名称', 'title', ''])} for _ in range(60)]
        for q in ('hello', 'zh', 'yinhang', '账号 -hello', 'abc -zhongwen', '-zh', 'title hello'):
            cond = search.parse(q)
            def original(it):
                text = it['text'].lower()
                hay = text + ' ' + it['name'].lower() + ' ' + search.to_pinyin(text) + ' ' + search.to_pinyin_initials(text)
                return all(t in hay for t in cond['terms']) and not any(t in hay for t in cond['not_terms'])
            self.assertEqual(search.SearchService().match(q, items)[0], [it for it in items if original(it)])

    def test_facade_preserves_midnight_test_clock_seam(self):
        self.assertIs(query.time, search.time)
        self.assertIs(query.parse, search.parse)
        self.assertIs(query.compile_pred, search.compile_pred)

    def test_numeric_content_type_does_not_crash(self):
        self.assertEqual(search.match('type:text', [{'text': 'test', 'content_type': 1}])[0], [])


class FakeWidget:
    def __init__(self):
        self.configurations = []
        self.destroyed = False
    def configure(self, **kw):
        self.configurations.append(kw)
    def destroy(self):
        self.destroyed = True


class FakeCanvas:
    def __init__(self):
        self.top = 0.0
        self.height = ITEM_H * 2
        self.width = 350
        self.region = (0, 0, self.width, 1)
        self.ids = 0
        self.deleted = []
        self.windows = {}
    def canvasy(self, value):
        return self.top + value
    def winfo_width(self):
        return self.width
    def winfo_height(self):
        return self.height
    def configure(self, **kw):
        if 'scrollregion' in kw:
            self.region = kw['scrollregion']
    def yview_moveto(self, fraction):
        self.top = fraction * self.region[3]
    def create_window(self, pos, **kw):
        self.ids += 1
        self.windows[self.ids] = kw
        return self.ids
    def coords(self, wid, *pos):
        self.windows[wid]['pos'] = pos
    def itemconfigure(self, wid, **kw):
        self.windows[wid].update(kw)
    itemconfig = itemconfigure
    def delete(self, wid):
        self.deleted.append(wid)
        self.windows.pop(wid, None)


def viewport_class():
    # Loading the real class definition avoids importing Win32-backed popups.
    # Only widget construction is replaced; set_data/update_view/_fill run intact.
    tree = ast.parse((ROOT / 'clawboard/vlist.py').read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'VirtualList')
    ns = dict(tk=types.SimpleNamespace(Frame=object), scaled=scaled,
              ITEM_H=ITEM_H, CARD_GAP=CARD_GAP, T=T, preview=preview,
              FONT=FONT, FONT_MONO=FONT_MONO, FONT_SM=FONT_SM)
    exec(compile(ast.Module(body=[cls], type_ignores=[]), 'clawboard/vlist.py', 'exec'), ns)
    return ns['VirtualList']


class ViewportTests(unittest.TestCase):
    def setUp(self):
        self.view = object.__new__(viewport_class())
        v = self.view
        v.items, v.pool, v.wids, v._free = [], {}, {}, []
        v.sel, v.kw, v.multi = None, '', set()
        v._pending_top, v._scrollregion = None, None
        v._vw, v._maxc, v._maxc2, v.show_num = 0, 0, 40, False
        v.canvas = FakeCanvas()
        v._hide_empty = lambda: None
        v._show_empty = lambda: None
        v._layout = lambda frame, width: None
        self.frames = []
        def make_row(index):
            frame = FakeWidget()
            frame._idx, frame._vw, frame._numw = index, 0, 16
            for name in ('_row', '_num', '_l1a', '_l1b', '_l1c', '_l2', '_badge'):
                setattr(frame, name, FakeWidget())
            self.frames.append(frame)
            return frame
        v._mk_item = make_row
        self.items = [{'id': str(i), 'text': 'hello %s' % i, 'disp': 'hello %s' % i,
                       'sub': 'metadata', 'badge': '10 B', 'kind': 'clip'} for i in range(30)]

    def test_scrolling_reuses_rows_without_destroying_them(self):
        v = self.view
        v.set_data(self.items, None, '')
        created = len(self.frames)
        original_ids = {id(f) for f in self.frames}
        v.canvas.top = ITEM_H * 10
        v.update_view()
        self.assertEqual(len(self.frames), created)
        self.assertEqual({id(f) for f in v.pool.values()}, original_ids)
        self.assertFalse(any(frame.destroyed for frame in self.frames))
        self.assertEqual(v.canvas.deleted, [])

    def test_data_refresh_preserves_stable_scroll_anchor(self):
        v = self.view
        v.set_data(self.items, '10', '')
        v.canvas.top = ITEM_H * 10 + 7
        v.update_view()
        v.set_data([{'id': 'new', 'text': 'new'}] + self.items, '10', '')
        self.assertAlmostEqual(v.canvas.top, ITEM_H * 11 + 7)
        self.assertEqual(v.sel, '10')
        v.set_data(self.items, None, 'hello', reset_scroll=True)
        self.assertEqual(v.canvas.top, 0)

    def test_identical_refresh_does_not_reconfigure_row_labels(self):
        v = self.view
        v.set_data(self.items, None, '')
        before = [len(f._l1a.configurations) for f in self.frames]
        v.update_view()
        v.set_data(list(self.items), None, '')
        self.assertEqual([len(f._l1a.configurations) for f in self.frames], before)

    def test_selection_only_repaints_affected_rows(self):
        v = self.view
        v.set_data(self.items, None, '')
        text_calls = sum(sum('text' in c for c in f._l1a.configurations) for f in self.frames)
        paint_calls = sum(len(f.configurations) for f in self.frames)
        v.sel = '1'
        v.update_view()
        self.assertEqual(sum(sum('text' in c for c in f._l1a.configurations) for f in self.frames), text_calls)
        self.assertEqual(sum(len(f.configurations) for f in self.frames), paint_calls + 1)

    def test_empty_results_keep_rows_available_for_next_query(self):
        v = self.view
        v.set_data(self.items, None, '')
        count = len(self.frames)
        v.set_data([], None, 'missing', reset_scroll=True)
        self.assertEqual(v.pool, {})
        self.assertFalse(any(frame.destroyed for frame in self.frames))
        v.set_data(self.items, None, '', reset_scroll=True)
        self.assertEqual(len(self.frames), count)

    def test_removed_multi_selection_is_discarded(self):
        v = self.view
        v.set_data(self.items, None, '')
        v.multi = {'0', '20'}
        v.set_data(self.items[1:], None, '')
        self.assertEqual(v.multi, {'20'})

    def test_search_placeholder_preserves_multi_until_final_results_arrive(self):
        v = self.view
        v.set_data(self.items, None, '')
        v.multi = {'0', '20'}
        v.set_data([], None, 'hello', preserve_selection=True)
        self.assertEqual(v.multi, {'0', '20'})
        v.set_data(self.items[1:], None, 'hello')
        self.assertEqual(v.multi, {'20'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
