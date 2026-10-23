"""The real clipboard transaction adapter with native calls replaced by ports."""
import ast
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clawboard.services import CaptureResult, ClipboardSnapshot


class SnapshotTests(unittest.TestCase):
    def reader(self, *, opened=True, excluded=False, sequence=2, data=None):
        events = []
        native = SimpleNamespace(OpenClipboard=lambda _: events.append('open') or opened,
            CloseClipboard=lambda: events.append('close'),
            GetClipboardSequenceNumber=lambda: sequence,
            IsClipboardFormatAvailable=lambda fmt: fmt == (50 if excluded else 13))
        namespace = {'u32': native, 'CaptureResult': CaptureResult, 'ClipboardSnapshot': ClipboardSnapshot,
            '_clip_fmt_id': lambda name: 50 if name == 'exclude' else 51,
            'CF_NAME_EXCLUDE': 'exclude', 'CF_NAME_INCLUDE_HISTORY': 'include',
            'CF_DIB': 8, 'CF_UNICODETEXT': 13, 'CF_HDROP': 15,
            '_bytes': lambda fmt: events.append(('read', fmt)) or
                                  (b'h\x00e\x00l\x00l\x00o\x00\x00\x00' if data is None else data),
            'capture_source': lambda own, delay_retry=False: ('editor', 99),
            'window_title_of': lambda hwnd: 'Synthetic editor'}
        tree = ast.parse((ROOT / 'clawboard/win32_snapshot.py').read_text(encoding='utf-8'))
        tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'read_snapshot']
        exec(compile(tree, 'win32_snapshot.py', 'exec'), namespace)
        return namespace['read_snapshot'], events

    def test_busy_clipboard_retries_without_attempting_read_or_close(self):
        read, events = self.reader(opened=False)
        self.assertEqual(read(2).status, 'retry')
        self.assertEqual(events, ['open'])

    def test_privacy_and_data_are_in_one_open_transaction(self):
        read, events = self.reader(excluded=True)
        self.assertEqual(read(2).status, 'private')
        self.assertEqual(events, ['open', 'close'])

    def test_successful_snapshot_closes_clipboard_and_captures_source(self):
        read, events = self.reader()
        result = read(2, own_hwnd=10, include_title=True)
        self.assertEqual(result.status, 'captured')
        self.assertEqual(result.snapshot.text, 'hello')
        self.assertEqual(result.snapshot.source_title, 'Synthetic editor')
        self.assertEqual(events, ['open', ('read', 13), 'close'])

    def test_sequence_change_before_commit_is_retryable(self):
        read, events = self.reader(sequence=3)
        self.assertEqual(read(2).status, 'retry')
        self.assertEqual(events[-1], 'close')

    def test_broken_utf16_does_not_acknowledge_content(self):
        read, events = self.reader(data=b'\x00\xd8')
        self.assertEqual(read(2).status, 'retry')
        self.assertEqual(events[-1], 'close')


if __name__ == '__main__':
    unittest.main()
