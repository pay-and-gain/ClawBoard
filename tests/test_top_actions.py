"""Top action bars: fake monitor geometry and standalone synthetic Tk controls.

No ClawBoard App, library, clipboard, or external program is constructed.
"""
import ctypes
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clawboard import widgets


class CenterTests(unittest.TestCase):
    def test_work_area_clamps_size_and_preserves_negative_monitor_coordinates(self):
        class Rect(ctypes.Structure):
            _fields_ = [(name, ctypes.c_long) for name in ('left', 'top', 'right', 'bottom')]
        class Info(ctypes.Structure):
            _fields_ = [('cbSize', ctypes.c_uint), ('rcWork', Rect)]
        def info(_, pointer):
            pointer._obj.rcWork = Rect(-900, -120, 0, 520)
            return True
        captured = []
        win = SimpleNamespace(update_idletasks=lambda: None, geometry=captured.append)
        parent = SimpleNamespace(winfo_rootx=lambda: -200, winfo_rooty=lambda: -80,
            winfo_width=lambda: 300, winfo_height=lambda: 200,
            winfo_screenwidth=lambda: 1920, winfo_screenheight=lambda: 1080)
        api = SimpleNamespace(u32=SimpleNamespace(MonitorFromWindow=lambda *_: 1,
                              GetMonitorInfoW=info), MONITORINFO=Info, MONITOR_DEFAULTTONEAREST=2)
        native = SimpleNamespace(top_hwnd=lambda _: 1)
        with patch.dict(sys.modules, {'clawboard.windows_api': api, 'clawboard.windows_geometry': native}):
            widgets.center_on(win, parent, 2000, 2000)
        import re
        match = re.fullmatch(r'(\d+)x(\d+)([+-]\d+)([+-]\d+)', captured[0])
        width, height, x, y = map(int, match.groups())
        self.assertLessEqual(width, 900)
        self.assertLessEqual(height, 640)
        self.assertGreaterEqual(x, -900)
        self.assertLessEqual(x + width, 0)
        self.assertGreaterEqual(y, -120)
        self.assertLessEqual(y + height, 520)


@unittest.skipUnless(os.name == 'nt', 'standalone native Tk geometry requires Windows')
class NativeActionsTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.tk = tk
        self.root = tk.Tk()
        self.root.title('ClawBoard synthetic action layout')
        self.root.geometry('300x200+40+40')
        self.errors, self.tcl_errors, self.windows, self.invalidated = [], [], [], []
        self.root.report_callback_exception = lambda kind, value, trace: self.errors.append(repr(value))
        self.root.tk.createcommand('cb_top_action_bgerror', lambda text: self.tcl_errors.append(text))
        self.root.tk.eval('proc bgerror {message} {cb_top_action_bgerror $message}')
        self.app = SimpleNamespace(root=self.root,
            application=SimpleNamespace(tasks=SimpleNamespace(invalidate=self.invalidated.append)),
            tip=lambda _: None)
        self.pump(.04)

    def tearDown(self):
        for window in self.windows:
            if window.win.winfo_exists():
                if isinstance(window, widgets.Dialog):
                    window._cancel()
                elif isinstance(window, widgets.SplitDialog):
                    window.cancel()
                else:
                    window.close()
        self.pump(.12)
        try:
            self.assertEqual(self.errors, [])
            self.assertEqual(self.tcl_errors, [])
        finally:
            self.root.destroy()

    def pump(self, seconds=.06):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.root.update()
            time.sleep(.003)

    def inside(self, widget, win):
        self.assertTrue(widget.winfo_ismapped())
        x, y = widget.winfo_rootx(), widget.winfo_rooty()
        self.assertGreaterEqual(x, win.winfo_rootx())
        self.assertGreaterEqual(y, win.winfo_rooty())
        self.assertLessEqual(x + widget.winfo_width(), win.winfo_rootx() + win.winfo_width())
        self.assertLessEqual(y + widget.winfo_height(), win.winfo_rooty() + win.winfo_height())

    def dialog(self):
        dialog = widgets.Dialog(self.root, 'Synthetic edit', [
            ('名称', 'Synthetic name', False), ('内容', 'Long synthetic 中文\n' * 250, True)])
        self.windows.append(dialog)
        dialog.show(100, 30)
        self.pump()
        return dialog

    def transform(self):
        from clawboard.transform_dialog import TransformWindow
        dialog = TransformWindow(self.app, 'Synthetic source 中文\n' * 120)
        self.windows.append(dialog)
        self.pump()
        return dialog

    def test_legacy_small_dialog_keeps_native_buttons_above_scroll_body(self):
        dialog = self.dialog()
        dialog.win.geometry('%dx%d' % dialog.win.minsize())
        self.pump()
        for button in (dialog.ok_button, dialog.cancel_button):
            self.assertEqual(button.winfo_class(), 'Button')
            self.inside(button, dialog.win)
            self.assertLess(button.winfo_rooty(), dialog.body.winfo_rooty())
        self.assertGreater(dialog.body.canvas.bbox('all')[3], dialog.body.canvas.winfo_height())
        self.assertIn('Long synthetic 中文', dialog.vars['内容'][1].get('1.0', 'end-1c'))
        text = dialog.vars['内容'][1]
        text.event_generate('<MouseWheel>', delta=-120)
        self.pump()
        self.assertGreater(text.yview()[0], 0)

    def test_dialog_confirmation_retains_full_input(self):
        results = []
        dialog = self.dialog()
        dialog.on_ok = results.append
        full = dialog.vars['内容'][1].get('1.0', 'end-1c')
        dialog.ok_button.invoke()
        self.assertEqual(results, [['Synthetic name', full]])
        self.assertTrue(dialog._closed)
        self.assertIsNone(dialog._focus_job)

    def test_dialog_cancel_and_rapid_destroy_cancel_focus_jobs(self):
        jobs = []
        for index in range(6):
            dialog = widgets.Dialog(self.root, 'Synthetic quick close', [('', 'text', False)])
            self.windows.append(dialog)
            jobs.append(dialog._focus_job)
            if index % 2:
                dialog.win.destroy()
            else:
                dialog.cancel_button.invoke()
            self.assertTrue(dialog._closed)
            self.assertIsNone(dialog._focus_job)
        self.pump(.12)
        pending = self.root.tk.splitlist(self.root.tk.call('after', 'info'))
        self.assertTrue(all(job not in pending for job in jobs))

    def test_transform_narrow_actions_wrap_and_body_stacks_without_losing_text(self):
        dialog = self.transform()
        source = dialog.src.get('1.0', 'end-1c')
        dialog._show('Synthetic complete result\n' * 180, None)
        full = dialog.out.get('1.0', 'end-1c')
        dialog.win.geometry('280x340')
        self.pump()
        self.assertEqual(dialog._action_columns, 2)
        self.assertTrue(dialog._narrow)
        for button in dialog.action_buttons:
            self.inside(button, dialog.win)
            self.assertLess(button.winfo_rooty(), dialog.mid.winfo_rooty())
        self.assertEqual(dialog.src.get('1.0', 'end-1c'), source)
        self.assertEqual(dialog.out.get('1.0', 'end-1c'), full)
        dialog.win.geometry('1000x600')
        self.pump()
        self.assertEqual(dialog._action_columns, 4)
        self.assertFalse(dialog._narrow)
        for button in dialog.action_buttons:
            self.inside(button, dialog.win)

    def test_transform_buttons_keep_complete_result_ownership(self):
        from clawboard import transform_dialog
        dialog = self.transform()
        dialog._show('Synthetic result 中文 😀', None)
        copies, saved = [], []
        self.app.ingest = lambda text, manual: saved.append((text, manual))
        with patch.object(transform_dialog, 'clip_write', side_effect=lambda text: copies.append(text)):
            dialog.action_buttons[0].invoke()
        dialog.action_buttons[1].invoke()
        self.assertEqual(copies, ['Synthetic result 中文 😀'])
        self.assertEqual(saved, [('Synthetic result 中文 😀', True)])

    def test_transform_rapid_close_and_destroy_cancel_focus_jobs(self):
        from clawboard.transform_dialog import TransformWindow
        jobs = []
        for index in range(6):
            dialog = TransformWindow(self.app, 'Synthetic quick close')
            self.windows.append(dialog)
            jobs.append(dialog._focus_job)
            if index % 2:
                dialog.win.destroy()
            else:
                dialog.close()
            self.assertTrue(dialog._closed)
            self.assertIsNone(dialog._focus_job)
        self.pump(.12)
        pending = self.root.tk.splitlist(self.root.tk.call('after', 'info'))
        self.assertTrue(all(job not in pending for job in jobs))

    def split(self):
        self.split_group, self.saves = {'items': []}, []
        self.app.cur_group = lambda: self.split_group
        self.app.save = self.saves.append
        self.app.render = lambda: None
        dialog = widgets.SplitDialog(self.app, 'Synthetic 一|Synthetic 二|Synthetic 三')
        dialog.mode.set(dialog.MODES[-1])
        self.windows.append(dialog)
        self.pump()
        return dialog

    def test_split_top_actions_are_native_and_narrow_window_keeps_source(self):
        dialog = self.split()
        text = dialog.txt.get('1.0', 'end-1c')
        dialog.win.geometry('%dx%d' % dialog.win.minsize())
        self.pump()
        for button in dialog.action_buttons:
            self.assertEqual(button.winfo_class(), 'Button')
            self.inside(button, dialog.win)
            self.assertLess(button.winfo_rooty(), dialog.txt.winfo_rooty())
        self.assertEqual(dialog.txt.get('1.0', 'end-1c'), text)
        dialog.cancel()

    def test_split_enter_and_space_each_execute_once(self):
        for sequence in ('<Return>', '<space>'):
            dialog = self.split()
            # Settle the dialog's delayed initial Text focus before selecting
            # the button; slow CI scheduling must not steal it mid-keystroke.
            self.pump(.15)
            button = dialog.action_buttons[0]
            button.focus_force()
            self.pump()
            if button.focus_get() is not button:
                self.skipTest('native keyboard focus is unavailable in this desktop session')
            button.event_generate(sequence)
            if sequence == '<space>':
                button.event_generate('<KeyRelease-space>')
            self.pump(.2)
            self.assertEqual(self.saves, [True])
            self.assertEqual(len(self.split_group['items']), 3)
            self.assertTrue(dialog._closed)
            self.assertIsNone(dialog._focus_job)

    def test_split_quick_cancel_removes_focus_job(self):
        dialog = widgets.SplitDialog(self.app, 'Synthetic quick close')
        self.windows.append(dialog)
        job = dialog._focus_job
        dialog.cancel()
        self.pump(.12)
        self.assertTrue(dialog._closed)
        self.assertIsNone(dialog._focus_job)
        self.assertNotIn(job, self.root.tk.splitlist(self.root.tk.call('after', 'info')))


if __name__ == '__main__':
    unittest.main()
