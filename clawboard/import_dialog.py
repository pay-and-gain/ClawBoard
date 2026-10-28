"""Merge-import UI: review a detached snapshot, then use the idle helper."""
from copy import deepcopy
from pathlib import Path
from threading import Event
import tkinter as tk
from tkinter import filedialog, messagebox

from clawboard import runtime
from clawboard.backup_dialog import BackupWindow
from clawboard.backups import BackupError, BackupCancelled
from clawboard.config import FONT
from clawboard.import_merge import plan_merge
from clawboard.import_service import ImportService
from clawboard.privacy import display_text
from clawboard.restore_job import (
    prepare_import_job, launch_restore_job, cancel_restore_job,
)
from clawboard.theme import T
from clawboard.widgets import ScrollFrame


class ImportWindow(BackupWindow):
    """Share native metrics/lifecycle, without constructing restore controls."""

    _READY = frozenset(('ready', 'trigger_disabled'))
    _LABELS = dict(ready='可导入', duplicate='重复 · 跳过', blocked='不可导入',
                   trigger_disabled='可导入 · 触发词停用')

    def __init__(self, app):
        self.app = app
        self._base_dir = Path(app._store.path).absolute().parent
        self._service = ImportService(app._store.path,
            images_dir=app.application.image_store.directory)
        self._tasks, self._key = app.application.tasks, ('merge-import', id(self))
        self._closed = self._busy = self._restoring = False
        self._generation, self._restore_job = 0, None
        self._cancel, self._jobs, self._fonts = Event(), {}, {}
        self.preview, self._snapshot, self._rows, self._row_status = None, None, [], {}
        self.win = tk.Toplevel(app.root)
        self.win.title('ClawBoard · 内容合并导入')
        self.win.transient(app.root)
        self.win.configure(bg=T['bg'])
        self._scale = self._window_scale(app.root)
        self.archive = tk.StringVar(master=self.win)
        self._archive_trace = self.archive.trace_add('write', self._archive_changed)
        self._build()
        self._fit(initial=True)
        self._metrics = self._remember_metrics(self.win)
        self._scale_binding = app.root.bind('<<ClawBoardUIScaleChanged>>',
            lambda _: self._schedule('dpi', self._sync_scale), add='+')
        self.win.bind('<Configure>', self._configured, add='+')
        self.win.bind('<Destroy>', self._destroyed, add='+')
        self.win.bind('<Escape>', lambda _: self.close())
        self.win.protocol('WM_DELETE_WINDOW', self.close)
        self._schedule('dpi', self._sync_scale)

    def _build(self):
        footer = tk.Frame(self.win, bg=T['bg'])
        footer.pack(side='top', fill='x', padx=self._px(14), pady=self._px(10))
        self.status = self._label(footer, '选择导出文件或完整备份包，先预览再导入。')
        actions = tk.Frame(footer, bg=T['bg'])
        actions.pack(fill='x')
        self.close_button = self._button(actions, '取消', self.close)
        self.close_button.pack(side='right')
        self.import_button = self._button(actions, '导入所选…', self.confirm_import, primary=True)
        self.import_button.pack(side='left')
        self.body = ScrollFrame(self.win)
        self.body.canvas.configure(width=1, height=1)
        self.body.pack(fill='both', expand=True, padx=self._px(16), pady=self._px(10))
        content = self.body.inner
        self._label(content, '内容合并导入', bold=True)
        self._label(content, '只加入选中的历史和常用语，保留现有内容、设置与回收站。重复内容跳过；同名分组另建“导入”分组；冲突触发词停用并提示。')
        self._label(content, 'JSON 导出不包含图片正文，缺图项不能导入；完整 ZIP 备份可携带图片。外部文件记录只保留路径，不复制文件正文。')
        path_row = tk.Frame(content, bg=T['bg'])
        path_row.pack(fill='x', pady=self._px(5))
        self.select_button = self._button(path_row, '选择…', self.choose_archive)
        self.select_button.pack(side='right', padx=(self._px(8), 0))
        self.path_entry = tk.Entry(path_row, textvariable=self.archive, font=self._font(FONT),
            bg=T['card'], fg=T['fg'], insertbackground=T['fg'], relief='flat', bd=0,
            highlightthickness=1, highlightbackground=T['line'], highlightcolor=T['acc'])
        self.path_entry.pack(fill='x', expand=True, ipady=self._px(6))
        self.inspect_button = self._button(content, '检查并预览', self.inspect_archive)
        self.inspect_button.pack(anchor='w', pady=self._px(4))
        self.summary = self._label(content, '尚未检查文件。')
        tools = tk.Frame(content, bg=T['bg'])
        tools.pack(fill='x')
        self.all_button = self._button(tools, '选中可导入项', self.select_ready)
        self.all_button.pack(side='left')
        self.none_button = self._button(tools, '取消全选', self.select_none)
        self.none_button.pack(side='left', padx=(self._px(6), 0))
        self._label(content, '按住 Ctrl 可多选，Shift 可连续选择；重复项会跳过。')
        listing = tk.Frame(content, bg=T['bg'])
        listing.pack(fill='x', pady=self._px(5))
        self.listbox = tk.Listbox(listing, width=1, height=7, font=self._font(FONT),
            bg=T['card'], fg=T['fg'], selectbackground=T['acc'],
            selectforeground=T.get('on_acc', '#fff'), relief='flat', bd=0,
            highlightthickness=1, highlightbackground=T['line'], highlightcolor=T['acc'],
            selectmode='extended', exportselection=False, activestyle='dotbox')
        scroll = tk.Scrollbar(listing, orient='vertical', command=self.listbox.yview)
        scroll.pack(side='right', fill='y')
        self.listbox.pack(fill='x', expand=True)
        self.listbox.configure(yscrollcommand=scroll.set)
        self.listbox.bind('<<ListboxSelect>>', self._selection_changed)
        self.listbox.bind('<Return>', self._focus_preview)
        self.listbox.bind('<Double-Button-1>', self._focus_preview)
        self._label(content, '完整内容预览（按当前隐私设置遮罩）', bold=True)
        view = tk.Frame(content, bg=T['bg'])
        view.pack(fill='x', pady=self._px(5))
        self.preview_text = tk.Text(view, width=1, height=9, wrap='word',
            font=self._font(FONT), bg=T['card'], fg=T['fg'], relief='flat', bd=0,
            highlightthickness=1, highlightbackground=T['line'], highlightcolor=T['acc'],
            state='disabled', takefocus=True)
        scroll = tk.Scrollbar(view, orient='vertical', command=self.preview_text.yview)
        scroll.pack(side='right', fill='y')
        self.preview_text.pack(fill='x', expand=True)
        self.preview_text.configure(yscrollcommand=scroll.set)
        self._label(content, '确认后先备份当前库，再正常退出并重新打开。导入时会再次检查最新资料；容量不足时取消，不删除旧记录或修改设置。')
        self._controls = (self.select_button, self.path_entry, self.inspect_button,
                          self.all_button, self.none_button, self.listbox)
        self._paint_busy()
        self.body.bind_wheel_tree()
        self._bind_focus_reveal(content)

    def _guard(self):
        if runtime.NO_SAVE:
            self._status('自测模式不选择文件、不提交导入或退出程序')
            return False
        if not self._alive() or self._busy:
            return False
        if getattr(self.app._store, 'recovery_required', False):
            self._status('当前资料处于只读保护，请先解决保存问题后再导入。', error=True)
            return False
        return self._cancel_restore()

    def _paint_busy(self):
        for widget in self._controls:
            widget.configure(state='disabled' if self._busy else 'normal')
        enabled = self.preview is not None and bool(self._selection_keys()) and not self._busy
        self.import_button.configure(state='normal' if enabled else 'disabled')

    def _archive_changed(self, *_):
        if getattr(self, '_setting_path', False):
            return
        # Programmatic edits also revoke a worker's ownership of this preview.
        self._generation += 1
        self._cancel.set()
        self._tasks.invalidate(self._key)
        self._busy = False
        self.preview = self._snapshot = None
        self._rows, self._row_status = [], {}
        if hasattr(self, 'summary') and self._alive():
            self.listbox.delete(0, 'end')
            self.summary.configure(text='文件路径已更改，请重新检查。')
            self._write_preview('尚未检查文件。')
            self._paint_busy()

    def choose_archive(self):
        if not self._guard():
            return
        path = filedialog.askopenfilename(parent=self.win, title='选择 ClawBoard 导出或备份',
            initialdir=str(self._base_dir),
            filetypes=[('ClawBoard 导出或备份', '*.json *.zip'), ('JSON 导出', '*.json'),
                       ('完整备份包', '*.zip')])
        if path and self._guard():
            self.archive.set(path)
            self.inspect_archive()

    def inspect_archive(self):
        if not self._guard():
            return
        path = self.archive.get().strip()
        if not path:
            self._status('请先选择 JSON 导出或 ZIP 完整备份。', error=True)
            return
        self.preview = None
        self._snapshot = deepcopy(self.app.data)
        self._rows, self._row_status = [], {}
        self.listbox.delete(0, 'end')
        self._write_preview('正在检查文件…')
        self._submit_inspect(path, self._snapshot)

    def _submit_inspect(self, path, snapshot):
        self._generation += 1
        generation = self._generation
        self._cancel.set()
        self._cancel = cancel = Event()
        self._busy = True
        self._paint_busy()
        self._status('正在检查内容、重复项和图片…')

        def current():
            return self._alive() and generation == self._generation and not cancel.is_set()

        def done(preview):
            if current():
                self._busy = False
                self._show_preview(preview)

        def failed(error):
            if current():
                self._busy = False
                self.preview = None
                self._paint_busy()
                self._status(str(error) if isinstance(error, BackupError)
                             else '检查未完成，请核对文件后重试。', error=True)

        task = self._tasks.submit(self._service.inspect, path, snapshot,
            cancelled=cancel.is_set, key=self._key, on_result=done, on_error=failed)
        if task is None:
            self._busy = False
            self._paint_busy()
            self._status('后台任务繁忙，请稍后重试。', error=True)

    def _masked(self, text):
        # Imported mask_off/sens fields are untrusted display preferences.
        return display_text(text, masked=bool(self.app.st.get('mask_sensitive', True)))

    def _show_preview(self, preview):
        self.preview = preview
        self._setting_path = True
        try:
            self.archive.set(str(preview.source.path))
        finally:
            self._setting_path = False
        self._rows = list(preview.source.entries)
        self._row_status = {row.key: row for row in preview.plan.rows}
        self.listbox.delete(0, 'end')
        for entry in self._rows:
            row = self._row_status.get(entry.key)
            status = row.status if row else 'blocked'
            body = self._masked(entry.item.get('text', '')[:632])[:120]
            body = body.replace('\r', ' ').replace('\n', '  ') or '（空内容）'
            location = '历史' if entry.section == 'clip' else '常用语 · ' + self._masked(entry.group_name)[:60]
            self.listbox.insert('end', '%s | %s | %s' % (
                self._LABELS.get(status, '不可导入'), location, body))
        self.select_ready()
        if preview.plan.error:
            self._status(preview.plan.error + ' 可减少选择后重试。', error=True)
        else:
            self._status('检查完成，请选择要加入的内容。')

    def _selection_keys(self):
        return tuple(self._rows[int(index)].key for index in self.listbox.curselection()
                     if 0 <= int(index) < len(self._rows))

    def select_ready(self):
        if not self._alive() or self._busy:
            return
        self.listbox.selection_clear(0, 'end')
        for index, entry in enumerate(self._rows):
            row = self._row_status.get(entry.key)
            if row and row.status in self._READY:
                self.listbox.selection_set(index)
        self._selection_changed()

    def select_none(self):
        if self._alive() and not self._busy:
            self.listbox.selection_clear(0, 'end')
            self._selection_changed()

    def _write_preview(self, text):
        self.preview_text.configure(state='normal')
        self.preview_text.delete('1.0', 'end')
        self.preview_text.insert('1.0', text)
        self.preview_text.configure(state='disabled')

    def _selection_changed(self, _event=None):
        if not self._alive():
            return
        keys = self._selection_keys()
        entry = next((row for row in self._rows if row.key in keys), None)
        if entry is None:
            self._write_preview('选择一项可查看完整内容；可多选导入。')
        else:
            row = self._row_status.get(entry.key)
            location = '剪贴板历史' if entry.section == 'clip' else '常用语 · ' + self._masked(entry.group_name)
            self._write_preview('位置：%s\n状态：%s\n\n%s' % (
                location, row.message if row else '不可导入', self._masked(entry.item.get('text', ''))))
        if self.preview is not None:
            plan = self.preview.plan
            blocked = sum(row.status == 'blocked' for row in plan.rows)
            self.summary.configure(text='共%d项，重复%d项，不可导入%d项，触发词停用%d项；已选%d项。'
                % (len(self._rows), plan.duplicate_count, blocked, plan.disabled_trigger_count, len(keys)))
        self._paint_busy()

    def _focus_preview(self, _event=None):
        self._selection_changed()
        self.preview_text.focus_set()
        return 'break'

    def confirm_import(self):
        if not self._guard() or self.preview is None:
            return
        preview, keys = self.preview, self._selection_keys()
        if Path(self.archive.get().strip()).absolute() != Path(preview.source.path).absolute():
            self._archive_changed()
            return
        if not keys:
            return
        try:
            plan = plan_merge(deepcopy(self.app.data), preview.source, keys,
                current_image_hashes=preview.current_image_hashes)
        except (BackupError, ValueError):
            self._status('所选内容需要重新检查，请重新预览后再导入。', error=True)
            return
        if plan.error or not plan.imported_count:
            self._status(plan.error or '所选内容均已存在，没有需要加入的资料。', error=True)
            return
        text = ('将加入%d项，跳过%d项重复内容，停用%d项冲突触发词。\n'
                '先完整备份当前库，保留现有资料、设置和回收站。\n'
                '程序将正常保存、短暂退出并重新打开。\n'
                '导入时再次检查最新资料；容量不足则取消，不删除旧记录。\n'
                '外部文件记录仅保留路径，不包含文件正文。\n\n确定导入所选内容吗？'
                % (plan.imported_count, plan.duplicate_count, plan.disabled_trigger_count))
        if messagebox.askyesno('确认内容合并导入', text, parent=self.win, default='no'):
            self._start_import(preview, keys)

    def _cancel_restore(self):
        if self._restore_job is None:
            return True
        try:
            cancel_restore_job(self._restore_job, base_dir=self._base_dir)
        except Exception:
            self._status('导入未开始，撤销请求失败。请保持程序打开并检查数据目录。', error=True)
            return False
        self._restore_job = None
        return True

    def _start_import(self, preview, keys):
        if (not self._guard() or self.preview is not preview
                or self._selection_keys() != keys):
            return
        self._busy = self._restoring = True
        self._paint_busy()
        try:
            self._restore_job = prepare_import_job(self._base_dir, preview.source.path,
                                                   preview.source.sha256, keys)
            if runtime.NO_SAVE:
                raise BackupCancelled('自测模式不会启动导入')
            launch_restore_job(self._restore_job)
            if runtime.NO_SAVE:
                raise BackupCancelled('自测模式不会退出或启动导入')
            self.app.quit_app()
        except Exception:
            if self._cancel_restore():
                self._status('导入未开始，请检查文件和当前资料保存状态。', error=True)
        else:
            # A later ordinary quit must not unexpectedly consume a stale ticket.
            if self._root_exists() and self._cancel_restore():
                self._status('导入未开始：原程序未能正常退出，请先解决保存问题。', error=True)
        finally:
            self._restoring = False
            if self._alive():
                self._busy = False
                self._paint_busy()
