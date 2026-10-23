"""Clipboard transaction sequencing without touching the desktop clipboard."""
import ast
import ctypes
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ClipboardWrites(unittest.TestCase):
    CASES = [('clipboard.py', 'clip_write', 'synthetic'),
             ('clipboard.py', 'clip_write_files', ['C:/synthetic.txt']),
             ('image_win32.py', 'write_clipboard_dib', bytes(44))]

    def writer(self, file, name, *, empty=True, after_close='own', marker_failure=None):
        state = SimpleNamespace(sequence=10, LAST_SEQ=1, LAST_WRITE_SEQ=1,
                                pre_close=None, external_sequence=None, opens=0,
                                locked=False, formats={}, memory={}, next_handle=0)
        calls = []

        def alloc(flags, size):
            calls.append('alloc')
            if marker_failure == 'alloc' and state.next_handle:
                return 0
            state.next_handle += 1
            state.memory[state.next_handle] = ctypes.create_string_buffer(size)
            return state.next_handle

        def lock(handle):
            if marker_failure == 'lock' and handle == 2:
                return 0
            return ctypes.addressof(state.memory[handle])

        def set_data(fmt, handle):
            calls.append('marker' if fmt == 50000 else 'set')
            if marker_failure == 'set' and fmt == 50000:
                return 0
            state.formats[fmt] = handle
            state.sequence += 1
            return handle

        def open_clipboard(_):
            state.opens += 1
            if state.opens > 1 and after_close == 'busy':
                return False
            self.assertFalse(state.locked)
            state.locked = True
            return True

        def close():
            calls.append('close')
            self.assertTrue(state.locked)
            state.locked = False
            if state.opens != 1:
                return
            state.pre_close = state.sequence
            state.sequence += 2  # Windows synthesizes related formats at close.
            if after_close in ('external', 'mismatched', 'undersized'):
                # Another app wins the lock before our acknowledgement read.
                state.external_sequence = state.sequence = state.sequence + 10
                state.formats.clear()
                if after_close != 'external':
                    state.memory[99] = ctypes.create_string_buffer(
                        b'wrong-token-12345' if after_close == 'mismatched' else b'!')
                    state.formats[50000] = 99

        def get_data(fmt):
            self.assertTrue(state.locked, 'marker must be read while clipboard is locked')
            return state.formats.get(fmt, 0)

        def sequence():
            self.assertTrue(state.locked, 'ack must not sample an unlocked sequence')
            return state.sequence

        native = SimpleNamespace(
            OpenClipboard=open_clipboard, EmptyClipboard=lambda: empty,
            CloseClipboard=close, GetClipboardSequenceNumber=sequence,
            SetClipboardData=set_data, GetClipboardData=get_data,
            RegisterClipboardFormatW=lambda name: 0 if marker_failure == 'register' else 50000)
        kernel = SimpleNamespace(
            GlobalAlloc=alloc, GlobalLock=lock,
            GlobalSize=lambda h: ctypes.sizeof(state.memory[h]),
            GlobalUnlock=lambda h: None, GlobalFree=lambda h: state.memory.pop(h, None))
        namespace = dict(ctypes=ctypes, runtime=state, u32=native, k32=kernel,
                         GMEM_MOVEABLE=2, CF_UNICODETEXT=13, CF_HDROP=15,
                         MAX_DIB_BYTES=1024, CF_DIB=8, os=os,
                         _OWN_WRITE_FORMAT='ClawBoard.WriteToken.v1', _priv_fmt_cache={},
                         clip_seq=sequence, build_hdrop=lambda p: b'paths')
        helpers = ast.parse((ROOT / 'clawboard/clipboard.py').read_text(encoding='utf-8'))
        helpers.body = [n for n in helpers.body if isinstance(n, ast.FunctionDef)
                        and n.name in ('_write_own_marker', '_ack_own_write', '_clip_fmt_id')]
        exec(compile(helpers, 'clipboard-helpers', 'exec'), namespace)
        tree = ast.parse((ROOT / 'clawboard' / file).read_text(encoding='utf-8'))
        tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
        exec(compile(tree, file, 'exec'), namespace)
        return namespace[name], state, calls

    def test_all_formats_record_post_close_sequence(self):
        for file, name, value in self.CASES:
            with self.subTest(name=name):
                write, state, calls = self.writer(file, name)
                self.assertTrue(write(value))
                self.assertEqual(calls, ['alloc', 'set', 'alloc', 'marker', 'close', 'close'])
                self.assertEqual(state.LAST_SEQ, 14)
                self.assertEqual(state.LAST_WRITE_SEQ, 14)
                self.assertFalse(state.locked)

    def test_external_copy_between_close_and_ack_is_never_acknowledged(self):
        for file, name, value in self.CASES:
            for kind in ('external', 'mismatched', 'undersized'):
                with self.subTest(name=name, kind=kind):
                    write, state, calls = self.writer(file, name, after_close=kind)
                    self.assertTrue(write(value))
                    self.assertEqual(state.LAST_WRITE_SEQ, state.pre_close)
                    self.assertEqual(state.LAST_SEQ, state.pre_close)
                    self.assertNotEqual(state.LAST_WRITE_SEQ, state.external_sequence)
                    self.assertFalse(state.locked)

    def test_busy_ack_read_uses_only_pre_close_sequence(self):
        for file, name, value in self.CASES:
            with self.subTest(name=name):
                write, state, calls = self.writer(file, name, after_close='busy')
                self.assertTrue(write(value))
                self.assertEqual(state.LAST_WRITE_SEQ, state.pre_close)
                self.assertFalse(state.locked)

    def test_marker_failure_never_changes_successful_content_write(self):
        for file, name, value in self.CASES:
            for failure in ('register', 'alloc', 'lock', 'set'):
                with self.subTest(name=name, failure=failure):
                    write, state, calls = self.writer(file, name, marker_failure=failure)
                    self.assertTrue(write(value))
                    self.assertEqual(state.LAST_WRITE_SEQ, state.pre_close)
                    self.assertEqual(state.opens, 1)
                    self.assertEqual(len(state.memory), 1, 'failed marker allocation must be freed')
                    self.assertFalse(state.locked)

    def test_failed_empty_does_not_allocate_or_acknowledge(self):
        for file, name, value in self.CASES:
            with self.subTest(name=name):
                write, state, calls = self.writer(file, name, empty=False)
                self.assertFalse(write(value))
                self.assertEqual(calls, ['close'])
                self.assertEqual(state.LAST_WRITE_SEQ, 1)


if __name__ == '__main__':
    unittest.main()
