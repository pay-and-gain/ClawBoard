# -*- coding: utf-8 -*-
"""增量重构自测：clawboard 包拆分后的兼容性与纯函数层（不依赖 GUI）。

只做两件事：
1. 验证 `import ClawBoard as C` 的 re-export 聚合层对外符号与老版本一致；
2. 验证 config / runtime / theme / classify / timefmt 的纯函数与数据契约。

本文件绝不创建 Tk 根窗口，因此可被 CI / 无桌面环境直接运行。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ClawBoard as C
from clawboard import runtime
from clawboard.config import AppState, DEFAULT_SETTINGS
from clawboard.theme import T
from clawboard.classify import classify, detect_content_type
from clawboard.timefmt import migrate, now_ms, full_time


class TestReExportCompat(unittest.TestCase):
    """re-export 聚合层：老代码写 C.xxx 必须原样可用。"""

    def test_class_and_ui_symbols(self):
        self.assertTrue(isinstance(C.ClawBoard, type))
        for name in ('Dialog', 'SplitDialog', 'Tip', 'ThinBar', 'ScrollFrame',
                     'VirtualList', 'SettingsWindow', 'TransformWindow', 'ExportDialog'):
            self.assertTrue(hasattr(C, name), '缺少 re-export: %s' % name)

    def test_domain_symbols(self):
        for name in ('classify', 'guess_lang', 'kind_icon', 'type_icon', 'to_plain',
                     'byte_size', 'human_size', 'length_filtered', 'crop_items',
                     'preview', 'rel_time', 'full_time', 'parse_ignore_list',
                     'match_ignore', 'backup_data', 'migrate'):
            self.assertTrue(hasattr(C, name), '缺少 re-export: %s' % name)

    def test_system_symbols(self):
        for name in ('clip_read', 'clip_write', 'clip_seq', 'clip_is_private',
                     'scan_sensitive', 'mask_text', 'single_instance',
                     'init_dpi_awareness', 'HiddenWindow', 'make_ico'):
            self.assertTrue(hasattr(C, name), '缺少 re-export: %s' % name)

    def test_config_symbols(self):
        for name in ('APP_NAME', 'APP_VER', 'BASE_DIR', 'DATA_FILE', 'CRASH_LOG',
                     'FONT', 'FONT_MONO', 'BAR_H', 'ITEM_H', 'MIN_W', 'MIN_H',
                     'MAX_TEXT', 'SCHEMA_VERSION', 'CLASSIFY_MAX', 'DEFAULT_SETTINGS'):
            self.assertTrue(hasattr(C, name), '缺少 re-export: %s' % name)

    def test_mutable_globals_share_same_object(self):
        # 测试写 C.T['acc'] / C.DEFAULT_SETTINGS['collapsed'] 是原地改 dict，
        # re-export 共享同一对象，内部模块必须立刻可见。
        self.assertIs(C.T, T)
        self.assertIs(C.DEFAULT_SETTINGS, DEFAULT_SETTINGS)

    def test_no_save_bridge_forwards_to_runtime(self):
        old = runtime.NO_SAVE
        try:
            C.NO_SAVE = True
            self.assertTrue(runtime.NO_SAVE, 'C.NO_SAVE=True 未转发到 runtime.NO_SAVE')
            C.NO_SAVE = False
            self.assertFalse(runtime.NO_SAVE)
        finally:
            runtime.NO_SAVE = old

    def test_composite_class_methods_present(self):
        # 主类 97 方法拆进 5 个 mixin 后，对外方法名必须一个不丢。
        for name in ('ingest', 'save', 'render', 'paste', 'build_ui', '_layout_tool',
                     'min_size', 'apply_geometry', 'toggle_collapse', 'set_tab',
                     'cur_group', 'visible_items', 'on_click_item', 'quick_paste',
                     'open_settings', 'open_transform', 'open_export', 'quit_app',
                     'poll_clip', 'poll_bg'):
            self.assertTrue(hasattr(C.ClawBoard, name), '主类缺少方法: %s' % name)


class TestPureLayers(unittest.TestCase):
    """config / runtime / theme / classify / timefmt 纯函数。"""

    def test_appstate_defaults(self):
        s = AppState()
        self.assertEqual(s.tab, 'clip')
        self.assertIsNone(s.sel_clip)
        self.assertIsNone(s._restore)
        self.assertFalse(s.collapsed)

    def test_default_settings_required_keys(self):
        for key in ('theme', 'hotkey', 'max_items', 'listen', 'autopaste',
                    'mask_sensitive', 'trim_paste', 'collapsed', 'bg_color'):
            self.assertIn(key, DEFAULT_SETTINGS)

    def test_classify_still_pure(self):
        self.assertEqual(classify('https://a.com')[0], 'url')
        self.assertEqual(classify('{"a":1}')[0], 'json')
        self.assertEqual(classify('def f():\n    pass')[0], 'code')
        self.assertEqual(detect_content_type('hello'), 'text')

    def test_migrate_idempotent(self):
        d = {'clip': [{'text': 'hello'}], 'groups': [{'name': '默认', 'items': []}],
             'gi': 0, 'settings': dict(DEFAULT_SETTINGS), 'schema_version': 1}
        out = migrate(d)
        self.assertEqual(out['schema_version'], 3)
        self.assertEqual(out['clip'][0]['content_type'], 'text')
        again = migrate(out)
        self.assertEqual(again['schema_version'], 3)

    def test_full_time(self):
        self.assertEqual(full_time(None), '—')
        self.assertTrue(full_time(now_ms()).startswith('20'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
