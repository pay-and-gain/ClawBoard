"""Opt-in Windows desktop integration tests; synthetic clipboard/data only.

Run separately from _t44, with other ClawBoard instances closed. This temporarily
changes the system clipboard and brings an isolated editor to the foreground.
"""
import ctypes
from ctypes import wintypes
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.windows_test_guard import acquire_desktop_test_lease
acquire_desktop_test_lease()
TEMP = tempfile.TemporaryDirectory(prefix='cb-native-')
# Redirect config before importing any adapter that binds its path constants.
from clawboard import config, runtime
config.BASE_DIR = TEMP.name
config.DATA_FILE = str(Path(TEMP.name) / 'ClawBoard数据.json')
config.CRASH_LOG = str(Path(TEMP.name) / 'crash.log')
runtime.NO_SAVE = True

import ClawBoard as C
C.NO_SAVE = True
from clawboard.clipboard import clip_seq, clip_write, clip_write_files
from clawboard.image_win32 import write_clipboard_dib
from clawboard.image import dib_to_png, png_to_dib
from clawboard.services import ClipboardService
from clawboard.win32_snapshot import read_snapshot
from clawboard.hotkey import HiddenWindow
from clawboard.paste_adapter import PasteRequest, TriggerRequest, windows_backend
from clawboard.win32 import (u32, k32, top_hwnd, init_dpi_awareness,
                             WM_TRAY, WM_LBUTTONUP, WM_HOTKEY,
                             sh32, NOTIFYICONDATA, NIM_DELETE, NIM_MODIFY, NIF_TIP)
from clawboard.windows_input import _kbd, _send_batch
from clawboard.windows_layout import keyboard_layout
from clawboard.trigger import TRIGGER_LAYOUT_US, is_supported_trigger_layout


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


DATA_PATHS = [ROOT / 'ClawBoard数据.json',
              Path.home() / 'Desktop' / 'cut' / 'ClawBoard数据.json',
              Path(os.environ['APPDATA']) / 'ClawBoard' / 'ClawBoard数据.json']
BEFORE = {p: digest(p) for p in DATA_PATHS}


def retry(fn, timeout=2):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if fn():
            return True
        time.sleep(.02)
    return False


class NativeClipboard(unittest.TestCase):
    def test_text_and_changed_sequence(self):
        self.assertTrue(retry(lambda: clip_write('native 中文 😀\nsecond line')))
        sequence = clip_seq()
        result = read_snapshot(sequence)
        self.assertEqual(result.status, 'captured')
        self.assertEqual(result.snapshot.text, 'native 中文 😀\nsecond line')
        self.assertEqual(runtime.LAST_WRITE_SEQ, sequence)
        self.assertTrue(retry(lambda: clip_write('newer snapshot')))
        self.assertEqual(read_snapshot(sequence).status, 'retry')

    def test_file_snapshot(self):
        paths = [str(Path(TEMP.name) / '中文 file.txt'), str(Path(TEMP.name) / 'two.txt')]
        for path in paths:
            Path(path).write_text('synthetic', encoding='utf-8')
        self.assertTrue(retry(lambda: clip_write_files(paths)))
        result = read_snapshot(clip_seq())
        self.assertEqual(result.status, 'captured')
        self.assertEqual(result.snapshot.paths, tuple(paths))
        self.assertEqual(runtime.LAST_WRITE_SEQ, clip_seq())

    def test_image_roundtrip(self):
        dib = struct.pack('<IiiHHIIiiII', 40, 2, 2, 1, 32, 0, 16, 0, 0, 0, 0)
        dib += bytes((10, 20, 30, 255, 40, 50, 60, 255)) * 2
        self.assertTrue(retry(lambda: write_clipboard_dib(dib)))
        result = read_snapshot(clip_seq())
        self.assertEqual(result.status, 'captured')
        self.assertEqual(result.snapshot.kind, 'image')
        png, width, height = dib_to_png(result.snapshot.payload)
        restored, rw, rh = png_to_dib(png)
        self.assertEqual((width, height, rw, rh), (2, 2, 2, 2))
        self.assertEqual(dib_to_png(restored)[0], png)
        self.assertEqual(runtime.LAST_WRITE_SEQ, clip_seq())

    def test_busy_clipboard_retries_without_acknowledgement(self):
        self.assertTrue(retry(lambda: clip_write('held snapshot')))
        sequence = clip_seq()
        service = ClipboardService(clip_seq, read_snapshot, initial_sequence=sequence - 1)
        # A NULL owner may reopen from another thread in the same process.
        # A separate process reproduces contention from a real external app.
        code = ('import ctypes,sys,tkinter as tk; u=ctypes.windll.user32; '
                'r=tk.Tk(); r.withdraw(); r.update(); '
                'ok=u.OpenClipboard(ctypes.c_void_p(r.winfo_id())); print(int(ok),flush=True); '
                'sys.stdin.readline(); u.CloseClipboard() if ok else None; r.destroy()')
        holder = subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            self.assertEqual(holder.stdout.readline().strip(), '1')
            self.assertEqual(service.poll().status, 'retry')
            self.assertEqual(service.last_sequence, sequence - 1)
        finally:
            holder.communicate('\n', timeout=3)
        captured = service.poll()
        self.assertEqual(captured.status, 'captured')
        self.assertEqual(captured.snapshot.text, 'held snapshot')
        self.assertTrue(service.complete(sequence))
        self.assertEqual(service.last_sequence, sequence)

    def test_private_marker(self):
        self.assertTrue(retry(lambda: clip_write('private synthetic')))
        self.assertTrue(retry(lambda: u32.OpenClipboard(None)))
        try:
            fmt = u32.RegisterClipboardFormatW('ExcludeClipboardContentFromMonitorProcessing')
            handle = k32.GlobalAlloc(2, 4)
            self.assertTrue(handle)
            pointer = k32.GlobalLock(handle)
            self.assertTrue(pointer)
            ctypes.memmove(pointer, struct.pack('<I', 1), 4)
            k32.GlobalUnlock(handle)
            self.assertTrue(u32.SetClipboardData(fmt, handle))
        finally:
            u32.CloseClipboard()
        self.assertEqual(read_snapshot(clip_seq()).status, 'private')
        self.assertEqual(read_snapshot(clip_seq(), private=False).status, 'captured')


class NativeDesktop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tkinter as tk
        init_dpi_awareness()
        cls.root = tk.Tk()
        cls.root.title('ClawBoard isolated native editor')
        cls.root.geometry('500x220+100+100')
        cls.root.update()
        cls.hwnd = top_hwnd(cls.root)
        cls.edit = u32.CreateWindowExW(0, 'EDIT', '', 0x50000000 | 0x00800000 | 4,
                                     10, 10, 460, 150, cls.hwnd, None,
                                     k32.GetModuleHandleW(None), None)
        if not cls.edit:
            raise RuntimeError('native Edit creation failed')
        u32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
        u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u32.SetFocus.argtypes = [wintypes.HWND]
        u32.SetFocus.restype = wintypes.HWND
        cls.pool = ThreadPoolExecutor(max_workers=1)

    @classmethod
    def tearDownClass(cls):
        cls.pool.shutdown(wait=True)
        cls.root.destroy()

    def run_editor(self, operation, initial=''):
        u32.SetWindowTextW(self.edit, initial)
        u32.SetForegroundWindow(self.hwnd)
        u32.SetFocus(self.edit)
        # Move the caret to the end, as it would be after typing a trigger.
        u32.SendMessageW(self.edit, 0x00B1, len(initial), len(initial))
        self.root.update()
        future = self.pool.submit(operation)
        end = time.monotonic() + 4
        while not future.done() and time.monotonic() < end:
            self.root.update()
            time.sleep(.005)
        self.assertTrue(future.done(), 'paste worker timed out')
        result = future.result()
        self.root.update()
        value = ctypes.create_unicode_buffer(1024)
        u32.GetWindowTextW(self.edit, value, 1024)
        return result, value.value

    def deliver(self, backend, text):
        result, value = self.run_editor(lambda: backend.perform(
            PasteRequest(1, text=text, target=self.hwnd, should_paste=True)))
        self.assertTrue(result.copied)
        self.assertTrue(result.pasted, result.error)
        self.assertEqual(value, text)

    def test_standard_edit_message_delivery(self):
        backend = windows_backend()
        self.deliver(backend, 'WM_PASTE 中文 text')

    def test_focus_and_sendinput_delivery(self):
        backend = windows_backend()
        backend.can_message = lambda target: False
        self.deliver(backend, 'SendInput 中文 text')

    def test_trigger_replacement_batch_reaches_native_edit(self):
        backend = windows_backend()
        # This tests real SendInput delivery, with only the layout port synthetic.
        # Actual target layouts and physical IME input are verified separately.
        backend.read_layout = lambda focus: TRIGGER_LAYOUT_US
        request = TriggerRequest('abc', '触发词完整内容', self.hwnd, self.edit,
                                 TRIGGER_LAYOUT_US)
        result, value = self.run_editor(lambda: backend.perform_trigger(request), 'abc ')
        self.assertTrue(result.pasted, result.error)
        self.assertEqual(value, request.replacement)

    def test_trigger_write_failure_preserves_original_input(self):
        backend = windows_backend()
        backend.read_layout = lambda focus: TRIGGER_LAYOUT_US
        backend.write_text = lambda text: False
        request = TriggerRequest('abc', 'replacement', self.hwnd, self.edit,
                                 TRIGGER_LAYOUT_US)
        result, value = self.run_editor(lambda: backend.perform_trigger(request), 'abc ')
        self.assertFalse(result.copied)
        self.assertFalse(result.pasted)
        self.assertIn('未替换', result.error)
        self.assertEqual(value, 'abc ')

    def test_trigger_wrong_focus_preserves_original_input(self):
        backend = windows_backend()
        backend.read_layout = lambda focus: TRIGGER_LAYOUT_US
        request = TriggerRequest('abc', 'replacement', self.hwnd, self.hwnd,
                                 TRIGGER_LAYOUT_US)
        result, value = self.run_editor(lambda: backend.perform_trigger(request), 'abc ')
        self.assertFalse(result.copied)
        self.assertEqual(value, 'abc ')

    def test_trigger_real_unsupported_layout_preserves_original_input(self):
        layout = keyboard_layout(self.edit)
        self.assertTrue(layout, 'target thread layout query failed')
        if is_supported_trigger_layout(layout):
            self.skipTest('current native editor uses supported US layout')
        backend = windows_backend()
        backend.write_text = lambda text: self.fail('unsupported layout wrote clipboard')
        request = TriggerRequest('nihao', 'replacement', self.hwnd, self.edit, layout)
        sequence = clip_seq()
        result, value = self.run_editor(lambda: backend.perform_trigger(request), 'KEEP| 你好')
        self.assertFalse(result.copied)
        self.assertFalse(result.pasted)
        self.assertEqual(value, 'KEEP| 你好')
        self.assertEqual(clip_seq(), sequence)

    def test_hidden_window_recreated_in_same_process(self):
        for _ in range(2):
            tray = []
            hidden = HiddenWindow(lambda: None, tray.append)
            hidden.start()
            try:
                self.assertTrue(hidden.ready.wait(3))
                self.assertTrue(hidden.hwnd)
                u32.PostMessageW(hidden.hwnd, WM_TRAY, 0, WM_LBUTTONUP)
                self.assertTrue(retry(lambda: tray == ['left']))
            finally:
                hidden.stop()
                hidden.join(3)
            self.assertFalse(hidden.is_alive())

    def test_keyboard_and_mouse_hooks_install_and_stop(self):
        from clawboard import windows_hooks
        try:
            self.assertTrue(windows_hooks.start_keyboard_hook(
                lambda ch: None, lambda: None, on_reset=lambda: None))
            self.assertIsNotNone(windows_hooks._hook_thread)
            self.assertTrue(windows_hooks._hook_thread.is_alive())
        finally:
            windows_hooks.stop_keyboard_hook()
        self.assertIsNone(windows_hooks._hook_thread)

    def test_hidden_top_level_tray_restores_own_removed_icon(self):
        hidden = HiddenWindow(lambda: None, lambda event: None)
        hidden.start()
        try:
            self.assertTrue(hidden.ready.wait(3))
            self.assertTrue(hidden.hwnd)
            self.assertTrue(hidden._taskbar_created)
            enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            u32.EnumWindows.argtypes = [enum_proc, wintypes.LPARAM]
            u32.EnumWindows.restype = wintypes.BOOL
            u32.IsWindowVisible.argtypes = [wintypes.HWND]
            u32.IsWindowVisible.restype = wintypes.BOOL
            handles = []
            callback = enum_proc(lambda hwnd, lp: handles.append(int(hwnd)) or True)
            self.assertTrue(u32.EnumWindows(callback, 0))
            self.assertIn(hidden.hwnd, handles)
            self.assertFalse(u32.IsWindowVisible(hidden.hwnd))
            self.assertTrue(hidden.tray_add())
            icon = hidden._icon
            record = NOTIFYICONDATA()
            record.cbSize, record.hWnd, record.uID = ctypes.sizeof(record), hidden.hwnd, 1
            record.uFlags, record.szTip = NIF_TIP, 'ClawBoard isolated tray recovery test'
            # Remove only our icon. This is not an Explorer restart.
            self.assertTrue(sh32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(record)))
            self.assertFalse(sh32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(record)))

            def notify():
                result = ctypes.c_size_t()
                self.assertTrue(u32.SendMessageTimeoutW(hidden.hwnd, hidden._taskbar_created,
                    0, 0, 2, 500, ctypes.byref(result)))

            notify()
            self.assertTrue(sh32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(record)))
            self.assertEqual(hidden._icon, icon)
            hidden.tray_del()
            notify()
            self.assertFalse(sh32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(record)))
        finally:
            hidden.stop()
            hidden.join(3)
        self.assertFalse(hidden.is_alive())

    def test_hidden_window_listener_hotkey_and_tray(self):
        changed, hotkey, tray = threading.Event(), threading.Event(), []
        hidden = HiddenWindow(hotkey.set, tray.append, changed.set)
        hidden.start()
        try:
            self.assertTrue(hidden.ready.wait(3))
            self.assertTrue(hidden.hwnd)
            self.assertTrue(hidden.clipboard_listener)
            self.assertTrue(hidden.reg_hotkey(2 | 1 | 4, 0x7B))  # Ctrl+Alt+Shift+F12
            # Exercise the OS RegisterHotKey route, not just a fabricated message.
            keys = [0x11, 0x12, 0x10, 0x7B]
            self.assertTrue(_send_batch([_kbd(vk) for vk in keys] +
                                       [_kbd(vk, up=True) for vk in reversed(keys)]))
            self.assertTrue(hotkey.wait(2))
            self.assertTrue(hidden.tray_add())
            self.assertTrue(retry(lambda: clip_write('listener event')))
            self.assertTrue(changed.wait(2))
            # Dispatch contract is tested here; physical hotkey input is separate.
            u32.PostMessageW(hidden.hwnd, WM_TRAY, 0, WM_LBUTTONUP)
            self.assertTrue(retry(lambda: tray == ['left']))
            tid = u32.GetWindowThreadProcessId(hidden.hwnd, None)
            u32.PostThreadMessageW(tid, WM_HOTKEY, hidden.hotkey_id, 0)
            self.assertTrue(hotkey.wait(2))
        finally:
            hidden.unreg_hotkey()
            hidden.tray_del()
            hidden.stop()
            hidden.join(3)
        self.assertFalse(hidden.is_alive())


if __name__ == '__main__':
    try:
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    finally:
        unchanged = all(digest(p) == before for p, before in BEFORE.items())
        print('Real data hashes unchanged:', unchanged)
        print('NO_SAVE temp JSON absent:', not Path(config.DATA_FILE).exists())
        TEMP.cleanup()
    sys.exit(0 if result.wasSuccessful() and unchanged else 1)
