"""Backup UI adapters: synthetic temporary files and fake restore helpers only."""
import ast
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clawboard.backups import BackupService, BackupError, BackupCancelled
from clawboard.backup_format import BackupPreview
from clawboard.dispatch import EventDispatcher
from clawboard.tasks import WorkerTasks


class Widget:
    def __init__(self, value=''):
        self.owner = threading.get_ident()
        self.value, self.options, self.exists = value, {}, True
        self.cancelled, self.unbound = [], []

    def configure(self, **options):
        assert threading.get_ident() == self.owner, 'worker touched Tk'
        self.options.update(options)

    def get(self):
        assert threading.get_ident() == self.owner
        return self.value

    def set(self, value):
        assert threading.get_ident() == self.owner
        self.value = value

    def winfo_exists(self):
        assert threading.get_ident() == self.owner
        return self.exists

    def destroy(self):
        self.exists = False

    def after_cancel(self, job):
        self.cancelled.append(job)

    def unbind(self, sequence, binding):
        self.unbound.append((sequence, binding))


class BackupDialogTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='cb-backup-ui-test-')
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.source = self.base / 'synthetic.json'
        self.source.write_text(json.dumps(dict(schema_version=3,
            clip=[dict(id='test', text='synthetic')], groups=[], settings={})), encoding='utf-8')
        self.raw = self.source.read_bytes()
        self.preview = BackupPreview(self.base / 'synthetic.zip', 'a' * 64,
                                     '2026-10-26T08:00:00Z', 'test', 3, 2, 1, 2048, 4)
        self.calls = []
        self.runtime = SimpleNamespace(NO_SAVE=False)
        self.dispatcher = EventDispatcher()
        self.tasks = WorkerTasks(self.dispatcher)
        self.addCleanup(lambda: self.tasks.shutdown(wait=True))
        self.namespace = dict(Path=Path, Event=threading.Event, time=time, datetime=datetime,
            runtime=self.runtime, BackupError=BackupError, BackupCancelled=BackupCancelled,
            T=dict(fg2='#777', danger='#f00'), tk=SimpleNamespace(TclError=RuntimeError),
            filedialog=SimpleNamespace(
                askopenfilename=lambda **kw: self._record('open', str(self.preview.archive)),
                asksaveasfilename=lambda **kw: self._record('save-picker', str(self.preview.archive))),
            messagebox=SimpleNamespace(askyesno=lambda *a, **kw: self._record('confirm', True)),
            prepare_restore_job=lambda *a, **kw: self._record('prepare', self.base / 'fake-job.json'),
            launch_restore_job=lambda *a, **kw: self._record('launch', object()),
            cancel_restore_job=lambda *a, **kw: self._record('cancel', None))
        tree = ast.parse((ROOT / 'clawboard/backup_dialog.py').read_text(encoding='utf-8'))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef))
        exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])),
                     'backup_dialog.py', 'exec'), self.namespace)
        self.dialog = dialog = self.namespace['BackupWindow'].__new__(self.namespace['BackupWindow'])
        self.root = Widget()
        dialog.app = SimpleNamespace(root=self.root, save_now=lambda: self._record('flush', True),
                                     quit_app=lambda: self._record('quit', None))
        dialog.win = Widget()
        dialog._base_dir = self.base
        dialog._service = BackupService(self.source, self.base / 'synthetic-images')
        dialog._tasks, dialog._key = self.tasks, 'synthetic-backup-ui'
        dialog._closed = dialog._busy = dialog._restoring = False
        dialog._generation, dialog._restore_job = 0, None
        dialog._cancel, dialog._jobs = threading.Event(), {}
        dialog._scale_binding = 'synthetic-binding'
        dialog.preview = None
        dialog.archive, dialog.preview_label, dialog.status = Widget(), Widget(), Widget()
        dialog._controls = tuple(Widget() for _ in range(4))
        dialog.restore_button = Widget()

    def _record(self, name, result):
        self.calls.append(name)
        return result

    def drain(self):
        deadline = time.monotonic() + 3
        while self.tasks.pending and time.monotonic() < deadline:
            self.dispatcher.drain()
            time.sleep(.001)
        self.assertEqual(self.tasks.pending, 0)
        self.assertFalse(self.dispatcher.errors)
        self.assertEqual(self.source.read_bytes(), self.raw)

    def ready(self):
        self.dialog._show_preview(self.preview)
        self.dialog._paint_busy()

    def test_no_save_blocks_pickers_workers_confirm_prepare_launch_and_quit(self):
        self.ready()
        self.runtime.NO_SAVE = True
        for action in (self.dialog.choose_archive, self.dialog.create_backup,
                       self.dialog.inspect_archive, self.dialog.confirm_restore):
            action()
        self.dialog._start_restore(self.preview)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.tasks.pending, 0)
        self.assertFalse(self.preview.archive.exists())

    def test_create_flushes_on_owner_then_writes_only_temporary_zip_in_worker(self):
        owner = threading.get_ident()
        service, threads = self.dialog._service, []
        def create(path, cancelled):
            threads.append(threading.get_ident())
            self.assertIn('flush', self.calls)
            return service.create(path, cancelled=cancelled)
        self.dialog._service = SimpleNamespace(create=create)
        self.dialog.create_backup()
        self.drain()
        self.assertEqual(self.calls, ['save-picker', 'flush'])
        self.assertNotEqual(threads, [owner])
        self.assertEqual(self.dialog.preview.clip_count, 1)
        self.assertTrue(self.preview.archive.exists())
        self.assertEqual(self.dialog.restore_button.options['state'], 'normal')

    def test_failed_flush_does_not_submit_or_create(self):
        self.dialog.app.save_now = lambda: False
        self.dialog.create_backup()
        self.assertEqual(self.tasks.pending, 0)
        self.assertFalse(self.preview.archive.exists())
        self.assertIn('保存问题', self.dialog.status.options['text'])

    def test_inspect_corrupt_package_reports_error_and_keeps_restore_disabled(self):
        self.preview.archive.write_bytes(b'not a complete backup')
        self.dialog.archive.set(str(self.preview.archive))
        self.dialog.inspect_archive()
        self.drain()
        self.assertIsNone(self.dialog.preview)
        self.assertEqual(self.dialog.restore_button.options['state'], 'disabled')
        self.assertEqual(self.dialog.status.options['fg'], '#f00')

    def test_preview_contains_counts_size_and_external_file_limit(self):
        self.ready()
        text = self.dialog.preview_label.options['text']
        for expected in ('2026-10-26', 'test', '3 条', '2 条', '1 张', '2.0 KB', '4 条', '只保留路径'):
            self.assertIn(expected, text)
        self.dialog.archive.set('changed.zip')
        self.dialog._archive_changed()
        self.assertIsNone(self.dialog.preview)
        self.assertEqual(self.dialog.restore_button.options['state'], 'disabled')

    def test_preview_time_is_local_and_invalid_value_has_bounded_fallback(self):
        self.ready()
        expected = datetime(2026, 10, 26, 8, tzinfo=timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M:%S')
        self.assertIn('备份时间：' + expected + '（本机时间）',
                      self.dialog.preview_label.options['text'])
        self.assertEqual(self.preview.created_at, '2026-10-26T08:00:00Z')
        self.assertEqual(self.dialog._created_time('unknown'), 'unknown')
        self.assertEqual(self.dialog._created_time('invalid-' * 20), ('invalid-' * 20)[:64] + '…')

    def test_stale_worker_completion_cannot_touch_closed_window(self):
        captured = {}
        invalidated = []
        def submit(*args, **kwargs):
            captured.update(kwargs)
            return object()
        self.dialog._tasks = SimpleNamespace(submit=submit, invalidate=invalidated.append)
        self.dialog._submit('inspect', str(self.preview.archive))
        self.dialog._jobs['dpi'] = 'timer-id'
        self.dialog.close()
        before = dict(self.dialog.status.options)
        captured['on_result'](self.preview)
        captured['on_error'](BackupError('late error'))
        self.assertIsNone(self.dialog.preview)
        self.assertEqual(self.dialog.status.options, before)
        self.assertTrue(captured['cancelled']())
        self.assertEqual(invalidated, ['synthetic-backup-ui'])
        self.assertEqual(self.dialog.win.cancelled, ['timer-id'])
        self.assertEqual(self.root.unbound, [('<<ClawBoardUIScaleChanged>>', 'synthetic-binding')])

    def test_superseded_worker_completion_is_ignored(self):
        callbacks = []
        def submit(*args, **kwargs):
            callbacks.append(kwargs)
            return object()
        self.dialog._tasks = SimpleNamespace(submit=submit)
        self.dialog._submit('inspect', 'first.zip')
        self.dialog._submit('inspect', 'second.zip')
        callbacks[0]['on_result'](self.preview)
        self.assertIsNone(self.dialog.preview)
        callbacks[1]['on_result'](self.preview)
        self.assertIs(self.dialog.preview, self.preview)

    def test_busy_queue_restores_controls_without_scheduling(self):
        self.dialog._tasks = SimpleNamespace(submit=lambda *a, **kw: None)
        self.dialog._submit('inspect', str(self.preview.archive))
        self.assertFalse(self.dialog._busy)
        self.assertIn('繁忙', self.dialog.status.options['text'])

    def test_restore_exit_failure_cancels_before_later_ordinary_exit(self):
        self.ready()
        self.dialog.confirm_restore()
        self.assertEqual(self.calls, ['confirm', 'prepare', 'launch', 'quit', 'cancel'])
        self.assertIsNone(self.dialog._restore_job)
        self.assertIn('恢复未开始', self.dialog.status.options['text'])
        self.assertFalse(self.dialog._busy)

    def test_restore_success_leaves_ticket_for_helper_only_after_root_disappears(self):
        self.ready()
        def quit_app():
            self.calls.append('quit')
            self.root.exists = self.dialog.win.exists = False
        self.dialog.app.quit_app = quit_app
        self.dialog.confirm_restore()
        self.assertEqual(self.calls, ['confirm', 'prepare', 'launch', 'quit'])
        self.assertIsNotNone(self.dialog._restore_job)

    def test_launch_failure_cancels_and_does_not_quit(self):
        self.ready()
        def fail(*args):
            self.calls.append('launch')
            raise OSError('synthetic failure')
        self.namespace['launch_restore_job'] = fail
        self.dialog._start_restore(self.preview)
        self.assertEqual(self.calls, ['prepare', 'launch', 'cancel'])

    def test_no_save_switch_after_prepare_cancels_without_launch_or_quit(self):
        self.ready()
        def prepare(*args):
            self.calls.append('prepare')
            self.runtime.NO_SAVE = True
            return self.base / 'fake-job.json'
        self.namespace['prepare_restore_job'] = prepare
        self.dialog._start_restore(self.preview)
        self.assertEqual(self.calls, ['prepare', 'cancel'])

    def test_stale_confirmation_cannot_restore_different_preview(self):
        self.ready()
        def confirm(*args, **kwargs):
            self.dialog.preview = None
            return True
        self.namespace['messagebox'].askyesno = confirm
        self.dialog.confirm_restore()
        self.assertEqual(self.calls, [])

    def test_failed_ticket_cancellation_keeps_window_open_for_retry(self):
        self.dialog._restore_job = self.base / 'fake-job.json'
        def fail(*args, **kwargs):
            raise OSError('cannot write marker')
        self.namespace['cancel_restore_job'] = fail
        self.dialog.close()
        self.assertTrue(self.dialog.win.exists)
        self.assertFalse(self.dialog._closed)
        self.assertIn('保持程序打开', self.dialog.status.options['text'])

    def test_failed_revocation_blocks_second_restore_ticket(self):
        self.ready()
        self.dialog._restore_job = self.base / 'old-fake-job.json'
        def fail(*args, **kwargs):
            raise OSError('cannot write marker')
        self.namespace['cancel_restore_job'] = fail
        self.dialog._start_restore(self.preview)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.dialog._restore_job.name, 'old-fake-job.json')


if __name__ == '__main__':
    unittest.main()
