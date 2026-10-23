"""Run the actual Tk bridge against a scheduler port without loading Win32/Tk."""
import ast
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clawboard.application import ApplicationController
from clawboard.media import ImageStore
from clawboard.models import default_data
from clawboard.services import ClipboardSnapshot, CaptureResult
from clawboard.storage import JsonStore


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='clawboard-bridge-')
        self.sequence = 1
        self.policy = []
        self.runtime = SimpleNamespace(NO_SAVE=True, LAST_SEQ=1, LAST_WRITE_SEQ=None)
        self.scheduled = {}
        def after(delay, callback):
            token = str(len(self.scheduled) + 1)
            self.scheduled[token] = (delay, callback)
            return token
        root = SimpleNamespace(winfo_id=lambda: 10, after=after,
                               after_cancel=lambda token: self.scheduled.pop(token, None))
        data = default_data()
        self.events = []
        self.app = SimpleNamespace(root=root, data=data, st=data['settings'],
            _store=JsonStore(Path(self.temp.name) / 'data.json'), hidden=False, tab='clip',
            render=lambda: self.events.append('render'),
            tip=lambda text: self.events.append(('tip', text)),
            note=lambda text: self.events.append(('log', text)),
            show_copy_toast=lambda text: self.events.append(('toast', text)),
            _catchup_tip=lambda: 'catch-up', close_paste=lambda: None)
        def read(sequence, **policy):
            self.policy.append(policy)
            return CaptureResult('captured', ClipboardSnapshot(sequence, 'text', text='synthetic note'))
        namespace = {'os': os, 'runtime': self.runtime,
            'sound': SimpleNamespace(play_copy=lambda: None),
            'ApplicationController': ApplicationController, 'ImageStore': ImageStore,
            'BASE_DIR': self.temp.name, 'clip_seq': lambda: self.sequence, 'read_snapshot': read}
        tree = ast.parse((ROOT / 'clawboard/tk_bridge.py').read_text(encoding='utf-8'))
        tree.body = [node for node in tree.body if isinstance(node, ast.ClassDef)]
        exec(compile(tree, 'tk_bridge.py', 'exec'), namespace)
        self.bridge = namespace['TkApplicationBridge'](self.app)
        self.app.application = self.bridge.application

    def tearDown(self):
        self.bridge.close()
        self.temp.cleanup()

    def settle(self):
        deadline = time.monotonic() + 3
        while self.bridge.application.pending:
            self.bridge.application.drain()
            if time.monotonic() > deadline:
                self.fail('bridge work did not finish')
            threading.Event().wait(0.001)
        self.bridge.application.drain()

    def test_live_capture_uses_snapshot_policy_and_owner_callbacks(self):
        self.sequence = 2
        self.app.st['smart_private'] = False
        self.app.st['record_title'] = True
        self.assertTrue(self.bridge.request_capture())
        self.settle()
        self.assertEqual(self.policy, [{'private': False, 'own_hwnd': 10, 'include_title': True}])
        self.assertEqual(self.app.data['clip'][0]['text'], 'synthetic note')
        self.assertIn('render', self.events)
        self.assertEqual(self.runtime.LAST_SEQ, 2)
        self.assertFalse(self.app._store.path.exists())

    def test_background_notification_only_enqueues_ui_work(self):
        caller = threading.Thread(target=self.bridge.clipboard_changed)
        caller.start()
        caller.join()
        self.assertFalse(self.bridge._capture_event)
        self.bridge.application.drain()
        self.assertTrue(self.bridge._capture_event)
        self.assertEqual(self.events, [])

    def test_own_write_does_not_acknowledge_a_subsequent_external_copy(self):
        self.runtime.LAST_WRITE_SEQ = 2
        self.sequence = 3
        self.bridge.own_write()
        self.assertEqual(self.bridge.application.clipboard.last_sequence, 2)
        self.bridge.request_capture()
        self.settle()
        self.assertEqual(self.bridge.application.clipboard.last_sequence, 3)
        self.assertEqual(self.app.data['clip'][0]['text'], 'synthetic note')

    def test_own_image_sequence_is_never_recaptured(self):
        self.runtime.LAST_WRITE_SEQ = self.sequence = 2
        self.bridge.request_capture()
        self.settle()
        self.assertEqual(self.app.data['clip'], [])
        self.assertEqual(self.policy, [])

    def test_paused_listener_invalidates_pending_capture(self):
        self.app.st['listen'] = False
        self.sequence = 4
        self.assertFalse(self.bridge.request_capture())
        self.assertEqual(self.bridge.application.clipboard.last_sequence, 4)

    def test_rejected_capture_cannot_change_inflight_privacy_policy(self):
        entered, release = threading.Event(), threading.Event()
        self.sequence = 2
        def sequence():
            entered.set()
            release.wait(2)
            return 2
        self.bridge.application.clipboard.sequence_reader = sequence
        self.app.st['smart_private'] = True
        self.bridge.request_capture()
        try:
            self.assertTrue(entered.wait(2))
            self.app.st['smart_private'] = False
            self.assertFalse(self.bridge.request_capture())
        finally:
            release.set()
        self.settle()
        self.assertTrue(self.policy[0]['private'])

    def test_busy_clipboard_notification_remains_pending_for_next_pump(self):
        entered, release = threading.Event(), threading.Event()
        self.sequence = 2
        def sequence():
            entered.set()
            release.wait(2)
            return 2
        self.bridge.application.clipboard.sequence_reader = sequence
        self.bridge.request_capture()
        try:
            self.assertTrue(entered.wait(2))
            self.bridge.clipboard_changed()
            self.bridge._pump()
            self.assertTrue(self.bridge._capture_event)
        finally:
            release.set()
        self.settle()
        self.bridge._pump()
        self.assertFalse(self.bridge._capture_event)
        self.settle()

    def test_forced_catchup_is_deferred_until_inflight_work_is_invalidated(self):
        entered, release = threading.Event(), threading.Event()
        self.sequence = 2
        def sequence():
            entered.set()
            release.wait(2)
            return 2
        self.bridge.application.clipboard.sequence_reader = sequence
        self.bridge.request_capture()
        try:
            self.assertTrue(entered.wait(2))
            self.bridge.application.invalidate_clipboard()
            self.assertFalse(self.bridge.request_capture(force=True, quiet=True, dedup=True))
            self.assertIsNotNone(self.bridge._deferred_capture)
        finally:
            release.set()
        self.settle()
        self.assertEqual(self.app.data['clip'], [])
        self.bridge._pump()
        self.settle()
        self.assertEqual(len(self.app.data['clip']), 1)
        self.assertIn(('tip', 'catch-up'), self.events)


if __name__ == '__main__':
    unittest.main()
