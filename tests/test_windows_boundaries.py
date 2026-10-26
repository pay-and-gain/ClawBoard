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
        self.mouse_callback = None
        self.module = None
        package = types.ModuleType('clawboard')
        package.__path__ = [str(ROOT / 'clawboard')]
        config = types.ModuleType('clawboard.config')
        config.APP_NAME, config.BASE_DIR = 'ClawBoardTest', '/tmp'
        config.ICON_FILE = '/tmp/clawboard-test.ico'
        config.UI_ASSET_DIR = '/tmp/clawboard-ui-assets'
        config.BAR_H, config.MIN_W, config.MIN_H, config.RESIZE_ZONE = 34, 280, 340, 6
        config.UI_SCALE_LEVELS, config.scaled = (0.5, 1.0, 1.5), int
        config.UI_SCALE, config.DPI_SCALE = 1.0, 1.0
        registry = types.ModuleType('winreg')
        registry.HKEY_CURRENT_USER, registry.KEY_SET_VALUE, registry.REG_SZ = 0, 2, 1
        # Remove already imported adapters inside this isolated module dictionary;
        # their original objects are restored when the patch closes.
        modules = {k: v for k, v in sys.modules.items()
                   if not k.startswith('clawboard.windows_') and
                   k not in ('clawboard.win32', 'clawboard.hotkey', 'clawboard.app_geometry',
                             'clawboard.tk_dpi', 'clawboard.runtime')}
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
        if kind == self.module.WH_KEYBOARD_LL:
            self.callback = callback
            return 0x123456781234
        self.mouse_callback = callback
        return 0x123456781235

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

    def test_tray_timeout_version_union_keeps_native_field_offsets(self):
        record = self.w.NOTIFYICONDATA
        self.assertEqual(record.uTimeout.offset, record.uVersion.offset)
        self.assertEqual(record.szInfoTitle.offset,
                         record.uTimeout.offset + ctypes.sizeof(ctypes.c_uint))
        info = record()
        info.uTimeout = 6000
        self.assertEqual(info.uVersion, 6000)
        if sys.platform == 'win32':
            self.assertEqual(ctypes.sizeof(record), 976 if ctypes.sizeof(ctypes.c_void_p) == 8 else 956)
        self.assertEqual(self.w.u32.DestroyWindow.argtypes, [ctypes.wintypes.HWND])
        self.assertEqual(self.w.u32.UnregisterClassW.argtypes,
                         [ctypes.wintypes.LPCWSTR, ctypes.wintypes.HINSTANCE])

    def test_geometry_primary_monitor_excludes_left_and_top_boundary(self):
        geometry = importlib.import_module('clawboard.app_geometry')
        geometry.monitors = lambda: [(-1920, 0, 0, 1080), (0, -1080, 1920, 0),
                                    (0, 0, 1920, 1080)]
        self.assertEqual(geometry.GeometryMixin.primary_monitor(), (0, 0, 1920, 1080))
        panel = geometry.GeometryMixin()
        panel.root = types.SimpleNamespace(winfo_x=lambda: -100, winfo_y=lambda: 100,
                                          winfo_width=lambda: 200, winfo_height=lambda: 100)
        self.assertEqual(panel._window_monitor(), (0, 0, 1920, 1080))

    def prepare_hidden_window(self):
        classes, windows = {}, {}
        def register(pointer):
            record = pointer._obj
            if record.lpszClassName in classes:
                return 0
            classes[record.lpszClassName] = record.lpfnWndProc
            return 1
        def create(style, name, title, *args):
            tid = threading.get_ident()
            self.win.queues[tid] = queue.Queue()
            hwnd = 0x123456780000 + len(windows) + 1
            windows[hwnd] = (tid, classes[name])
            return hwnd
        def post(hwnd, message, wp, lp):
            tid, _ = windows[hwnd]
            self.win.queues[tid].put((hwnd, message, wp, lp))
            return 1
        def get(pointer, *args):
            value = self.win.queues[threading.get_ident()].get(timeout=2)
            if value == self.w.WM_QUIT:
                return 0
            record = pointer._obj
            record.hWnd, record.message, record.wParam, record.lParam = value
            return 1
        def dispatch(pointer):
            record = pointer._obj
            return windows[record.hWnd][1](record.hWnd, record.message, record.wParam, record.lParam)
        def destroy(hwnd):
            windows[hwnd][1](hwnd, self.w.WM_DESTROY, 0, 0)
            return 1
        def unregister(name, instance):
            classes.pop(name)
            return 1
        self.win.u32.RegisterClassW.impl = register
        self.win.u32.CreateWindowExW.impl = create
        self.win.u32.PostMessageW.impl = post
        self.win.u32.GetMessageW.impl = get
        self.win.u32.DispatchMessageW.impl = dispatch
        self.win.u32.DestroyWindow.impl = destroy
        self.win.u32.PostQuitMessage.impl = lambda code: self.win.queues[threading.get_ident()].put(self.w.WM_QUIT)
        self.win.u32.UnregisterClassW.impl = unregister
        self.win.u32.AddClipboardFormatListener.impl = lambda hwnd: 1
        self.win.u32.RegisterHotKey.impl = lambda *args: 1
        return importlib.import_module('clawboard.hotkey').HiddenWindow, classes

    def test_hidden_window_repeated_start_routes_callbacks_and_cleans_owner_resources(self):
        hidden_class, classes = self.prepare_hidden_window()
        caller = threading.get_ident()
        seen = []
        for value in ('first', 'second'):
            event = threading.Event()
            def tray(kind, value=value):
                seen.append((value, kind))
                event.set()
            hidden = hidden_class(lambda: None, tray, lambda: None)
            hidden.start()
            try:
                self.assertTrue(hidden.ready.wait(2))
                self.assertTrue(hidden.hwnd)
                self.assertTrue(hidden.reg_hotkey(2, 0x41))
                self.win.u32.PostMessageW(hidden.hwnd, self.w.WM_TRAY, 0, self.w.WM_LBUTTONUP)
                self.assertTrue(event.wait(1))
            finally:
                hidden.stop()
                hidden.join(2)
            self.assertFalse(hidden.is_alive())
            self.assertIsNone(hidden.hwnd)
            self.assertFalse(hidden.clipboard_listener)
            self.assertFalse(hidden.hotkey_ok)
            self.assertEqual(classes, {})
            for name in ('DestroyWindow', 'UnregisterClassW', 'RemoveClipboardFormatListener'):
                self.assertEqual(self.win.u32.functions[name].calls[-1][0], hidden.ident)
                self.assertNotEqual(hidden.ident, caller)
        self.assertEqual(seen, [('first', 'left'), ('second', 'left')])

    def test_hidden_window_stop_before_start_does_not_leave_native_window(self):
        hidden_class, classes = self.prepare_hidden_window()
        hidden = hidden_class(lambda: None, lambda action: None)
        hidden.stop()
        hidden.start()
        hidden.join(2)
        self.assertFalse(hidden.is_alive())
        self.assertTrue(hidden.ready.is_set())
        self.assertEqual(classes, {})
        self.assertEqual(self.win.u32.CreateWindowExW.calls, [])

    def test_taskbar_created_restores_only_enabled_tray_without_reloading_icon(self):
        hidden_class, classes = self.prepare_hidden_window()
        module = importlib.import_module('clawboard.hotkey')
        self.win.u32.RegisterWindowMessageW.impl = lambda name: 0xC123
        self.win.u32.LoadImageW.impl = lambda *args: 0x123456789
        icons = set()
        def notify(command, pointer):
            record = pointer._obj
            identity = (record.hWnd, record.uID)
            if command == module.NIM_ADD:
                if identity in icons:
                    return 0
                icons.add(identity)
                return 1
            if command == module.NIM_DELETE:
                icons.discard(identity)
                return 1
            return 0
        self.win.module.sh32.Shell_NotifyIconW.impl = notify
        received = threading.Event()
        hidden = hidden_class(lambda: None, lambda action: received.set())
        def send_broadcast_then_barrier():
            received.clear()
            self.win.u32.PostMessageW(hidden.hwnd, 0xC123, 0, 0)
            self.win.u32.PostMessageW(hidden.hwnd, self.w.WM_TRAY, 0, self.w.WM_LBUTTONUP)
            self.assertTrue(received.wait(1))
        with patch.object(module.os.path, 'exists', return_value=True):
            hidden.start()
            try:
                self.assertTrue(hidden.ready.wait(2))
                self.assertTrue(hidden.hwnd)
                # A real broadcast reaches unshown top-level windows, not HWND_MESSAGE.
                self.assertIsNone(self.win.u32.CreateWindowExW.calls[-1][1][8])
                self.assertEqual(self.win.u32.RegisterWindowMessageW.calls[-1][1], ('TaskbarCreated',))
                send_broadcast_then_barrier()
                self.assertEqual(icons, set(), 'broadcast enabled an unused tray')
                self.assertTrue(hidden.tray_add())
                identity = (hidden.hwnd, 1)
                self.assertEqual(icons, {identity})
                icons.clear()  # Fake Explorer lost its notification area state.
                send_broadcast_then_barrier()
                self.assertEqual(icons, {identity})
                send_broadcast_then_barrier()
                self.assertEqual(icons, {identity}, 'duplicate broadcast duplicated an icon')
                self.assertEqual(len(self.win.u32.LoadImageW.calls), 1)
                hidden.tray_del()
                send_broadcast_then_barrier()
                self.assertEqual(icons, set(), 'broadcast restored a disabled tray')
                self.assertFalse(hidden._tray_enabled)
            finally:
                hidden.stop()
                hidden.join(2)
        self.assertFalse(hidden.is_alive())
        self.assertEqual(classes, {})
        self.assertIsNone(hidden._icon)
        self.assertEqual(len(self.win.u32.DestroyIcon.calls), 1)

    def test_taskbar_created_retries_failed_initial_add_until_explicitly_disabled(self):
        hidden_class, _ = self.prepare_hidden_window()
        module = importlib.import_module('clawboard.hotkey')
        self.win.u32.RegisterWindowMessageW.impl = lambda name: 0xC123
        self.win.u32.LoadImageW.impl = lambda *args: 123
        adds, recovered, barrier = [], threading.Event(), threading.Event()
        def notify(command, pointer):
            if command == module.NIM_ADD:
                adds.append(pointer._obj.hWnd)
                if len(adds) == 1:
                    return 0  # Explorer is unavailable during the first attempt.
                recovered.set()
            return 1
        self.win.module.sh32.Shell_NotifyIconW.impl = notify
        hidden = hidden_class(lambda: None, lambda action: barrier.set())
        with patch.object(module.os.path, 'exists', return_value=True):
            hidden.start()
            try:
                self.assertTrue(hidden.ready.wait(2))
                self.assertFalse(hidden.tray_add())
                self.assertTrue(hidden._tray_enabled)
                self.win.u32.PostMessageW(hidden.hwnd, 0xC123, 0, 0)
                self.assertTrue(recovered.wait(1))
                self.assertEqual(adds, [hidden.hwnd, hidden.hwnd])
                hidden.tray_del()
                self.win.u32.PostMessageW(hidden.hwnd, 0xC123, 0, 0)
                self.win.u32.PostMessageW(hidden.hwnd, self.w.WM_TRAY, 0, self.w.WM_LBUTTONUP)
                self.assertTrue(barrier.wait(1))
                self.assertEqual(len(adds), 2)
            finally:
                hidden.stop()
                hidden.join(2)
        self.assertFalse(hidden._tray_enabled)
        self.assertFalse(hidden.tray_add(), 'a stopped window accepted a new enable request')
        self.assertFalse(hidden._tray_enabled)

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
