"""Input failure contracts with fake DLLs/ports; never touch the desktop."""
import ast
import ctypes
import importlib
import pathlib
import sys
import threading
import types
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clawboard.paste_adapter import PasteRequest, TriggerRequest
from clawboard.trigger import TriggerEngine, TRIGGER_LAYOUT_US, is_supported_trigger_layout
from test_paste_adapter import FakeApp, backend
from test_windows_boundaries import WindowsHarness


def trigger_backend(**changes):
    values = dict(foreground=lambda: 10, target_focus=lambda target: 11,
                  replace_keys=lambda count: True, current_sequence=lambda: 5,
                  read_layout=lambda focus: TRIGGER_LAYOUT_US)
    values.update(changes)
    return backend(**values)


class InputInjectionTests(unittest.TestCase):
    def setUp(self):
        self.win = WindowsHarness()
        self.addCleanup(self.win.close)
        self.w = self.win.module
        self.batches = []
        def send(count, pointer, size):
            records = ctypes.cast(pointer, ctypes.POINTER(self.w.INPUT))
            self.batches.append([(records[i].u.ki.wVk, records[i].u.ki.dwFlags)
                                 for i in range(count)])
            return count
        self.win.u32.SendInput.impl = send

    def test_ctrl_v_is_one_complete_batch(self):
        self.assertTrue(self.w.send_ctrl_v())
        self.assertEqual(self.batches, [[(self.w.VK_CONTROL, 0), (self.w.VK_V, 0),
            (self.w.VK_V, self.w.KEYEVENTF_KEYUP),
            (self.w.VK_CONTROL, self.w.KEYEVENTF_KEYUP)]])

    def test_send_input_zero_and_partial_counts_are_failures(self):
        for count in (0, 2):
            with self.subTest(count=count):
                self.win.u32.SendInput.impl = lambda *args: count
                self.assertFalse(self.w.send_ctrl_v())
        self.win.u32.SendInput.impl = lambda *args: 0
        self.assertFalse(self.w.send_key(self.w.VK_V, gap=0))

    def test_native_exception_is_failure(self):
        def fail(*args):
            raise OSError('blocked injection')
        self.win.u32.SendInput.impl = fail
        self.assertFalse(self.w.send_ctrl_v())
        self.assertFalse(self.w.send_key(self.w.VK_V, gap=0))

    def test_backspace_has_release_and_short_circuits_failed_batch(self):
        self.assertTrue(self.w.send_backspaces(2, gap=0))
        self.assertEqual(self.batches, [[(self.w.VK_BACK, 0),
            (self.w.VK_BACK, self.w.KEYEVENTF_KEYUP)]] * 2)
        self.win.u32.SendInput.calls.clear()
        self.win.u32.SendInput.impl = lambda *args: 0
        self.assertFalse(self.w.send_backspaces(5, gap=0))
        self.assertEqual(len(self.win.u32.SendInput.calls), 2)  # failed pair + cleanup

    def test_trigger_delete_and_paste_are_one_batch(self):
        self.assertTrue(self.w.windows_input.send_replacement(3))
        self.assertEqual(len(self.batches), 1)
        self.assertEqual(self.batches[0][:6], [(self.w.VK_BACK, 0),
            (self.w.VK_BACK, self.w.KEYEVENTF_KEYUP)] * 3)
        self.assertEqual(len(self.batches[0]), 10)

    def test_failed_modifier_release_does_not_type_a_shortcut(self):
        self.win.u32.GetAsyncKeyState.impl = lambda vk: 0x8000 if vk == self.w.VK_CONTROL else 0
        self.win.u32.SendInput.impl = lambda *args: 0
        self.assertFalse(self.w.send_ctrl_v())
        self.assertEqual(len(self.win.u32.SendInput.calls), 1)

    def test_hook_ignores_injected_text_and_resets_on_shortcut_navigation(self):
        seen, reset = [], []
        self.assertTrue(self.w.start_keyboard_hook(seen.append, lambda: seen.append('back'),
                                                  on_reset=lambda: reset.append(True)))
        record = self.w.KBDLLHOOKSTRUCT()
        record.vkCode, record.flags = 0x41, 0x10
        self.win.callback(0, self.w.WM_KEYDOWN, ctypes.addressof(record))
        self.assertEqual(seen, [])
        self.win.call_key(self.win.callback, 0x41)
        self.assertEqual(seen, ['a'])
        self.win.u32.GetAsyncKeyState.impl = lambda vk: 0x8000 if vk == self.w.VK_CONTROL else 0
        self.win.call_key(self.win.callback, 0x56)
        self.assertEqual(seen, ['a'])
        self.win.u32.GetAsyncKeyState.impl = lambda vk: 0
        self.win.call_key(self.win.callback, 0x25)  # left arrow
        self.assertEqual(len(reset), 2)

    def test_mouse_press_cancels_pending_replacement_and_always_passes_through(self):
        cancelled = threading.Event()
        self.win.u32.CallNextHookEx.impl = lambda *args: 73
        self.assertTrue(self.w.start_keyboard_hook(lambda char: None, lambda: None,
                                                  on_reset=cancelled.set))
        mouse = self.win.mouse_callback
        self.assertEqual(mouse(0, 0x0201, 0), 73)  # same-position left button down
        self.assertTrue(cancelled.is_set())
        result = trigger_backend(
            write_text=lambda text: self.fail('mouse-cancelled trigger wrote clipboard')).perform_trigger(
                TriggerRequest('abc', 'replacement', 10, 11, TRIGGER_LAYOUT_US), cancelled=cancelled)
        self.assertFalse(result.copied)
        for message in (0x0204, 0x0207, 0x020B, 0x020A, 0x020E):
            cancelled.clear()
            self.assertEqual(mouse(0, message, 0), 73)
            self.assertTrue(cancelled.is_set())
        cancelled.clear()
        self.assertEqual(mouse(-1, 0x0201, 0), 73)
        self.assertFalse(cancelled.is_set())
        self.w.stop_keyboard_hook()
        self.assertEqual(mouse(0, 0x0201, 0), 73)
        self.assertFalse(cancelled.is_set())

    def test_both_input_hooks_are_installed_and_removed_on_the_same_thread(self):
        self.assertTrue(self.w.start_keyboard_hook(lambda char: None, lambda: None,
                                                  on_reset=lambda: None))
        owner = self.w._hook_thread.ident
        self.assertTrue(self.win.pump_entered.wait(1))
        self.w.stop_keyboard_hook()
        installs = self.win.u32.SetWindowsHookExW.calls
        removals = self.win.u32.UnhookWindowsHookEx.calls
        self.assertEqual([call[1][0] for call in installs], [self.w.WH_KEYBOARD_LL, 14])
        self.assertEqual([call[0] for call in installs + removals], [owner] * 4)
        self.assertEqual({call[1][0] for call in removals}, {0x123456781234, 0x123456781235})

    def test_mouse_install_failure_disables_keyboard_trigger_and_unhooks_it(self):
        install = self.win.install
        self.win.u32.SetWindowsHookExW.impl = lambda kind, *args: 0 if kind == 14 else install(kind, *args)
        seen = []
        self.assertFalse(self.w.start_keyboard_hook(seen.append, lambda: None, on_reset=lambda: None))
        callback = self.win.callback
        self.w.stop_keyboard_hook()
        self.win.call_key(callback, 0x41)
        self.assertEqual(seen, [])
        self.assertEqual([call[1][0] for call in self.win.u32.UnhookWindowsHookEx.calls],
                         [0x123456781234])

    def test_enter_and_tab_pass_through_without_trigger_characters(self):
        seen, resets = [], []
        self.win.u32.CallNextHookEx.impl = lambda *args: 17
        self.assertTrue(self.w.start_keyboard_hook(seen.append, lambda: None,
                                                  on_reset=lambda: resets.append(True)))
        for key in (self.w.VK_RETURN, self.w.VK_TAB):
            self.assertEqual(self.win.call_key(self.win.callback, key), 17)
        self.assertEqual(seen, [])
        self.assertEqual(resets, [True, True])

    def test_final_replacement_guard_runs_after_modifier_release(self):
        released = []
        self.win.u32.GetAsyncKeyState.impl = lambda vk: 0x8000 if vk == self.w.VK_CONTROL else 0
        def send(count, pointer, size):
            released.append(True)
            return count
        self.win.u32.SendInput.impl = send
        self.assertFalse(self.w.windows_input.send_replacement(
            6, guard=lambda: not released))
        self.assertEqual(len(self.win.u32.SendInput.calls), 1)  # only Ctrl-up; no destructive batch


class LayoutBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.win = WindowsHarness()
        self.addCleanup(self.win.close)
        self.layout = importlib.import_module('clawboard.windows_layout')

    def test_layout_abi_retains_pointer_width_and_queries_actual_focus_thread(self):
        self.assertIs(self.win.u32.GetKeyboardLayout.restype, ctypes.c_void_p)
        self.win.u32.GetWindowThreadProcessId.impl = lambda hwnd, pid: 818
        self.win.u32.GetKeyboardLayout.impl = lambda tid: TRIGGER_LAYOUT_US
        self.assertEqual(self.layout.keyboard_layout(0x123456789), TRIGGER_LAYOUT_US)
        self.assertEqual(self.win.u32.GetWindowThreadProcessId.calls[-1][1], (0x123456789, None))
        self.assertEqual(self.win.u32.GetKeyboardLayout.calls[-1][1], (818,))

    def test_layout_reader_returns_unknown_on_invalid_handle_thread_or_native_failure(self):
        self.assertEqual(self.layout.keyboard_layout(0), 0)
        self.assertEqual(self.win.u32.GetWindowThreadProcessId.calls, [])
        self.win.u32.GetWindowThreadProcessId.impl = lambda hwnd, pid: 0
        self.assertEqual(self.layout.keyboard_layout(10), 0)
        self.assertEqual(self.win.u32.GetKeyboardLayout.calls, [])
        self.win.u32.GetWindowThreadProcessId.impl = lambda hwnd, pid: 818
        for value in (None, 0):
            self.win.u32.GetKeyboardLayout.impl = lambda tid: value
            self.assertEqual(self.layout.keyboard_layout(10), 0)
        def fail(tid):
            raise OSError('layout unavailable')
        self.win.u32.GetKeyboardLayout.impl = fail
        self.assertEqual(self.layout.keyboard_layout(10), 0)

    def test_only_known_us_layout_is_accepted_including_signed_handle_normalization(self):
        self.assertTrue(is_supported_trigger_layout(TRIGGER_LAYOUT_US))
        self.assertTrue(is_supported_trigger_layout(0xFFFFFFFF04090409))
        for layout in (0, None, 'unknown', 0x08040804, 0xE0200804, 0x04110411,
                       0x04120412, 0x00010409, 0xF0020409, 0x00020409, 0x0409):
            with self.subTest(layout=layout):
                self.assertFalse(is_supported_trigger_layout(layout))
        self.win.u32.GetWindowThreadProcessId.impl = lambda hwnd, pid: 818
        self.win.u32.GetKeyboardLayout.impl = lambda tid: 0xFFFFFFFF04090409
        self.assertEqual(self.layout.keyboard_layout(10), TRIGGER_LAYOUT_US)


class IntegrityBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.win = WindowsHarness()
        self.addCleanup(self.win.close)
        self.focus = self.win.module.windows_focus

    def test_input_requires_known_target_integrity_no_higher_than_source(self):
        for source, target, permitted in ((0x2000, 0x2000, True), (0x2000, 0x1000, True),
                                         (0x2000, 0x3000, False), (None, 0x2000, False),
                                         (0x2000, None, False), (None, None, False),
                                         (-1, 0, False)):
            with self.subTest(source=source, target=target):
                with patch.object(self.focus, '_pid_integrity', return_value=source), \
                     patch.object(self.focus, '_integrity_of', return_value=target):
                    self.assertEqual(self.focus.can_send_input(10), permitted)

    def test_invalid_target_and_integrity_query_exceptions_are_rejected(self):
        self.assertFalse(self.focus.can_send_input(0))
        for method in ('_pid_integrity', '_integrity_of'):
            with patch.object(self.focus, '_pid_integrity', return_value=0x2000), \
                 patch.object(self.focus, '_integrity_of', return_value=0x2000), \
                 patch.object(self.focus, method, side_effect=OSError('integrity unavailable')):
                self.assertFalse(self.focus.can_send_input(10))


class TriggerSafetyTests(unittest.TestCase):
    request = TriggerRequest('abc', '  replacement\n', 10, 11, TRIGGER_LAYOUT_US)

    def test_clipboard_preparation_precedes_deletion_and_preserves_raw_text(self):
        calls = []
        result = trigger_backend(write_text=lambda text: calls.append(('write', text)) or True,
            replace_keys=lambda count: calls.append(('replace', count)) or True).perform_trigger(self.request)
        self.assertTrue(result.pasted)
        self.assertEqual(calls, [('write', '  replacement\n'), ('replace', 4)])

    def test_busy_clipboard_never_deletes_typed_trigger(self):
        result = trigger_backend(write_text=lambda text: False,
            replace_keys=lambda count: self.fail('deleted before preparing clipboard')).perform_trigger(self.request)
        self.assertFalse(result.copied)
        self.assertFalse(result.pasted)
        self.assertIn('未替换', result.error)

    def test_focus_switch_before_or_during_preparation_never_deletes(self):
        for switch_during_write in (False, True):
            with self.subTest(during_write=switch_during_write):
                foreground = [10 if switch_during_write else 20]
                calls = []
                def write(text):
                    calls.append(text)
                    foreground[0] = 20
                    return True
                result = trigger_backend(foreground=lambda: foreground[0], write_text=write,
                    replace_keys=lambda count: self.fail('deleted in another window')).perform_trigger(self.request)
                self.assertFalse(result.pasted)
                self.assertEqual(bool(calls), switch_during_write)
                self.assertEqual(result.copied, switch_during_write)

    def test_same_window_different_focus_control_is_rejected(self):
        result = trigger_backend(target_focus=lambda target: 12,
            write_text=lambda text: self.fail('stale trigger overwrote clipboard')).perform_trigger(self.request)
        self.assertFalse(result.copied)

    def test_clipboard_changed_after_write_cancels_deletion(self):
        result = trigger_backend(current_sequence=lambda: 6,
            replace_keys=lambda count: self.fail('deleted with different clipboard')).perform_trigger(self.request)
        self.assertTrue(result.copied)
        self.assertFalse(result.pasted)
        self.assertEqual(result.sequence, 5)

    def test_additional_input_after_preparation_cancels_deletion(self):
        cancelled = threading.Event()
        def write(text):
            cancelled.set()
            return True
        result = trigger_backend(write_text=write,
            replace_keys=lambda count: self.fail('deleted after further user input')).perform_trigger(
                self.request, cancelled=cancelled)
        self.assertFalse(result.pasted)

    def test_failed_injection_reports_copy_only_result(self):
        result = trigger_backend(replace_keys=lambda count: False).perform_trigger(self.request)
        self.assertTrue(result.copied)
        self.assertFalse(result.pasted)
        self.assertIn('检查输入框', result.error)

    def test_cjk_unknown_dvorak_and_international_layouts_never_write_or_erase(self):
        for layout in (0, 0x08040804, 0xE0200804, 0x04110411, 0x04120412,
                       0x00010409, 0xF0020409, 0x00020409):
            with self.subTest(layout=layout):
                request = TriggerRequest('nihao', 'IME-must-not-expand', 10, 11, layout)
                result = trigger_backend(read_layout=lambda focus: layout,
                    write_text=lambda text: self.fail('IME replacement wrote clipboard'),
                    replace_keys=lambda count: self.fail('IME replacement erased input')).perform_trigger(request)
                self.assertFalse(result.copied)
                self.assertFalse(result.pasted)
        # Backward-compatible construction lacks a trustworthy layout snapshot.
        self.assertFalse(trigger_backend().perform_trigger(
            TriggerRequest('abc', 'replacement', 10, 11)).copied)

    def test_layout_exception_or_missing_reader_never_writes(self):
        def fail(focus):
            raise OSError('layout query failed')
        for read in (None, fail):
            result = trigger_backend(read_layout=read,
                write_text=lambda text: self.fail('unknown layout wrote clipboard')).perform_trigger(self.request)
            self.assertFalse(result.copied)

    def test_layout_change_after_write_cancels_deletion(self):
        layout = [TRIGGER_LAYOUT_US]
        def write(text):
            layout[0] = 0x08040804
            return True
        result = trigger_backend(read_layout=lambda focus: layout[0], write_text=write,
            replace_keys=lambda count: self.fail('erased after switch to IME')).perform_trigger(self.request)
        self.assertTrue(result.copied)
        self.assertFalse(result.pasted)

    def test_final_native_guard_rechecks_layout_and_clipboard(self):
        layout = [TRIGGER_LAYOUT_US]
        def checked_replace(count, *, guard):
            layout[0] = 0x08040804
            return guard()
        result = trigger_backend(read_layout=lambda focus: layout[0],
            replace_keys_guarded=checked_replace,
            replace_keys=lambda count: self.fail('unguarded fallback used')).perform_trigger(self.request)
        self.assertTrue(result.copied)
        self.assertFalse(result.pasted)

    def test_ordinary_paste_remains_available_under_chinese_ime(self):
        result = trigger_backend(read_layout=lambda focus: 0x08040804).perform(
            PasteRequest(1, text='中文粘贴', target=10, should_paste=True))
        self.assertTrue(result.copied)
        self.assertTrue(result.pasted)

    def test_denied_or_unknown_integrity_never_activates_or_injects_ordinary_paste(self):
        def unknown(target):
            raise OSError('integrity unavailable')
        for permission in (lambda target: False, lambda target: None, unknown):
            with self.subTest(permission=permission):
                result = trigger_backend(can_message=lambda target: False, can_inject=permission,
                    activate=lambda *args, **kwargs: self.fail('activated a protected target'),
                    send_keys=lambda: self.fail('injected into a protected target')).perform(
                        PasteRequest(1, text='copied only', target=10, should_paste=True))
                self.assertTrue(result.copied)
                self.assertFalse(result.pasted)
                self.assertIn('手动 Ctrl+V', result.error)

    def test_known_same_integrity_allows_input_and_rechecks_after_activation(self):
        calls = []
        def activate(target, **kwargs):
            calls.append('activate')
            return True
        result = trigger_backend(can_message=lambda target: False,
            can_inject=lambda target: calls.append('permission') or True, activate=activate,
            send_keys=lambda: calls.append('send') or True).perform(
                PasteRequest(1, text='normal', target=10, should_paste=True))
        self.assertTrue(result.pasted)
        self.assertEqual(calls, ['permission', 'activate', 'permission', 'send'])
        permission = iter((True, False))
        result = trigger_backend(can_message=lambda target: False,
            can_inject=lambda target: next(permission), activate=activate,
            send_keys=lambda: self.fail('injected after permissions changed')).perform(
                PasteRequest(1, text='copied only', target=10, should_paste=True))
        self.assertTrue(result.copied)
        self.assertFalse(result.pasted)

    def test_denied_or_unknown_integrity_trigger_never_writes_or_erases(self):
        def unknown(target):
            raise OSError('integrity unavailable')
        for permission in (lambda target: False, lambda target: None, unknown):
            result = trigger_backend(can_inject=permission,
                write_text=lambda text: self.fail('protected trigger changed clipboard'),
                replace_keys=lambda count: self.fail('protected trigger erased input')).perform_trigger(self.request)
            self.assertFalse(result.copied)
            self.assertFalse(result.pasted)

    def test_trigger_final_guard_rechecks_integrity(self):
        permitted = [True]
        def checked_replace(count, *, guard):
            permitted[0] = False
            return guard()
        result = trigger_backend(can_inject=lambda target: permitted[0],
            replace_keys_guarded=checked_replace,
            replace_keys=lambda count: self.fail('unguarded protected injection')).perform_trigger(self.request)
        self.assertTrue(result.copied)
        self.assertFalse(result.pasted)

    def test_ordinary_paste_rejects_injection_failure_or_late_focus_change(self):
        for changes in ({'send_keys': lambda: False}, {'foreground': lambda: 20},
                        {'current_sequence': lambda: 6}):
            with self.subTest(changes=list(changes)):
                result = trigger_backend(can_message=lambda target: False, **changes).perform(
                    PasteRequest(1, text='text', target=10, should_paste=True))
                self.assertTrue(result.copied)
                self.assertFalse(result.pasted)

    def test_message_paste_does_not_deliver_a_later_external_copy(self):
        result = trigger_backend(current_sequence=lambda: 6,
            message=lambda target: self.fail('delivered clipboard from later copy')).perform(
                PasteRequest(1, text='text', target=10, should_paste=True))
        self.assertTrue(result.copied)
        self.assertFalse(result.pasted)

    def test_cancellation_during_file_probe_prevents_either_clipboard_writer(self):
        for is_file in (False, True):
            with self.subTest(is_file=is_file):
                cancelled = threading.Event()
                def probe(text):
                    cancelled.set()
                    return is_file
                result = backend(looks_files=probe,
                    write_text=lambda text: self.fail('cancelled text writer ran'),
                    write_files=lambda files: self.fail('cancelled file writer ran')).perform(
                        PasteRequest(1, text='C:\\file.txt'), cancelled=cancelled)
                self.assertFalse(result.copied)
                self.assertIn('取消', result.error)

    def test_cancellation_during_plain_conversion_or_encoding_prevents_write(self):
        cancelled = threading.Event()
        def convert(text):
            cancelled.set()
            return text
        native = backend(write_text=lambda text: self.fail('cancelled plain writer ran'))
        with patch('clawboard.paste_adapter.to_plain', convert):
            result = native.perform(PasteRequest(1, text='text', plain=True), cancelled=cancelled)
        self.assertFalse(result.copied)
        cancelled.clear()
        class EncodingText(str):
            def encode(self, *args, **kwargs):
                cancelled.set()
                return super().encode(*args, **kwargs)
        with patch('clawboard.paste_adapter.to_plain', lambda text: EncodingText(text)):
            result = native.perform(PasteRequest(1, text='text', plain=True, trim=False),
                                    cancelled=cancelled)
        self.assertFalse(result.copied)

    def test_cancellation_during_image_decode_prevents_write(self):
        cancelled = threading.Event()
        def decode(raw):
            cancelled.set()
            return b'dib', 1, 1
        result = backend(decode_image=decode,
            write_image=lambda dib: self.fail('cancelled image writer ran')).perform(
                PasteRequest(1, image_name='synthetic.png'), cancelled=cancelled)
        self.assertFalse(result.copied)

    def test_trigger_and_ordinary_paste_share_the_same_bounded_queue(self):
        operations, state = [], {'text': '', 'seq': 4}
        entered, release = threading.Event(), threading.Event()
        def write(text):
            state['text'] = text
            state['seq'] += 1
            operations.append(('write', text))
            if text == 'normal':
                entered.set()
                release.wait(2)
            return True
        app = FakeApp(trigger_backend(write_text=write, sequence=lambda: state['seq'],
            current_sequence=lambda: state['seq'],
            message=lambda target: operations.append(('paste', state['text'])) or True,
            replace_keys=lambda count: operations.append(('replace', state['text'])) or True))
        try:
            self.assertTrue(app.paste('normal'))
            self.assertTrue(entered.wait(1))
            self.assertTrue(app._queue_trigger(self.request))
            self.assertEqual(operations, [('write', 'normal')])
            self.assertFalse(app.write_clip('synchronous competitor'))
            release.set()
            app.wait()
            self.assertEqual(operations, [('write', 'normal'), ('paste', 'normal'),
                ('write', self.request.replacement), ('replace', self.request.replacement)])
            self.assertEqual([event for event in app.events if event[0] == 'ack'],
                             [('ack', 5), ('ack', 6)])
        finally:
            release.set()
            app.close_paste()

    def test_stopping_trigger_generation_cancels_queued_request(self):
        entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
        writes = []
        def write(text):
            writes.append(text)
            entered.set()
            release.wait(2)
            return True
        app = FakeApp(trigger_backend(write_text=write))
        try:
            app.paste('normal')
            self.assertTrue(entered.wait(1))
            self.assertTrue(app._queue_trigger(self.request, stopped=stopped))
            stopped.set()
            release.set()
            app.wait()
            self.assertEqual(writes, ['normal'])
        finally:
            release.set()
            app.close_paste()

    def test_layout_change_while_queued_never_writes_trigger_payload(self):
        entered, release = threading.Event(), threading.Event()
        layout, writes = [TRIGGER_LAYOUT_US], []
        def write(text):
            writes.append(text)
            entered.set()
            release.wait(2)
            return True
        app = FakeApp(trigger_backend(write_text=write, read_layout=lambda focus: layout[0]))
        try:
            self.assertTrue(app.paste('normal'))
            self.assertTrue(entered.wait(1))
            self.assertTrue(app._queue_trigger(self.request))
            layout[0] = 0x08040804
            release.set()
            app.wait()
            self.assertEqual(writes, ['normal'])
            self.assertFalse(app._queue_trigger(self.request))
        finally:
            release.set()
            app.close_paste()

    def test_refreshing_trigger_mapping_discards_old_buffer(self):
        engine = TriggerEngine({'abc': 'old'})
        for char in 'abc':
            engine.feed(char)
        engine.set_triggers({'abc': 'new'})
        self.assertIsNone(engine.feed(' '))


class TriggerWiringTests(unittest.TestCase):
    def wiring(self, triggers=None):
        tree = ast.parse((ROOT / 'clawboard/system.py').read_text(encoding='utf-8'))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'SystemMixin')
        nodes = [node for node in cls.body if isinstance(node, ast.FunctionDef)
                 and node.name in ('setup_trigger', '_stop_trigger_worker', '_refresh_triggers')]
        callbacks, posted, context = {}, [], [10, 11, TRIGGER_LAYOUT_US]
        def start(on_char, on_backspace, on_reset=None):
            callbacks.update(char=on_char, back=on_backspace, reset=on_reset)
            return True
        namespace = dict(threading=threading, TriggerEngine=TriggerEngine,
            TriggerRequest=TriggerRequest, top_hwnd=lambda root: 99,
            stop_keyboard_hook=lambda: None, start_keyboard_hook=start,
            u32=types.SimpleNamespace(GetForegroundWindow=lambda: context[0]),
            target_focus_hwnd=lambda target: context[1],
            keyboard_layout=lambda focus: context[2],
            is_supported_trigger_layout=is_supported_trigger_layout)
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
                     '<trigger-wiring-contract>', 'exec'), namespace)
        app = types.SimpleNamespace(st={'trigger_enabled': True}, root=None,
            data={'groups': [{'items': triggers or [{'trigger': 'abc', 'text': 'replacement'}]}]},
            application=types.SimpleNamespace(dispatcher=types.SimpleNamespace(
                post=lambda *args: posted.append(args))),
            _ensure_paste=lambda: None, _queue_trigger=lambda *args: None, note=lambda text: None)
        for node in nodes:
            setattr(app, node.name, types.MethodType(namespace[node.name], app))
        app.setup_trigger()
        return app, callbacks, posted, context

    def test_setup_captures_original_target_and_cancels_after_further_input(self):
        app, callbacks, posted, context = self.wiring()
        for char in 'abc ':
            callbacks['char'](char)
        self.assertEqual(posted[0][1], TriggerRequest('abc', 'replacement', 10, 11, TRIGGER_LAYOUT_US))
        self.assertFalse(posted[0][2].is_set())
        callbacks['char']('x')
        self.assertTrue(posted[0][2].is_set())
        callbacks['reset']()
        for separator in ('\n', '\t'):
            for char in 'abc' + separator:
                callbacks['char'](char)
        self.assertEqual(len(posted), 1)
        for char in 'ab':
            callbacks['char'](char)
        context[:] = [20, 21, TRIGGER_LAYOUT_US]
        for char in 'c ':
            callbacks['char'](char)
        self.assertEqual(len(posted), 1)
        app._stop_trigger_worker()
        self.assertTrue(posted[0][3].is_set())

    def test_pinyin_letters_and_space_never_queue_an_ime_replacement(self):
        app, callbacks, posted, context = self.wiring(
            [{'trigger': 'nihao', 'text': 'IME-must-not-expand'}])
        for layout in (0x08040804, 0xE0200804, 0, 0x00010409, 0x00020409):
            context[2] = layout
            for char in 'nihao ':
                callbacks['char'](char)
        self.assertEqual(posted, [])
        self.assertEqual(app._trigger_engine.buf, [])

    def test_layout_change_during_letters_resets_buffer_and_cancels_pending(self):
        app, callbacks, posted, context = self.wiring()
        for char in 'ab':
            callbacks['char'](char)
        context[2] = 0x08040804
        callbacks['char']('c')
        context[2] = TRIGGER_LAYOUT_US
        callbacks['char'](' ')
        self.assertEqual(posted, [])
        callbacks['reset']()
        for char in 'abc ':
            callbacks['char'](char)
        self.assertEqual(len(posted), 1)
        context[2] = 0x08040804
        callbacks['back']()
        self.assertTrue(posted[0][2].is_set())


if __name__ == '__main__':
    unittest.main(verbosity=2)
