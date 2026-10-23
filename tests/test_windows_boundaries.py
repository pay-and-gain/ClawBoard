# -*- coding: utf-8 -*-
"""Win32 boundary contracts with fake DLLs; no Windows layout or GUI claims.

Imports the real adapter modules in an isolated package. Native calls are replaced
by a message queue, so thread ownership, cancellation, timeouts and facade aliases
can be checked on Linux without importing or constructing the application.
"""
import ast
import ctypes
import importlib
import pathlib
import queue
import sys
import threading
import types
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]


class NativeFunction:
    def __init__(self, name):
        self.name = name
        self.calls = []
        self.impl = lambda *args: 0
    def __call__(self, *args):
        self.calls.append((threading.get_ident(), args))
        return self.impl(*args)


class NativeLibrary:
    def __init__(self):
        self.functions = {}
    def __getattr__(self, name):
        return self.functions.setdefault(name, NativeFunction(name))


class WindowsHarness:
    def __init__(self):
        self.stack = ExitStack()
        self.libraries = {}
        self.queues = {}
        self.pump_entered = threading.Event()
        self.callback = None
        self.module = None
        package = types.ModuleType('clawboard')
        package.__path__ = [str(ROOT / 'clawboard')]
        config = types.ModuleType('clawboard.config')
        config.APP_NAME, config.BASE_DIR = 'ClawBoardTest', '/tmp'
        registry = types.ModuleType('winreg')
        registry.HKEY_CURRENT_USER, registry.KEY_SET_VALUE, registry.REG_SZ = 0, 2, 1
        # Remove already imported adapters inside this isolated module dictionary;
        # their original objects are restored when the patch closes.
        modules = {k: v for k, v in sys.modules.items()
                   if not k.startswith('clawboard.windows_') and k != 'clawboard.win32'}
        modules.update({'clawboard': package, 'clawboard.config': config, 'winreg': registry})
        self.stack.enter_context(patch.dict(sys.modules, modules, clear=True))
        self.stack.enter_context(patch.object(ctypes, 'WinDLL', self.library, create=True))
        self.stack.enter_context(patch.object(ctypes, 'WINFUNCTYPE', ctypes.CFUNCTYPE, create=True))
        self.stack.enter_context(patch.object(ctypes, 'get_last_error', lambda: 0, create=True))
        windll = types.SimpleNamespace(dwmapi=self.library('dwmapi'), user32=self.library('user32'),
                                      gdi32=self.library('gdi32'), shcore=self.library('shcore'))
        self.stack.enter_context(patch.object(ctypes, 'windll', windll, create=True))
        self.module = importlib.import_module('clawboard.win32')
        self.u32, self.k32 = self.module.u32, self.module.k32
        self.k32.GetCurrentThreadId.impl = threading.get_ident
        self.k32.GetModuleHandleW.impl = lambda name: 1
        self.u32.PeekMessageW.impl = self.peek
        self.u32.GetMessageW.impl = self.get_message
        self.u32.PostThreadMessageW.impl = self.post_thread_message
        self.u32.SetWindowsHookExW.impl = self.install
        self.u32.UnhookWindowsHookEx.impl = lambda handle: True

    def library(self, name, **kwargs):
        return self.libraries.setdefault(name, NativeLibrary())

    def peek(self, *args):
        self.queues.setdefault(threading.get_ident(), queue.Queue())
        return 0

    def install(self, kind, callback, module, tid):
        self.callback = callback
        return 0x123456781234

    def get_message(self, *args):
        self.pump_entered.set()
        value = self.queues[threading.get_ident()].get(timeout=2)
        if value == self.module.WM_QUIT:
            return 0
        if isinstance(value, tuple) and value[0] == 'key':
            self.call_key(self.callback, value[1])
        return 1

    def call_key(self, callback, vk):
        record = self.module.KBDLLHOOKSTRUCT()
        record.vkCode = vk
        return callback(0, self.module.WM_KEYDOWN, ctypes.addressof(record))

    def post_thread_message(self, tid, message, wparam, lparam):
        target = self.queues.get(tid)
        if target is None:
            return False
        target.put(message)
        return True

    def close(self):
        try:
            if self.module is not None:
                self.module.stop_keyboard_hook()
        finally:
            self.stack.close()


class WindowsBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.win = WindowsHarness()
        self.addCleanup(self.win.close)
        self.w = self.win.module

    def test_legacy_exports_resolve_to_single_owners(self):
        for name in self.w._OWNERS:
            self.assertTrue(hasattr(self.w, name), name)
            self.assertIn(name, dir(self.w))
        api = self.w.windows_api
        self.assertIs(self.w.u32, api.u32)
        self.assertIs(self.w.shell32, self.w.sh32)
        self.assertIs(self.w.MUTEX, self.w.windows_system.MUTEX)
        for name in ('_pid_integrity', '_focus_class_name', '_kbd', '_INPUTUNION', '_dwm', '_hook'):
            self.assertTrue(hasattr(self.w, name), name)

    def test_facade_geometry_monkeypatch_updates_real_call_path(self):
        self.w.monitors = lambda: [(0, 0, 100, 100), (100, 0, 200, 100)]
        self.assertEqual(self.w.visible_ratio(50, 0, 100, 100), 1.0)
        self.w.window_rect = lambda hwnd: (100, 0, 200, 100)
        self.w.monitor_rect_of = lambda hwnd: (100, 0, 200, 100)
        self.w.class_name_of = lambda hwnd: 'editor'
        self.w.is_zoomed = lambda hwnd: False
        self.assertTrue(self.w.is_fullscreen_window(999))

    def test_facade_forwards_dependency_rebindings_between_adapters(self):
        fake = lambda root: 0x123456789
        self.w.top_hwnd = fake
        self.assertIs(self.w.windows_geometry.top_hwnd, fake)
        self.assertIs(self.w.windows_effects.top_hwnd, fake)
        replacement = object()
        self.w.u32 = replacement
        for module in self.w._MODULES:
            if 'u32' in vars(module):
                self.assertIs(module.u32, replacement)

    def test_nested_patch_object_restores_canonical_geometry_export(self):
        original = self.w.monitors
        outer = Mock(return_value=[(0, 0, 100, 100)])
        inner = Mock(return_value=[(0, 0, 200, 100)])
        with patch.object(self.w, 'monitors', outer):
            self.assertIs(self.w.windows_geometry.monitors, outer)
            self.assertEqual(self.w.visible_ratio(0, 0, 200, 100), 0.5)
            with patch.object(self.w, 'monitors', inner):
                self.assertIs(self.w.monitors, inner)
                self.assertEqual(self.w.visible_ratio(0, 0, 200, 100), 1.0)
            self.assertIs(self.w.monitors, outer)
            self.assertIs(self.w.windows_geometry.monitors, outer)
        self.assertIs(self.w.monitors, original)
        self.assertIs(self.w.windows_geometry.monitors, original)

    def test_nested_patch_object_restores_cross_adapter_dependency(self):
        original = self.w.top_hwnd
        outer, inner = Mock(return_value=10), Mock(return_value=20)
        with patch.object(self.w, 'top_hwnd', outer):
            with patch.object(self.w, 'top_hwnd', inner):
                self.assertIs(self.w.windows_geometry.top_hwnd, inner)
                self.assertIs(self.w.windows_effects.top_hwnd, inner)
            self.assertIs(self.w.windows_geometry.top_hwnd, outer)
            self.assertIs(self.w.windows_effects.top_hwnd, outer)
        self.assertIs(self.w.top_hwnd, original)
        self.assertIs(self.w.windows_geometry.top_hwnd, original)
        self.assertIs(self.w.windows_effects.top_hwnd, original)
        self.assertNotIsInstance(self.w.top_hwnd, Mock)

    def test_legacy_shared_configuration_rebinding_reaches_adapter(self):
        self.w.BASE_DIR = '/tmp/other-isolated-directory'
        self.assertEqual(self.w.windows_system.BASE_DIR, '/tmp/other-isolated-directory')
        clock = types.SimpleNamespace(time=lambda: 123)
        self.w.time = clock
        self.assertIs(self.w.windows_focus.time, clock)
        self.assertIs(self.w.windows_system.time, clock)

    def test_timeout_abi_uses_pointer_sized_result(self):
        function = self.w.u32.SendMessageTimeoutW
        self.assertIs(function.restype, ctypes.c_ssize_t)
        self.assertIs(function.argtypes[-1]._type_, ctypes.c_size_t)
        self.assertEqual(self.w.PASTE_MESSAGE_TIMEOUT_MS, 500)
        self.assertEqual(self.w.SMTO_ABORTIFHUNG, 2)

    def test_paste_message_treats_zero_target_result_as_delivered(self):
        self.w.target_focus_hwnd = lambda hwnd: 0x123456789
        # The API reports success although the target edit control returned zero.
        self.win.u32.SendMessageTimeoutW.impl = lambda *args: 1
        self.assertTrue(self.w.paste_message(1))
        _, args = self.win.u32.SendMessageTimeoutW.calls[-1]
        self.assertEqual(args[:6], (0x123456789, self.w.WM_PASTE, 0, 0,
                                   self.w.SMTO_ABORTIFHUNG, 500))

    def test_paste_message_handles_timeout_invalid_target_and_native_error(self):
        self.w.target_focus_hwnd = lambda hwnd: 10
        self.win.u32.SendMessageTimeoutW.impl = lambda *args: 0
        self.assertFalse(self.w.paste_message(1))
        def fail(*args):
            raise OSError('native target unavailable')
        self.win.u32.SendMessageTimeoutW.impl = fail
        self.assertFalse(self.w.paste_message(1))
        self.w.target_focus_hwnd = lambda hwnd: 0
        self.assertFalse(self.w.paste_message(0))
        self.assertEqual(len(self.win.u32.SendMessageTimeoutW.calls), 2)

    def test_hook_install_pump_and_unhook_use_same_worker_thread(self):
        caller = threading.get_ident()
        self.assertTrue(self.w.start_keyboard_hook(lambda ch: None, lambda: None))
        thread = self.w._hook_thread
        self.assertTrue(thread.daemon)
        self.assertNotEqual(thread.ident, caller)
        self.assertEqual(self.w._hook_tid, thread.ident)
        # Installation readiness precedes the first pump iteration. Waiting for
        # this fake-native entry avoids stopping a correctly initialized worker
        # before it has ever needed to call GetMessageW.
        self.assertTrue(self.win.pump_entered.wait(2))
        self.w.stop_keyboard_hook()
        self.assertFalse(thread.is_alive())
        install_tid = self.win.u32.SetWindowsHookExW.calls[0][0]
        pump_tid = self.win.u32.GetMessageW.calls[0][0]
        unhook_tid = self.win.u32.UnhookWindowsHookEx.calls[0][0]
        self.assertEqual((install_tid, pump_tid, unhook_tid), (thread.ident,) * 3)
        self.assertEqual(self.win.u32.PostQuitMessage.calls, [])
        _, quit_args = self.win.u32.PostThreadMessageW.calls[0]
        self.assertEqual(quit_args[:2], (thread.ident, self.w.WM_QUIT))
        self.assertIsNone(self.w._hook)
        self.assertIsNone(self.w._hook_thread)

    def test_hook_callback_cancellation_and_idempotent_start_stop(self):
        entered = threading.Event()
        seen = []
        def receive(char):
            seen.append(char)
            entered.set()
        self.assertTrue(self.w.start_keyboard_hook(receive, lambda: None))
        self.assertTrue(self.w.start_keyboard_hook(receive, lambda: None))
        self.assertEqual(len(self.win.u32.SetWindowsHookExW.calls), 1)
        callback, tid = self.win.callback, self.w._hook_tid
        self.win.queues[tid].put(('key', 0x41))
        self.assertTrue(entered.wait(1))
        self.assertEqual(seen, ['a'])
        self.w.stop_keyboard_hook()
        self.win.call_key(callback, 0x42)
        self.assertEqual(seen, ['a'])
        self.w.stop_keyboard_hook()
        self.assertEqual(len(self.win.u32.UnhookWindowsHookEx.calls), 1)

    def test_hook_install_failure_returns_false(self):
        self.win.u32.SetWindowsHookExW.impl = lambda *args: 0
        self.assertFalse(self.w.start_keyboard_hook(lambda ch: None, lambda: None))
        self.w.stop_keyboard_hook()
        self.assertEqual(self.win.u32.UnhookWindowsHookEx.calls, [])

    def test_hook_native_initialization_exception_returns_false(self):
        def fail(*args):
            raise OSError('hook initialization failed')
        self.win.u32.SetWindowsHookExW.impl = fail
        self.assertFalse(self.w.start_keyboard_hook(lambda ch: None, lambda: None))
        self.w.stop_keyboard_hook()
        self.assertIsNone(self.w._hook)

    def test_hook_initialization_wait_is_bounded_and_late_install_is_cleaned(self):
        release = threading.Event()
        def install(*args):
            release.wait(1)
            return 123
        self.win.u32.SetWindowsHookExW.impl = install
        self.w.HOOK_START_TIMEOUT = 0.01
        self.assertFalse(self.w.start_keyboard_hook(lambda ch: None, lambda: None))
        release.set()
        self.w.stop_keyboard_hook()
        self.assertEqual(len(self.win.u32.UnhookWindowsHookEx.calls), 1)
        self.assertIsNone(self.w._hook_thread)

    def test_hook_getmessage_error_still_unhooks(self):
        gate = threading.Event()
        self.win.u32.GetMessageW.impl = lambda *args: gate.wait(1) and -1
        self.assertTrue(self.w.start_keyboard_hook(lambda ch: None, lambda: None))
        thread = self.w._hook_thread
        gate.set()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(self.win.u32.UnhookWindowsHookEx.calls), 1)
        self.assertIsNone(self.w._hook)

    def test_adapters_are_small_and_never_depend_on_compatibility_facade(self):
        for path in (ROOT / 'clawboard').glob('windows_*.py'):
            self.assertLessEqual(len(path.read_text(encoding='utf-8').splitlines()), 800, str(path))
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    self.assertNotEqual(node.module, 'clawboard.win32', str(path))
                if isinstance(node, ast.Import):
                    self.assertNotIn('clawboard.win32', [n.name for n in node.names], str(path))


if __name__ == '__main__':
    unittest.main(verbosity=2)
