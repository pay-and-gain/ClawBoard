"""Portable application-level capture/save integration using synthetic input."""
import os
import json
from pathlib import Path
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clawboard.application import ApplicationController
from clawboard.media import ImageStore
from clawboard.models import default_data
from clawboard.services import CaptureResult, ClipboardSnapshot
from clawboard.storage import JsonStore


def dib_sample():
    pixels = bytes((12, 34, 56, 255, 98, 76, 54, 255))
    return struct.pack('<IiiHHIIiiII', 40, 2, 1, 1, 32, 0, len(pixels), 0, 0, 0, 0) + pixels


class TestApplicationController(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='clawboard-application-')
        self.directory = Path(self.temp.name)
        self.data = default_data()
        self.store = JsonStore(self.directory / 'data.json')
        self.images = ImageStore(self.directory / 'images')
        self.errors, self.outcomes = [], []
        self.no_save = False
        self.controller = ApplicationController(self.data, self.store, self.images,
            no_save=lambda: self.no_save, on_capture=self.outcomes.append, on_error=self.errors.append)

    def tearDown(self):
        self.controller.close()
        self.temp.cleanup()

    def pump(self, timeout=3):
        end = time.monotonic() + timeout
        pause = threading.Event()
        while self.controller.pending:
            self.controller.drain()
            if time.monotonic() >= end:
                self.fail('application work did not settle')
            pause.wait(0.001)
        self.controller.drain()

    def configure_text(self, text='hello', sequence=1, source='chrome'):
        self.controller.configure_clipboard(lambda: sequence,
            lambda seq: ClipboardSnapshot(seq, 'text', text=text, source_app=source))

    def seed_persisted_image(self):
        name = self.images.write(b'synthetic existing image')
        self.data['clip'] = [{'id': 'persisted-image', 'text': '[图片]', 'image_path': name,
                             'content_type': 'image', 'created_at': 1}]
        self.data['settings']['max_items'] = 1
        self.store.save(self.data)
        return name

    def finish_capture_callback(self, timeout=3):
        end = time.monotonic() + timeout
        while self.controller.capture_pending:
            self.controller.drain()
            if time.monotonic() >= end:
                self.fail('capture callback did not finish')
            threading.Event().wait(0.001)

    def test_capture_commits_on_owner_and_saves_a_detached_snapshot(self):
        threads = []
        def read(seq):
            threads.append(threading.get_ident())
            return ClipboardSnapshot(seq, 'text', text='hello', source_app='chrome')
        self.controller.configure_clipboard(lambda: 1, read)
        owner = threading.get_ident()
        self.controller.on_capture = lambda outcome: self.outcomes.append((outcome, threading.get_ident()))
        self.assertTrue(self.controller.capture())
        self.assertEqual(self.data['clip'], [])
        self.pump()
        self.controller.flush()
        self.assertEqual(self.data['clip'][0]['text'], 'hello')
        self.assertEqual(self.outcomes[0][1], owner)
        self.assertNotEqual(threads[0], owner)
        self.assertEqual(self.controller.clipboard.last_sequence, 1)
        self.assertEqual(self.store.load().data['clip'][0]['text'], 'hello')

    def test_busy_clipboard_read_is_retried_without_advancing_sequence(self):
        attempts = []
        def read(seq):
            attempts.append(seq)
            return CaptureResult('retry') if len(attempts) == 1 else ClipboardSnapshot(seq, 'text', text='hello')
        self.controller.configure_clipboard(lambda: 2, read, initial_sequence=1)
        self.controller.capture()
        self.pump()
        self.assertEqual(self.controller.clipboard.last_sequence, 1)
        self.assertEqual(self.data['clip'], [])
        self.assertTrue(self.controller.capture())
        self.pump()
        self.assertEqual(self.controller.clipboard.last_sequence, 2)
        self.assertEqual(attempts, [2, 2])

    def test_ignore_and_sensitive_filters_acknowledge_deliberate_skips(self):
        self.configure_text(source='keepass')
        self.controller.capture()
        self.pump()
        self.assertEqual(self.outcomes[-1].status, 'skip')
        self.assertEqual(self.controller.clipboard.last_sequence, 1)
        self.assertEqual(self.data['clip'], [])
        self.data['settings']['skip_sensitive'] = True
        self.configure_text('password=synthetic_secret_123', sequence=2)
        self.controller.capture()
        self.pump()
        self.assertEqual(self.outcomes[-1].status, 'sensitive')
        self.assertEqual(self.controller.clipboard.last_sequence, 2)
        self.assertFalse(self.store.path.exists())

    def test_pause_and_reset_discard_capture_already_being_prepared(self):
        entered, release = threading.Event(), threading.Event()
        def read(seq):
            entered.set()
            release.wait(2)
            return ClipboardSnapshot(seq, 'text', text='must not commit')
        self.controller.configure_clipboard(lambda: 1, read)
        try:
            self.assertTrue(self.controller.capture())
            self.assertTrue(entered.wait(2))
            self.data['settings']['listen'] = False
            self.controller.reset_clipboard(5)
            self.assertFalse(self.controller.capture())
            release.set()
            self.pump()
            self.assertEqual(self.data['clip'], [])
            self.assertEqual(self.outcomes, [])
            self.assertEqual(self.controller.clipboard.last_sequence, 5)
        finally:
            release.set()

    def test_own_clipboard_write_invalidates_old_processing_result(self):
        entered, release = threading.Event(), threading.Event()
        from clawboard.history import prepare_text
        def delayed(text):
            entered.set()
            release.wait(2)
            return prepare_text(text)
        self.configure_text(sequence=2)
        try:
            with patch('clawboard.application.prepare_text', side_effect=delayed):
                self.controller.capture()
                self.assertTrue(entered.wait(2))
                self.controller.reset_clipboard(3)
                release.set()
                self.pump()
            self.assertEqual(self.data['clip'], [])
            self.assertEqual(self.controller.clipboard.last_sequence, 3)
        finally:
            release.set()

    def test_no_save_keeps_both_text_and_image_capture_off_disk(self):
        self.no_save = True
        self.configure_text()
        self.controller.capture()
        self.pump()
        self.controller.configure_clipboard(lambda: 2,
            lambda seq: ClipboardSnapshot(seq, 'image', payload=dib_sample()))
        self.controller.capture()
        self.pump()
        self.assertEqual([item['content_type'] for item in self.data['clip']], ['image', 'text'])
        self.assertNotIn('image_path', self.data['clip'][0])
        self.assertFalse(self.store.path.exists())
        self.assertFalse(self.images.directory.exists())
        self.assertEqual(self.controller.data_revision, 2)

    def test_no_save_crop_does_not_delete_a_real_image(self):
        name = self.images.write(b'synthetic existing image')
        self.data['clip'] = [{'id': 'existing', 'text': '[图片]', 'image_path': name,
                             'content_type': 'image', 'created_at': 1}]
        self.data['settings']['max_items'] = 1
        self.no_save = True
        self.configure_text()
        self.controller.capture()
        self.pump()
        self.controller.close()
        self.assertTrue(self.images.path(name).exists())

    def test_image_codec_and_file_write_run_in_worker(self):
        threads = []
        write = self.images.write
        def observed(png):
            threads.append(threading.get_ident())
            return write(png)
        self.controller.configure_clipboard(lambda: 1,
            lambda seq: ClipboardSnapshot(seq, 'image', payload=dib_sample(), source_app='snippingtool'))
        with patch.object(self.images, 'write', side_effect=observed):
            self.controller.capture()
            self.pump()
        record = self.data['clip'][0]
        self.assertEqual((record['image_w'], record['image_h']), (2, 1))
        self.assertTrue(self.images.path(record['image_path']).exists())
        self.assertNotEqual(threads, [threading.get_ident()])
        self.assertEqual(self.controller.clipboard.last_sequence, 1)

    def test_duplicate_catchup_does_not_add_or_mutate_latest_record(self):
        original = {'id': 'old', 'text': 'same', 'created_at': 1, 'copy_count': 4}
        self.data['clip'].append(original)
        self.configure_text('same')
        self.controller.capture(quiet=True, dedup=True, force=True)
        self.pump()
        self.assertEqual(self.data['clip'], [original])
        self.assertEqual(original['copy_count'], 4)
        self.assertEqual(self.outcomes[-1].status, 'dup')
        self.assertTrue(self.outcomes[-1].quiet)

    def test_corrupt_store_remains_protected_without_json_or_image_writes(self):
        broken = b'{broken synthetic json'
        self.store.path.write_bytes(broken)
        self.store.load()
        self.assertIsNone(self.controller.request_save())
        self.assertIsNone(self.controller.request_save())
        self.controller.configure_clipboard(lambda: 1,
            lambda seq: ClipboardSnapshot(seq, 'image', payload=dib_sample()))
        self.controller.capture()
        self.pump()
        self.assertEqual(self.store.path.read_bytes(), broken)
        self.assertFalse(self.images.directory.exists())
        self.assertEqual(len(self.errors), 1)

    def test_stale_image_capture_removes_its_uncommitted_file(self):
        entered, release = threading.Event(), threading.Event()
        write = self.images.write
        def delayed_write(png):
            name = write(png)
            entered.set()
            release.wait(2)
            return name
        self.controller.configure_clipboard(lambda: 1,
            lambda seq: ClipboardSnapshot(seq, 'image', payload=dib_sample()))
        try:
            with patch.object(self.images, 'write', side_effect=delayed_write):
                self.controller.capture()
                self.assertTrue(entered.wait(2))
                self.controller.reset_clipboard(2)
                release.set()
                self.pump()
            self.assertEqual(self.data['clip'], [])
            self.assertEqual(list(self.images.directory.glob('*.png')), [])
        finally:
            release.set()

    def test_capture_refuses_parallel_jobs_and_does_not_ack_rejected_work(self):
        entered, release = threading.Event(), threading.Event()
        def read(seq):
            entered.set()
            release.wait(2)
            return ClipboardSnapshot(seq, 'text', text='hello')
        self.controller.configure_clipboard(lambda: 1, read)
        try:
            self.controller.capture()
            self.assertTrue(entered.wait(2))
            self.assertFalse(self.controller.capture())
            self.assertEqual(self.controller.clipboard.last_sequence, 0)
            release.set()
            self.pump()
            self.assertEqual(len(self.data['clip']), 1)
        finally:
            release.set()

    def test_processing_error_is_sanitized_and_allows_retry(self):
        self.configure_text('synthetic_private_value')
        with patch('clawboard.application.prepare_text', side_effect=RuntimeError('synthetic_private_value')):
            self.controller.capture()
            self.pump()
        self.assertEqual(self.controller.clipboard.last_sequence, 0)
        self.assertNotIn('synthetic_private_value', str(self.errors[-1]))
        self.assertTrue(self.controller.capture())
        self.pump()
        self.assertEqual(self.data['clip'][0]['text'], 'synthetic_private_value')

    def test_unsupported_image_is_terminal_instead_of_infinite_retry(self):
        self.controller.configure_clipboard(lambda: 1,
            lambda seq: ClipboardSnapshot(seq, 'image', payload=b'invalid'))
        self.controller.capture()
        self.pump()
        self.assertEqual(self.outcomes[-1].status, 'unsupported')
        self.assertEqual(self.controller.clipboard.last_sequence, 1)
        self.assertEqual(self.errors, [])

    def test_close_flushes_pending_save_and_prevents_new_ui_work(self):
        self.data['settings']['theme'] = 'light'
        self.controller.request_save()
        self.controller.close()
        self.controller.close()
        self.assertEqual(self.store.load().data['settings']['theme'], 'light')
        self.assertFalse(self.controller.capture())
        self.assertIsNone(self.controller.request_save())

    def test_failed_close_preserves_live_controller_then_retries_latest_snapshot(self):
        self.data['settings']['theme'] = 'light'
        with patch.object(self.store, 'save', side_effect=OSError('synthetic disk unavailable')):
            with self.assertRaises(OSError):
                self.controller.close()
            self.assertFalse(self.controller.closed)
            self.assertFalse(self.controller.dispatcher.closed)
            self.assertFalse(self.controller.tasks.closed)
            observed = []
            self.controller.dispatcher.post(observed.append, 'still usable')
            self.controller.drain()
            self.assertEqual(observed, ['still usable'])
        self.controller.close()
        self.assertTrue(self.controller.closed)
        self.assertEqual(self.store.load().data['settings']['theme'], 'light')

    def test_crop_does_not_delete_old_image_before_json_save_finishes(self):
        name = self.seed_persisted_image()
        original_save = self.store.save
        entered, release = threading.Event(), threading.Event()
        def blocked(data):
            entered.set()
            release.wait(2)
            return original_save(data)
        self.configure_text('replacement')
        try:
            with patch.object(self.store, 'save', side_effect=blocked):
                self.controller.capture()
                self.finish_capture_callback()
                self.assertTrue(entered.wait(2))
                self.assertTrue(self.images.path(name).exists())
                self.assertEqual(json.loads(self.store.path.read_text(encoding='utf-8'))['clip'][0]['image_path'], name)
                release.set()
                self.pump()
            self.assertFalse(self.images.path(name).exists())
            self.assertEqual(json.loads(self.store.path.read_text(encoding='utf-8'))['clip'][0]['text'], 'replacement')
        finally:
            release.set()

    def test_failed_crop_save_preserves_old_json_image_then_close_retry_collects_it(self):
        name = self.seed_persisted_image()
        self.configure_text('replacement')
        with patch.object(self.store, 'save', side_effect=OSError('synthetic disk unavailable')):
            self.controller.capture()
            self.pump()
            self.assertTrue(self.images.path(name).exists())
            self.assertEqual(json.loads(self.store.path.read_text(encoding='utf-8'))['clip'][0]['image_path'], name)
            self.assertTrue(self.errors)
        # No dispatcher drain after this successful save: close must confirm
        # revisions itself before it shuts down queued UI notifications.
        self.controller.close()
        self.assertFalse(self.images.path(name).exists())
        self.assertEqual(json.loads(self.store.path.read_text(encoding='utf-8'))['clip'][0]['text'], 'replacement')

    def test_ui_deletion_cleanup_belongs_to_next_save_and_close_confirms_it(self):
        name = self.seed_persisted_image()
        self.assertTrue(self.controller.queue_image_cleanup([name]))
        self.assertTrue(self.images.path(name).exists())
        self.data['clip'] = []
        self.controller.request_save()
        self.controller.flush()
        self.assertTrue(self.images.path(name).exists())
        self.controller.close()
        self.assertFalse(self.images.path(name).exists())

    def test_cleanup_rejects_no_save_and_readonly_data(self):
        name = self.seed_persisted_image()
        self.no_save = True
        self.assertFalse(self.controller.queue_image_cleanup([name]))
        self.data['clip'] = []
        self.controller.request_save()
        self.no_save = False
        self.store.recovery_required = True
        self.assertFalse(self.controller.queue_image_cleanup([name]))
        self.controller.close()
        self.assertTrue(self.images.path(name).exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
