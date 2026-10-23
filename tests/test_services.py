"""Portable service/concurrency regressions; no App, Tk or real clipboard."""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clawboard.dispatch import EventDispatcher
from clawboard.services import CaptureResult, ClipboardService, ClipboardSnapshot, SaveService
from clawboard.tasks import WorkerTasks


def wait_until(predicate, timeout=2):
    end = time.monotonic() + timeout
    pause = threading.Event()
    while not predicate():
        if time.monotonic() >= end:
            raise AssertionError('condition did not become ready')
        pause.wait(0.001)


class TestDispatcher(unittest.TestCase):
    def test_worker_delivery_runs_only_when_owner_drains(self):
        dispatcher = EventDispatcher()
        observed = []
        worker = threading.Thread(target=lambda: dispatcher.post(lambda: observed.append(threading.get_ident())))
        worker.start()
        worker.join()
        self.assertEqual(observed, [])
        self.assertEqual(dispatcher.drain(), 1)
        self.assertEqual(observed, [threading.get_ident()])

    def test_wrong_thread_cannot_drain(self):
        dispatcher = EventDispatcher()
        errors = []
        def worker():
            try:
                dispatcher.drain()
            except RuntimeError as error:
                errors.append(error)
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        self.assertEqual(len(errors), 1)

    def test_callback_error_does_not_break_later_events(self):
        dispatcher = EventDispatcher()
        observed = []
        def bad():
            raise ValueError('synthetic failure')
        dispatcher.post(bad)
        dispatcher.post(observed.append, 'delivered')
        dispatcher.drain()
        self.assertEqual(observed, ['delivered'])
        self.assertIsInstance(dispatcher.errors[0], ValueError)

    def test_close_drops_queued_callbacks_and_rejects_new_events(self):
        dispatcher = EventDispatcher()
        observed = []
        dispatcher.post(observed.append, 1)
        dispatcher.close()
        dispatcher.close()
        self.assertFalse(dispatcher.post(observed.append, 2))
        self.assertEqual(dispatcher.drain(), 0)
        self.assertEqual(observed, [])

    def test_drain_budget_leaves_remaining_work(self):
        dispatcher = EventDispatcher()
        for _ in range(3):
            dispatcher.post(lambda: None)
        self.assertEqual(dispatcher.drain(limit=2), 2)
        self.assertEqual(dispatcher.pending, 1)


class TestWorkerTasks(unittest.TestCase):
    def setUp(self):
        self.dispatcher = EventDispatcher()
        self.tasks = WorkerTasks(self.dispatcher, max_workers=2, max_pending=2)

    def tearDown(self):
        self.tasks.shutdown(wait=True)
        self.dispatcher.close()

    def test_capacity_covers_completed_callbacks_until_drain(self):
        first = self.tasks.submit(lambda: 'first')
        second = self.tasks.submit(lambda: 'second')
        first.result(timeout=2)
        second.result(timeout=2)
        wait_until(lambda: self.dispatcher.pending == 2)
        self.assertIsNone(self.tasks.submit(lambda: 'overflow'))
        self.dispatcher.drain()
        accepted = self.tasks.submit(lambda: 'accepted')
        self.assertIsNotNone(accepted)
        accepted.result(timeout=2)

    def test_latest_result_wins_even_when_old_work_finishes_later(self):
        gate = threading.Event()
        observed = []
        first = self.tasks.submit(lambda: gate.wait(2) or 'old', key='preview', on_result=observed.append)
        second = self.tasks.submit(lambda: 'new', key='preview', on_result=observed.append)
        try:
            second.result(timeout=2)
            gate.set()
            first.result(timeout=2)
            wait_until(lambda: self.dispatcher.pending == 2)
            self.dispatcher.drain()
            self.assertEqual(observed, ['new'])
        finally:
            gate.set()

    def test_invalidate_discards_queued_result(self):
        observed = []
        future = self.tasks.submit(lambda: 'obsolete', key='search', on_result=observed.append)
        future.result(timeout=2)
        wait_until(lambda: self.dispatcher.pending == 1)
        self.tasks.invalidate('search')
        self.dispatcher.drain()
        self.assertEqual(observed, [])

    def test_result_and_error_callbacks_use_owner_thread(self):
        observed = []
        def bad():
            raise LookupError('synthetic')
        success = self.tasks.submit(lambda: 42, on_result=lambda value: observed.append((value, threading.get_ident())))
        failure = self.tasks.submit(bad, on_error=lambda error: observed.append((type(error), threading.get_ident())))
        success.result(timeout=2)
        with self.assertRaises(LookupError):
            failure.result(timeout=2)
        wait_until(lambda: self.dispatcher.pending == 2)
        self.dispatcher.drain()
        self.assertCountEqual(observed, [(42, threading.get_ident()), (LookupError, threading.get_ident())])

    def test_shutdown_suppresses_already_queued_delivery(self):
        observed = []
        future = self.tasks.submit(lambda: 'done', on_result=observed.append)
        future.result(timeout=2)
        wait_until(lambda: self.dispatcher.pending == 1)
        self.tasks.shutdown(wait=True)
        self.tasks.shutdown()
        self.dispatcher.drain()
        self.assertEqual(observed, [])
        self.assertIsNone(self.tasks.submit(lambda: None))

    def test_missing_error_handler_is_observable_in_dispatcher(self):
        def bad():
            raise RuntimeError('synthetic')
        future = self.tasks.submit(bad)
        with self.assertRaises(RuntimeError):
            future.result(timeout=2)
        wait_until(lambda: self.dispatcher.pending == 1)
        self.dispatcher.drain()
        self.assertIsInstance(self.dispatcher.errors[0], RuntimeError)

    def test_completed_dynamic_keys_do_not_accumulate_generation_state(self):
        for number in range(10):
            future = self.tasks.submit(lambda: None, key='preview-%d' % number)
            future.result(timeout=2)
            wait_until(lambda: self.dispatcher.pending == 1)
            self.dispatcher.drain()
        self.assertEqual(self.tasks._generations, {})


class TestClipboardService(unittest.TestCase):
    def test_busy_read_is_retried_for_same_sequence(self):
        attempts = []
        def read(seq):
            attempts.append(seq)
            return CaptureResult('retry') if len(attempts) == 1 else ClipboardSnapshot(seq, 'text', text='sample')
        service = ClipboardService(lambda: 5, read, initial_sequence=4)
        self.assertEqual(service.poll().status, 'retry')
        self.assertEqual(service.last_sequence, 4)
        self.assertEqual(service.poll().status, 'captured')
        self.assertEqual(service.last_sequence, 4)
        self.assertEqual(service.poll().status, 'pending')
        self.assertTrue(service.complete(5))
        self.assertEqual(service.last_sequence, 5)
        self.assertEqual(service.poll().status, 'unchanged')
        self.assertEqual(attempts, [5, 5])

    def test_processing_failure_releases_inflight_without_ack(self):
        service = ClipboardService(lambda: 2, lambda seq: ClipboardSnapshot(seq, 'image', payload=b'dib'), initial_sequence=1)
        service.poll()
        self.assertFalse(service.complete(99))
        self.assertTrue(service.complete(2, success=False))
        self.assertEqual(service.last_sequence, 1)
        self.assertEqual(service.poll().status, 'captured')

    def test_empty_and_private_are_deliberately_acknowledged(self):
        for status in ('empty', 'private', 'unsupported'):
            with self.subTest(status=status):
                service = ClipboardService(lambda: 2, lambda seq: CaptureResult(status), initial_sequence=1)
                self.assertEqual(service.poll().status, status)
                self.assertEqual(service.last_sequence, 2)
                self.assertIsNone(service.inflight_sequence)

    def test_changed_snapshot_is_retried(self):
        service = ClipboardService(lambda: 2, lambda seq: ClipboardSnapshot(3, 'text'), initial_sequence=1)
        self.assertEqual(service.poll().status, 'retry')
        self.assertEqual(service.last_sequence, 1)

    def test_prepare_is_injected_and_snapshot_is_immutable(self):
        service = ClipboardService(lambda: 1, lambda seq: None, processor=lambda snapshot: snapshot.text.upper())
        snapshot = ClipboardSnapshot(1, 'text', text='sample')
        self.assertEqual(service.prepare(snapshot), 'SAMPLE')
        with self.assertRaises(AttributeError):
            snapshot.text = 'mutated'

    def test_reset_invalidates_read_in_progress_without_blocking(self):
        entered, release = threading.Event(), threading.Event()
        outcomes = []
        def reader(seq):
            entered.set()
            release.wait(2)
            return ClipboardSnapshot(seq, 'text')
        service = ClipboardService(lambda: 2, reader, initial_sequence=1)
        worker = threading.Thread(target=lambda: outcomes.append(service.poll()))
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.assertEqual(service.poll().status, 'pending')
            service.reset(99)
            release.set()
            worker.join(2)
            self.assertEqual(service.last_sequence, 99)
            self.assertEqual(outcomes[0].status, 'retry')
            self.assertIsNone(service.inflight_sequence)
        finally:
            release.set()
            worker.join(2)

    def test_force_reads_unchanged_sequence_for_startup_catchup(self):
        service = ClipboardService(lambda: 5, lambda seq: ClipboardSnapshot(seq, 'text'), initial_sequence=5)
        self.assertEqual(service.poll().status, 'unchanged')
        self.assertEqual(service.poll(force=True).status, 'captured')


class TestSaveService(unittest.TestCase):
    def setUp(self):
        self.dispatcher = EventDispatcher()

    def tearDown(self):
        self.dispatcher.close()

    def test_coalescing_preserves_last_request_and_copies_mutable_input(self):
        entered, release = threading.Event(), threading.Event()
        written, notified = [], []
        def write(data):
            if not written:
                entered.set()
                release.wait(2)
            written.append(data['value'])
            return 'ok'
        service = SaveService(self.dispatcher, write,
            on_saved=lambda revision, result: notified.append((revision, threading.get_ident())))
        try:
            data = {'value': [1]}
            service.request(data)
            self.assertTrue(entered.wait(2))
            data['value'].append(99)
            service.request({'value': [2]})
            revision = service.request({'value': [3]})
            release.set()
            self.assertEqual(service.flush(timeout=2), revision)
            self.assertEqual(written, [[1], [3]])
            self.assertFalse(service.pending)
            self.assertEqual(notified, [])
            self.dispatcher.drain()
            self.assertEqual(notified, [(1, threading.get_ident()), (3, threading.get_ident())])
        finally:
            release.set()
            service.close()

    def test_latest_write_failure_is_observable_and_does_not_report_saved(self):
        observed = []
        def fail(data):
            raise OSError('synthetic disk failure')
        service = SaveService(self.dispatcher, fail, on_error=lambda rev, err: observed.append((rev, type(err))))
        service.request({'value': 1})
        with self.assertRaises(OSError):
            service.flush(timeout=2)
        self.dispatcher.drain()
        self.assertEqual(observed, [(1, OSError)])
        self.assertEqual(service.saved_revision, 0)
        with self.assertRaises(OSError):
            service.close()
        service.close(flush=False)

    def test_skipped_write_does_not_confirm_a_saved_revision(self):
        service = SaveService(self.dispatcher, lambda data: False)
        service.request({'value': 1})
        self.assertEqual(service.flush(timeout=2), 0)
        self.assertEqual(service.saved_revision, 0)
        service.close()

    def test_failed_close_leaves_service_open_for_new_save(self):
        failing = [True]
        written = []
        def write(data):
            if failing[0]:
                raise OSError('synthetic disk failure')
            written.append(data)
        service = SaveService(self.dispatcher, write)
        service.request({'value': 1})
        with self.assertRaises(OSError):
            service.close()
        failing[0] = False
        revision = service.request({'value': 2})
        service.close()
        self.assertEqual(written, [{'value': 2}])
        self.assertEqual(service.saved_revision, revision)

    def test_close_flushes_last_snapshot_and_drops_ui_callbacks(self):
        written, observed = [], []
        service = SaveService(self.dispatcher, lambda data: written.append(data), on_saved=lambda *args: observed.append(args))
        service.request({'value': 1})
        service.request({'value': 2})
        service.close()
        service.close()
        self.assertEqual(written[-1], {'value': 2})
        self.dispatcher.drain()
        self.assertEqual(observed, [])
        with self.assertRaises(RuntimeError):
            service.request({'value': 3})

    def test_flush_timeout_does_not_discard_accepted_save(self):
        entered, release = threading.Event(), threading.Event()
        written = []
        def write(data):
            entered.set()
            release.wait(2)
            written.append(data)
        service = SaveService(self.dispatcher, write)
        try:
            service.request({'value': 1})
            self.assertTrue(entered.wait(2))
            with self.assertRaises(TimeoutError):
                service.flush(timeout=0.001)
            release.set()
            service.flush(timeout=2)
            self.assertEqual(written, [{'value': 1}])
        finally:
            release.set()
            service.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
