"""DPI transition contracts with fake native functions and Tk ports; no desktop."""
import importlib
import re
import types
import unittest
from unittest.mock import Mock

from test_windows_boundaries import WindowsHarness


class Root:
    def __init__(self):
        self.rect = (500, 600, 200, 100)
        self.tk = types.SimpleNamespace(call=Mock())
        self.minimum = None
        self.grab = None

    def winfo_id(self): return 0x123456789
    def winfo_width(self): return self.rect[0]
    def winfo_height(self): return self.rect[1]
    def winfo_x(self): return self.rect[2]
    def winfo_y(self): return self.rect[3]
    def grab_current(self): return self.grab
    def minsize(self, *value): self.minimum = value
    def geometry(self, value):
        self.rect = tuple(map(int, re.fullmatch(r'(\d+)x(\d+)\+(-?\d+)\+(-?\d+)', value).groups()))


class DpiTests(unittest.TestCase):
    def setUp(self):
        self.win = WindowsHarness()
        self.addCleanup(self.win.close)
        self.config = importlib.import_module('clawboard.config')
        self.config.ITEM_H = 52
        self.config.UI_SCALE, self.config.DPI_SCALE = 1.25, 1.25
        self.config.scaled = lambda value: max(1, int(value * self.config.UI_SCALE * self.config.DPI_SCALE))
        self.geometry = importlib.import_module('clawboard.app_geometry')
        self.panel = self.geometry.GeometryMixin()
        self.panel.root = Root()
        self.panel._dpi_scale, self.panel._dpi_pending = 1.25, None
        self.panel._dpi_ready = True
        self.panel.collapsed = self.panel.hidden = self.panel._edge_hidden = False
        self.panel._dpi_view_state = Mock(return_value={'preserved': True})
        self.panel._dpi_restore_view = Mock()
        self.win.u32.GetDpiForWindow.impl = lambda hwnd: 144
        self.win.u32.GetDpiForSystem.impl = lambda: 120

    def transition(self):
        self.assertFalse(self.panel.sync_window_dpi())
        self.assertTrue(self.panel.sync_window_dpi())

    def test_window_dpi_preserves_handle_width_and_falls_back_without_window(self):
        system = self.win.module.windows_system
        self.assertEqual(system.dpi_scale(self.panel.root), 1.5)
        self.assertEqual(self.win.u32.GetDpiForWindow.calls[-1][1], (0x123456789,))
        self.win.u32.GetDpiForWindow.impl = lambda hwnd: 0
        self.assertEqual(system.dpi_scale(self.panel.root), 1.25)
        self.assertEqual(system.dpi_scale(None), 1.25)

    def test_transition_updates_fonts_layout_and_minimum_once_without_changing_ui_level(self):
        self.transition()
        self.assertEqual(self.panel.root.rect, (600, 720, 150, 40))
        self.assertEqual(self.panel.root.minimum, (525, 637))
        self.assertEqual(self.config.UI_SCALE, 1.25)
        self.assertEqual(self.config.DPI_SCALE, 1.5)
        self.assertEqual(self.config.scaled(52), 97)
        self.panel.root.tk.call.assert_called_once_with('tk', 'scaling', 2.5)
        self.panel._dpi_restore_view.assert_called_once_with({'preserved': True})
        self.assertFalse(self.panel.sync_window_dpi())
        self.win.u32.GetDpiForWindow.impl = lambda hwnd: 120
        self.transition()
        self.assertEqual(self.panel.root.rect, (500, 600, 200, 100))

    def test_drag_modal_and_edge_hide_postpone_rebuild_until_stable(self):
        self.win.u32.GetAsyncKeyState.impl = lambda vk: 0x8000
        self.assertFalse(self.panel.sync_window_dpi())
        self.assertFalse(self.panel.sync_window_dpi())
        self.win.u32.GetAsyncKeyState.impl = lambda vk: 0
        self.panel.root.grab = object()
        self.assertFalse(self.panel.sync_window_dpi())
        self.panel.root.grab = None
        self.panel._edge_hidden = True
        self.assertFalse(self.panel.sync_window_dpi())
        self.panel._edge_hidden = False
        self.assertTrue(self.panel.sync_window_dpi())
        self.panel._dpi_restore_view.assert_called_once()

    def test_collapsed_state_and_restore_geometry_survive_transition(self):
        self.panel.collapsed = True
        self.panel._restore = '500x600+200+100'
        self.transition()
        self.assertEqual(self.panel.root.rect[:2], (393, 63))
        self.assertEqual(self.panel.root.minimum, (300, 63))
        self.assertEqual(self.panel._restore, '600x720+200+100')
        self.assertTrue(self.panel.collapsed)

    def test_hidden_window_defers_until_mapped_without_waking_it(self):
        self.panel.hidden = True
        self.assertFalse(self.panel.sync_window_dpi())
        self.assertFalse(self.panel.sync_window_dpi())
        self.panel._dpi_restore_view.assert_not_called()
        self.panel.hidden = False
        self.transition()

    def test_initial_saved_physical_geometry_is_not_scaled_twice(self):
        self.panel._dpi_ready = False
        self.transition()
        self.assertEqual(self.panel.root.rect, (525, 637, 187, 81))
        self.assertTrue(self.panel._dpi_ready)

    def test_deferred_view_restore_is_discarded_after_query_tab_or_group_changes(self):
        self.panel.search = types.SimpleNamespace(get=lambda: 'sample')
        self.panel.tab, self.panel.data = 'clip', {'gi': 0}
        self.panel.vlist = types.SimpleNamespace(update_view=Mock(), items=[{'id': 'one'}])
        for key in (('old', 'clip', 0), ('sample', 'phrase', 0), ('sample', 'clip', 1)):
            self.panel._dpi_deferred_view = dict(key=key, top=10, multi={'one'})
            self.panel.restore_dpi_view()
            self.assertIsNone(self.panel._dpi_deferred_view)
        self.panel.vlist.update_view.assert_not_called()
        self.panel._dpi_deferred_view = dict(key=('sample', 'clip', 0), top=10, multi={'one', 'gone'})
        self.panel.restore_dpi_view()
        self.assertEqual(self.panel.vlist.multi, {'one'})
        self.assertEqual(self.panel.vlist._pending_top, 810)
        self.panel.vlist.update_view.assert_called_once()


if __name__ == '__main__':
    unittest.main(verbosity=2)
