"""Recycle-bin UI contracts with synthetic records and no native App."""
import ast
from datetime import datetime
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clawboard.privacy import display_text
from clawboard.trash import TrashError


class Widget:
    def __init__(self):
        self.options, self.cancelled, self.unbound = {}, [], []
        self.exists, self.focused = True, False
        self.text = ''

    def configure(self, **options):
        self.options.update(options)

    def winfo_exists(self):
        return self.exists

    def destroy(self):
        self.exists = False

    def focus_set(self):
        self.focused = True

    def delete(self, *args):
        self.text = ''

    def insert(self, position, text):
        self.text += text

    def after_cancel(self, job):
        self.cancelled.append(job)

    def unbind(self, sequence, binding):
        self.unbound.append((sequence, binding))


class Listbox(Widget):
    def __init__(self):
        super().__init__()
        self.rows, self.selected = [], set()

    def delete(self, *args):
        self.rows.clear()
        self.selected.clear()

    def insert(self, position, text):
        self.rows.append(text)

    def curselection(self):
        return tuple(sorted(self.selected))

    def selection_set(self, index):
        self.selected.add(index)


class TrashDialogTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            dict(id='trash-one', deleted_at=1700000000000,
                 item=dict(id='one', text='Synthetic first item'), group=None),
            dict(id='trash-two', deleted_at=1700000001000,
                 item=dict(id='two', text='Synthetic phrase'), group=dict(name='Test group'))]
        self.calls = []
        self.runtime = SimpleNamespace(NO_SAVE=False)
        self.namespace = dict(datetime=datetime, runtime=self.runtime, TrashError=TrashError,
            display_text=display_text, T=dict(fg2='#777', danger='#f00'),
            tk=SimpleNamespace(TclError=RuntimeError),
            messagebox=SimpleNamespace(askyesno=lambda *a, **kw: True))
        tree = ast.parse((ROOT / 'clawboard/trash_dialog.py').read_text(encoding='utf-8'))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef))
        exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])),
                     'trash_dialog.py', 'exec'), self.namespace)
        self.dialog = dialog = self.namespace['TrashWindow'].__new__(self.namespace['TrashWindow'])
        dialog.app = SimpleNamespace(root=Widget(), st=dict(mask_sensitive=True),
            application=SimpleNamespace(trash=SimpleNamespace(entries=lambda: list(self.rows))),
            recycle_restore=lambda ids: self.record('restore', ids),
            recycle_purge=lambda ids=None: self.record('purge', ids),
            recycle_expire=lambda: self.record('expire', None))
        dialog._closed = dialog._busy = False
        dialog._rows, dialog._jobs = [], {}
        dialog._scale_binding = 'synthetic-binding'
        dialog.win, dialog.status, dialog.count = Widget(), Widget(), Widget()
        dialog.preview, dialog.listbox = Widget(), Listbox()
        dialog.restore_button, dialog.purge_button, dialog.clear_button = Widget(), Widget(), Widget()
        dialog.refresh()

    def record(self, operation, ids):
        self.calls.append((operation, ids))
        if ids is not None:
            self.rows[:] = [row for row in self.rows if row['id'] not in ids]

    def test_read_only_refresh_populates_origin_and_preview_without_actions(self):
        self.assertEqual(self.calls, [])
        self.assertEqual(len(self.dialog.listbox.rows), 2)
        self.assertIn('剪贴板历史', self.dialog.listbox.rows[0])
        self.assertIn('Test group', self.dialog.listbox.rows[1])
        self.assertIn('Synthetic first item', self.dialog.preview.text)
        self.assertEqual(self.dialog.preview.options['state'], 'disabled')

    def test_current_millisecond_timestamp_displays_local_date_and_minute(self):
        current = datetime.now()
        milliseconds = int(current.timestamp() * 1000)
        expected = current.strftime('%Y-%m-%d %H:%M')
        self.assertEqual(self.dialog._when(milliseconds), expected)
        self.rows[0]['deleted_at'] = milliseconds
        self.dialog.refresh()
        self.assertIn(expected, self.dialog.listbox.rows[0])
        self.assertIn('删除于：' + expected, self.dialog.preview.text)
        self.assertEqual(self.dialog._when('invalid'), '时间未知')

    def test_empty_view_disables_mutations_and_explains_where_records_appear(self):
        self.rows.clear()
        self.dialog.refresh()
        self.assertIn('回收站为空', self.dialog.preview.text)
        self.assertEqual(self.dialog.restore_button.options['state'], 'disabled')
        self.assertEqual(self.dialog.purge_button.options['state'], 'disabled')
        self.assertEqual(self.dialog.clear_button.options['state'], 'disabled')
        self.dialog.restore_selected()
        self.dialog.purge_all()
        self.assertEqual(self.calls, [])

    def test_no_save_blocks_all_mutation_and_even_confirmation(self):
        self.runtime.NO_SAVE = True
        def forbidden(*args, **kwargs):
            raise AssertionError('NO_SAVE must not open a destructive confirmation')
        self.namespace['messagebox'].askyesno = forbidden
        for action in (self.dialog.restore_selected, self.dialog.purge_selected,
                       self.dialog.purge_all, self.dialog.expire):
            action()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.dialog.status.options['text'], '自测模式，不改动资料')

    def test_sensitive_row_and_preview_follow_mask_setting(self):
        self.rows[0]['item'].update(text='phone 13812345678', sens=['手机号'])
        self.dialog.refresh()
        self.assertNotIn('13812345678', self.dialog.listbox.rows[0])
        self.assertNotIn('13812345678', self.dialog.preview.text)
        self.dialog.app.st['mask_sensitive'] = False
        self.dialog.refresh()
        self.assertIn('13812345678', self.dialog.preview.text)

    def test_per_record_reveal_is_preserved(self):
        self.rows[0]['item'].update(text='phone 13812345678', sens=['手机号'], mask_off=True)
        self.dialog.refresh()
        self.assertIn('13812345678', self.dialog.preview.text)

    def test_long_preview_is_bounded_and_original_record_is_unchanged(self):
        text = 'long synthetic text ' * 2000
        self.rows[0]['item']['text'] = text
        self.dialog.refresh()
        self.assertLess(len(self.dialog.preview.text), self.dialog.PREVIEW_LIMIT + 256)
        self.assertIn('恢复会保留完整内容', self.dialog.preview.text)
        self.assertEqual(self.rows[0]['item']['text'], text)

    def test_masking_looks_past_truncation_boundary(self):
        self.rows[0]['item'].update(text='x' * 113 + '13812345678' + 'y', sens=['手机号'])
        self.dialog.refresh()
        self.assertNotIn('1381234', self.dialog.listbox.rows[0])

    def test_enter_only_focuses_preview_and_never_restores(self):
        self.assertEqual(self.dialog._focus_preview(), 'break')
        self.assertTrue(self.dialog.preview.focused)
        self.assertEqual(self.calls, [])

    def test_restore_passes_selected_wrapper_ids_and_refreshes(self):
        self.dialog.listbox.selected = {1}
        self.dialog.restore_selected()
        self.assertEqual(self.calls, [('restore', ['trash-two'])])
        self.assertEqual(len(self.dialog.listbox.rows), 1)
        self.assertIn('已恢复', self.dialog.status.options['text'])

    def test_refresh_keeps_selection_by_stable_wrapper_id(self):
        self.dialog.listbox.selected = {1}
        self.rows.insert(0, dict(id='new', deleted_at=1700000002000,
            item=dict(id='new', text='new synthetic'), group=None))
        self.dialog.refresh()
        self.assertEqual(self.dialog._selection_ids(), ['trash-two'])

    def test_cancel_permanent_delete_does_nothing(self):
        self.namespace['messagebox'].askyesno = lambda *a, **kw: False
        self.dialog.purge_selected()
        self.dialog.purge_all()
        self.assertEqual(self.calls, [])

    def test_purge_selected_uses_only_selected_ids(self):
        self.dialog.purge_selected()
        self.assertEqual(self.calls, [('purge', ['trash-one'])])
        self.assertEqual([row['id'] for row in self.rows], ['trash-two'])

    def test_clear_freezes_reviewed_ids_and_leaves_new_items(self):
        def confirm(*args, **kwargs):
            self.rows.append(dict(id='later', deleted_at=1700000002000,
                item=dict(text='new while confirming'), group=None))
            return True
        self.namespace['messagebox'].askyesno = confirm
        self.dialog.purge_all()
        self.assertEqual(self.calls, [('purge', ['trash-one', 'trash-two'])])
        self.assertEqual([row['id'] for row in self.rows], ['later'])

    def test_close_during_confirmation_prevents_late_mutation(self):
        def confirm(*args, **kwargs):
            self.dialog.close()
            return True
        self.namespace['messagebox'].askyesno = confirm
        self.dialog.purge_selected()
        self.assertEqual(self.calls, [])

    def test_no_save_switch_during_confirmation_prevents_mutation(self):
        def confirm(*args, **kwargs):
            self.runtime.NO_SAVE = True
            return True
        self.namespace['messagebox'].askyesno = confirm
        self.dialog.purge_all()
        self.assertEqual(self.calls, [])

    def test_failed_read_keeps_existing_view_and_uses_safe_error_text(self):
        before = list(self.dialog.listbox.rows)
        def fail():
            raise ValueError('private user content must not be shown')
        self.dialog.app.application.trash.entries = fail
        self.dialog.refresh()
        self.assertEqual(self.dialog.listbox.rows, before)
        self.assertNotIn('private user content', self.dialog.status.options['text'])
        self.assertIn('无法读取', self.dialog.status.options['text'])

    def test_write_error_is_visible_and_does_not_claim_success(self):
        def fail(ids):
            raise OSError('private path')
        self.dialog.app.recycle_restore = fail
        self.dialog.restore_selected()
        self.assertIn('操作未能完成', self.dialog.status.options['text'])
        self.assertNotIn('private path', self.dialog.status.options['text'])
        self.assertFalse(self.dialog._busy)
        self.assertEqual(len(self.dialog.listbox.rows), 2)

    def test_restore_service_rejection_shows_actionable_chinese_reason(self):
        def fail(ids):
            raise TrashError('触发词已存在，请先修改冲突的常用语。')
        self.dialog.app.recycle_restore = fail
        self.dialog.restore_selected()
        self.assertEqual(self.dialog.status.options['text'], '触发词已存在，请先修改冲突的常用语。')
        self.assertFalse(self.dialog._busy)

    def test_rejected_trash_format_shows_service_reason_without_changing_rows(self):
        def fail():
            raise TrashError('回收站格式无法识别，请先完整备份。')
        self.dialog.app.application.trash.entries = fail
        before = list(self.dialog.listbox.rows)
        self.dialog.refresh()
        self.assertEqual(self.dialog.listbox.rows, before)
        self.assertEqual(self.dialog.status.options['text'], '回收站格式无法识别，请先完整备份。')

    def test_empty_restore_result_refreshes_without_claiming_success(self):
        def stale(ids):
            self.rows.clear()
            return []
        self.dialog.app.recycle_restore = stale
        self.dialog.restore_selected()
        self.assertEqual(self.dialog.listbox.rows, [])
        self.assertIn('所选内容已改变', self.dialog.status.options['text'])
        self.assertNotIn('已恢复', self.dialog.status.options['text'])

    def test_expiration_runs_through_adapter_and_refreshes(self):
        self.dialog.expire()
        self.assertEqual(self.calls, [('expire', None)])

    def test_closed_window_ignores_refresh_and_mutations(self):
        self.dialog.close()
        self.dialog.refresh()
        self.dialog.restore_selected()
        self.dialog.purge_all()
        self.dialog.expire()
        self.assertEqual(self.calls, [])

    def test_close_cancels_timers_and_unbinds_only_its_scale_callback(self):
        self.dialog._jobs = dict(dpi='timer-one')
        self.dialog.close()
        self.dialog.close()
        self.assertEqual(self.dialog.win.cancelled, ['timer-one'])
        self.assertEqual(self.dialog._jobs, {})
        self.assertEqual(self.dialog.app.root.unbound,
                         [('<<ClawBoardUIScaleChanged>>', 'synthetic-binding')])


if __name__ == '__main__':
    unittest.main()
