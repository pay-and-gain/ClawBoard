"""Import UI boundaries with synthetic controls; no App, clipboard or real data."""
import ast
from copy import deepcopy
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
from clawboard.backups import BackupError, BackupCancelled
from clawboard.dispatch import EventDispatcher
from clawboard.import_merge import plan_merge as actual_plan_merge
from clawboard.import_service import ImportService
from clawboard.models import default_data
from clawboard.privacy import display_text
from clawboard.tasks import WorkerTasks


class Widget:
    def __init__(self, value=''):
        self.owner = threading.get_ident()
        self.value, self.options, self.exists = value, {}, True
        self.cancelled, self.unbound, self.rows, self.selection = [], [], [], set()

    def _owner(self):
        assert self.owner == threading.get_ident(), 'worker touched Tk'

    def configure(self, **options):
        self._owner()
        self.options.update(options)

    def get(self):
        self._owner()
        return self.value

    def set(self, value):
        self._owner()
        self.value = value

    def delete(self, first, last):
        self._owner()
        self.value, self.rows, self.selection = '', [], set()

    def insert(self, where, value):
        self._owner()
        if where == 'end':
            self.rows.append(value)
        else:
            self.value = value

    def curselection(self):
        self._owner()
        return tuple(sorted(self.selection))

    def selection_clear(self, *args):
        self.selection.clear()

    def selection_set(self, index):
        self.selection.add(index)

    def winfo_exists(self):
        self._owner()
        return self.exists

    def destroy(self):
        self.exists = False

    def after_cancel(self, job):
        self.cancelled.append(job)

    def unbind(self, sequence, binding):
        self.unbound.append((sequence, binding))

    def trace_remove(self, *args):
        pass

    def focus_set(self):
        self.focused = True


class ImportDialogTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='cb-import-ui-')
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.source = self.base / 'synthetic.json'
        self.source.write_text('{"version":3,"items":[]}', encoding='utf-8')
        self.raw = self.source.read_bytes()
        self.calls = []
        self.runtime = SimpleNamespace(NO_SAVE=False)
        self.dispatcher = EventDispatcher()
        self.tasks = WorkerTasks(self.dispatcher)
        self.addCleanup(lambda: self.tasks.shutdown(wait=True))
        self.entries = (
            SimpleNamespace(key='c:0', section='clip', group_name='',
                item=dict(text='synthetic\nfull body'), issue=''),
            SimpleNamespace(key='c:1', section='clip', group_name='',
                item=dict(text='duplicate'), issue=''),
            SimpleNamespace(key='g:0:0', section='phrase', group_name='Synthetic',
                item=dict(text='13812345678', mask_off=True, sens=[]), issue=''),
            SimpleNamespace(key='c:2', section='clip', group_name='',
                item=dict(text='[图片]'), issue='JSON缺图'),
        )
        self.plan = SimpleNamespace(rows=tuple(
            SimpleNamespace(key=entry.key, status=status, message=status)
            for entry, status in zip(self.entries, ('ready', 'duplicate', 'trigger_disabled', 'blocked'))),
            imported_count=2, duplicate_count=1, disabled_trigger_count=1, error='')
        self.preview = SimpleNamespace(source=SimpleNamespace(path=self.source,
            sha256='a' * 64, entries=self.entries), plan=self.plan, current_image_hashes={})
        self.namespace = dict(Path=Path, Event=threading.Event, deepcopy=deepcopy,
            runtime=self.runtime, BackupError=BackupError, BackupCancelled=BackupCancelled,
            T=dict(fg2='#777', danger='#f00'), tk=SimpleNamespace(TclError=RuntimeError),
            display_text=display_text, plan_merge=lambda *a, **kw: self.plan,
            filedialog=SimpleNamespace(askopenfilename=lambda **kw: self._record('picker', str(self.source))),
            messagebox=SimpleNamespace(askyesno=lambda *a, **kw: self._record('confirm', True)),
            prepare_import_job=lambda *a: self._record('prepare', self.base / 'fake-job.json'),
            launch_restore_job=lambda *a: self._record('launch', object()),
            cancel_restore_job=lambda *a, **kw: self._record('cancel', None))
        for filename in ('backup_dialog.py', 'import_dialog.py'):
            tree = ast.parse((ROOT / 'clawboard' / filename).read_text(encoding='utf-8'))
            cls = next(node for node in tree.body if isinstance(node, ast.ClassDef))
            exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])),
                filename, 'exec'), self.namespace)
        cls = self.namespace['ImportWindow']
        self.dialog = d = cls.__new__(cls)
        self.root = Widget()
        d.app = SimpleNamespace(root=self.root, data=dict(clip=[dict(text='synthetic current')]),
            _store=SimpleNamespace(recovery_required=False), st=dict(mask_sensitive=True),
            quit_app=lambda: self._record('quit', None))
        d.win = Widget()
        d._base_dir, d._service = self.base, SimpleNamespace(inspect=lambda *a, **kw: self.preview)
        d._tasks, d._key = self.tasks, 'synthetic-import-ui'
        d._closed = d._busy = d._restoring = False
        d._generation, d._restore_job, d.preview, d._snapshot = 0, None, None, None
        d._cancel, d._jobs, d._rows, d._row_status = threading.Event(), {}, [], {}
        d._scale_binding, d._archive_trace = 'binding', 'trace'
        d.archive, d.status, d.summary = Widget(), Widget(), Widget()
        d.listbox, d.preview_text, d.import_button = Widget(), Widget(), Widget()
        d._controls = tuple(Widget() for _ in range(4))

    def _record(self, name, result):
        self.calls.append(name)
        return result

    def ready(self):
        self.dialog._show_preview(self.preview)

    def drain(self):
        deadline = time.monotonic() + 3
        while self.tasks.pending and time.monotonic() < deadline:
            self.dispatcher.drain()
            time.sleep(.001)
        self.assertEqual(self.tasks.pending, 0)
        self.assertFalse(self.dispatcher.errors)
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_preview_selects_only_ready_rows_and_keeps_conflict_explanation(self):
        self.ready()
        self.assertEqual(self.dialog._selection_keys(), ('c:0', 'g:0:0'))
        self.assertIn('重复 · 跳过', self.dialog.listbox.rows[1])
        self.assertIn('触发词停用', self.dialog.listbox.rows[2])
        self.assertIn('不可导入', self.dialog.listbox.rows[3])
        self.assertIn('已选2项', self.dialog.summary.options['text'])

    def test_imported_mask_off_and_empty_sens_cannot_bypass_masking(self):
        self.ready()
        self.dialog.listbox.selection = {2}
        self.dialog._selection_changed()
        self.assertNotIn('13812345678', self.dialog.preview_text.value)
        self.assertIn('138******78', self.dialog.preview_text.value)
        self.assertNotIn('13812345678', self.dialog.listbox.rows[2])

    def test_full_preview_keeps_long_body_and_is_read_only(self):
        self.entries[0].item['text'] = 'synthetic-' * 4000
        self.ready()
        self.assertIn(self.entries[0].item['text'], self.dialog.preview_text.value)
        self.assertEqual(self.dialog.preview_text.options['state'], 'disabled')

    def test_no_save_blocks_picker_inspect_confirm_prepare_launch_and_quit(self):
        self.ready()
        self.runtime.NO_SAVE = True
        for action in (self.dialog.choose_archive, self.dialog.inspect_archive, self.dialog.confirm_import):
            action()
        self.dialog._start_import(self.preview, self.dialog._selection_keys())
        self.assertEqual(self.calls, [])
        self.assertEqual(self.tasks.pending, 0)

    def test_readonly_store_blocks_all_mutation_paths(self):
        self.ready()
        self.dialog.app._store.recovery_required = True
        self.dialog.choose_archive()
        self.dialog.confirm_import()
        self.assertEqual(self.calls, [])
        self.assertIn('只读保护', self.dialog.status.options['text'])

    def test_inspection_copies_current_data_before_worker(self):
        captured = {}
        def submit(function, path, snapshot, **kwargs):
            captured['snapshot'] = snapshot
            captured['callbacks'] = kwargs
            return object()
        self.dialog._tasks = SimpleNamespace(submit=submit)
        self.dialog.archive.set(str(self.source))
        self.dialog.inspect_archive()
        self.dialog.app.data['clip'][0]['text'] = 'changed after preview'
        self.assertEqual(captured['snapshot']['clip'][0]['text'], 'synthetic current')
        self.assertIsNot(captured['snapshot'], self.dialog.app.data)

    def test_worker_does_not_touch_controls_and_runs_off_owner_thread(self):
        threads = []
        def inspect(*args, **kwargs):
            threads.append(threading.get_ident())
            return self.preview
        self.dialog._service = SimpleNamespace(inspect=inspect)
        self.dialog.archive.set(str(self.source))
        self.dialog.inspect_archive()
        self.drain()
        self.assertNotEqual(threads, [threading.get_ident()])
        self.assertIs(self.dialog.preview, self.preview)

    def test_path_change_invalidates_preview_and_disables_import(self):
        self.ready()
        self.dialog.archive.set('other.json')
        self.dialog._archive_changed()
        self.assertIsNone(self.dialog.preview)
        self.assertEqual(self.dialog._rows, [])
        self.assertEqual(self.dialog.import_button.options['state'], 'disabled')

    def test_capacity_error_still_allows_deselect_and_retry(self):
        self.plan.error = '容量不足'
        self.ready()
        self.assertEqual(self.dialog.import_button.options['state'], 'normal')
        self.dialog.confirm_import()
        self.assertEqual(self.calls, [])
        self.dialog.select_none()
        self.assertEqual(self.dialog.import_button.options['state'], 'disabled')
        self.plan.error = ''
        self.dialog.listbox.selection = {0}
        self.dialog._selection_changed()
        self.assertEqual(self.dialog.import_button.options['state'], 'normal')

    def test_failed_exit_cancels_ticket_before_later_ordinary_exit(self):
        self.ready()
        self.dialog.confirm_import()
        self.assertEqual(self.calls, ['confirm', 'prepare', 'launch', 'quit', 'cancel'])
        self.assertIsNone(self.dialog._restore_job)
        self.assertIn('未能正常退出', self.dialog.status.options['text'])

    def test_successful_exit_leaves_ticket_for_helper(self):
        self.ready()
        def quit_app():
            self.calls.append('quit')
            self.root.exists = self.dialog.win.exists = False
        self.dialog.app.quit_app = quit_app
        self.dialog.confirm_import()
        self.assertEqual(self.calls, ['confirm', 'prepare', 'launch', 'quit'])
        self.assertIsNotNone(self.dialog._restore_job)

    def test_launch_failure_does_not_quit_and_revokes(self):
        self.ready()
        def launch(*args):
            self.calls.append('launch')
            raise OSError('synthetic failure')
        self.namespace['launch_restore_job'] = launch
        self.dialog._start_import(self.preview, self.dialog._selection_keys())
        self.assertEqual(self.calls, ['prepare', 'launch', 'cancel'])

    def test_no_save_switch_after_prepare_revokes_before_launch(self):
        self.ready()
        def prepare(*args):
            self.calls.append('prepare')
            self.runtime.NO_SAVE = True
            return self.base / 'fake-job.json'
        self.namespace['prepare_import_job'] = prepare
        self.dialog._start_import(self.preview, self.dialog._selection_keys())
        self.assertEqual(self.calls, ['prepare', 'cancel'])

    def test_changed_preview_or_selection_during_confirmation_cannot_import(self):
        self.ready()
        def confirm(*args, **kwargs):
            self.dialog.listbox.selection = {0}
            return True
        self.namespace['messagebox'].askyesno = confirm
        self.dialog.confirm_import()
        self.assertEqual(self.calls, [])
        self.ready()
        def change_preview(*args, **kwargs):
            self.dialog.preview = None
            return True
        self.namespace['messagebox'].askyesno = change_preview
        self.dialog.confirm_import()
        self.assertEqual(self.calls, [])

    def test_failed_revocation_keeps_window_open_and_blocks_second_ticket(self):
        self.ready()
        self.dialog._restore_job = self.base / 'old-job.json'
        def cancel(*args, **kwargs):
            raise OSError('synthetic marker failure')
        self.namespace['cancel_restore_job'] = cancel
        self.dialog.close()
        self.dialog._start_import(self.preview, self.dialog._selection_keys())
        self.assertFalse(self.dialog._closed)
        self.assertEqual(self.calls, [])
        self.assertIn('保持程序打开', self.dialog.status.options['text'])

    def test_close_cancels_jobs_and_late_callbacks_are_ignored(self):
        captured = {}
        invalidated = []
        def submit(*args, **kwargs):
            captured.update(kwargs)
            return object()
        self.dialog._tasks = SimpleNamespace(submit=submit, invalidate=invalidated.append)
        self.dialog._submit_inspect(str(self.source), {})
        self.dialog._jobs['dpi'] = 'timer-id'
        self.dialog.close()
        before = dict(self.dialog.status.options)
        captured['on_result'](self.preview)
        captured['on_error'](BackupError('late error'))
        self.assertIsNone(self.dialog.preview)
        self.assertEqual(self.dialog.status.options, before)
        self.assertTrue(captured['cancelled']())
        self.assertEqual(invalidated, ['synthetic-import-ui'])
        self.assertEqual(self.dialog.win.cancelled, ['timer-id'])
        self.assertEqual(self.root.unbound, [('<<ClawBoardUIScaleChanged>>', 'binding')])

    def test_path_change_during_worker_rejects_old_completion(self):
        captured, invalidated = {}, []
        def submit(*args, **kwargs):
            captured.update(kwargs)
            return object()
        self.dialog._tasks = SimpleNamespace(submit=submit, invalidate=invalidated.append)
        self.dialog._submit_inspect(str(self.source), {})
        self.dialog.archive.set('changed.json')
        self.dialog._archive_changed()
        captured['on_result'](self.preview)
        captured['on_error'](BackupError('old result'))
        self.assertIsNone(self.dialog.preview)
        self.assertEqual(self.dialog.archive.get(), 'changed.json')
        self.assertFalse(self.dialog._busy)
        self.assertTrue(captured['cancelled']())
        self.assertEqual(invalidated, ['synthetic-import-ui'])

    def test_busy_queue_restores_controls_without_creating_ticket(self):
        self.dialog._tasks = SimpleNamespace(submit=lambda *a, **kw: None)
        self.dialog._submit_inspect(str(self.source), {})
        self.assertFalse(self.dialog._busy)
        self.assertIn('繁忙', self.dialog.status.options['text'])
        self.assertEqual(self.calls, [])

    def test_real_plan_mixed_missing_image_can_import_only_eligible_selection(self):
        payload = dict(version=3, items=[dict(text='synthetic text'),
            dict(text='[图片]', content_type='image', image_path='missing.png')])
        self.source.write_text(json.dumps(payload), encoding='utf-8')
        self.dialog.app.data = default_data()
        preview = ImportService(self.base / 'current.json').inspect(
            self.source, deepcopy(self.dialog.app.data))
        self.assertTrue(preview.plan.error)
        self.dialog._show_preview(preview)
        self.assertEqual(self.dialog._selection_keys(), ('c:0',))
        self.namespace['plan_merge'] = actual_plan_merge
        self.dialog.confirm_import()
        self.assertEqual(self.calls, ['confirm', 'prepare', 'launch', 'quit', 'cancel'])
        self.assertEqual(self.dialog.app.data, default_data())

    def test_real_confirmation_uses_current_data_instead_of_stale_snapshot(self):
        self.source.write_text(json.dumps(dict(version=3,
            items=[dict(text='synthetic incoming')])), encoding='utf-8')
        self.dialog.app.data = default_data()
        preview = ImportService(self.base / 'current.json').inspect(
            self.source, deepcopy(self.dialog.app.data))
        self.dialog._show_preview(preview)
        self.dialog.app.data['clip'].append(dict(text='synthetic incoming'))
        self.namespace['plan_merge'] = actual_plan_merge
        self.dialog.confirm_import()
        self.assertEqual(self.calls, [])
        self.assertIn('均已存在', self.dialog.status.options['text'])


if __name__ == '__main__':
    unittest.main()
