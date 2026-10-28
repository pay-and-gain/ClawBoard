"""Complete backup UI; workers never read Tk or mutate the active library."""
import ctypes
from datetime import datetime
import math
import os
from pathlib import Path
from threading import Event
import time
import tkinter as tk
from tkinter import filedialog, messagebox
import tkinter.font as tkfont

from clawboard import config, runtime
from clawboard.backups import BackupService, BackupError, BackupCancelled
from clawboard.config import FONT, FONT_B, FONT_SM
from clawboard.restore_job import prepare_restore_job, launch_restore_job, cancel_restore_job
from clawboard.theme import T
from clawboard.widgets import ScrollFrame


class BackupWindow:
    """Inspect first, then hand an approved restore to a separate process."""

    def __init__(self, app):
        self.app = app
        self._base_dir = Path(app._store.path).absolute().parent
        self._service = BackupService(app._store.path,
                                      images_dir=app.application.image_store.directory)
        self._tasks = app.application.tasks
        self._key = ('complete-backup', id(self))
        self._closed = self._busy = False
        self._generation = 0
        self._cancel = Event()
        self._jobs = {}
        self._fonts = {}
        self._restore_job = None
        self._restoring = False
        self.preview = None
        self.win = tk.Toplevel(app.root)
        self.win.title('ClawBoard · 完整备份与恢复')
        self.win.transient(app.root)
        self.win.configure(bg=T['bg'])
        self._scale = self._window_scale(app.root)
        self.archive = tk.StringVar(master=self.win)
        self._archive_trace = self.archive.trace_add('write', self._archive_changed)
        self._build()
        self._fit(initial=True)
        self._metrics = self._remember_metrics(self.win)
        self._scale_binding = app.root.bind(
            '<<ClawBoardUIScaleChanged>>', lambda _: self._schedule('dpi', self._sync_scale), add='+')
        self.win.bind('<Configure>', self._configured, add='+')
        self.win.bind('<Destroy>', self._destroyed, add='+')
        self.win.bind('<Escape>', lambda _: self.close())
        self.win.protocol('WM_DELETE_WINDOW', self.close)
        self._schedule('dpi', self._sync_scale)

    def _px(self, value):
        return max(1, round(value * self._scale))

    def _font(self, template):
        key = tuple(template)
        if key not in self._fonts:
            font = tkfont.Font(self.win, font=template)
            font.configure(size=-self._px(abs(template[1]) * 96 / 72))
            self._fonts[key] = font
        return self._fonts[key]

    def _button(self, parent, text, command, primary=False):
        button = tk.Button(parent, text=text, command=command, font=self._font(FONT),
                           bg=T['acc'] if primary else T['card'],
                           fg=T.get('on_acc', '#fff') if primary else T['fg'],
                           activebackground=T['card_h'], activeforeground=T['fg'],
                           relief='flat', bd=0, highlightthickness=1,
                           highlightbackground=T['line'], highlightcolor=T['acc'],
                           padx=self._px(10), pady=self._px(6), takefocus=True)
        button.bind('<Return>', lambda _: (button.invoke(), 'break')[1])
        return button

    def _label(self, parent, text, bold=False):
        label = tk.Label(parent, text=text, bg=T['bg'], fg=T['fg'] if bold else T['fg2'],
                         font=self._font(FONT_B if bold else FONT_SM), anchor='w',
                         justify='left', wraplength=self._px(420))
        label.pack(fill='x', pady=self._px(5))
        label.bind('<Configure>', lambda event: label.configure(wraplength=max(1, event.width)))
        return label

    def _build(self):
        footer = tk.Frame(self.win, bg=T['bg'])
        footer.pack(side='top', fill='x', padx=self._px(14), pady=self._px(10))
        primary = tk.Frame(footer, bg=T['bg'])
        primary.pack(fill='x')
        self.close_button = self._button(primary, '关闭', self.close)
        self.close_button.pack(side='right')
        self.create_button = self._button(primary, '创建备份…', self.create_backup, primary=True)
        self.create_button.pack(side='left')
        actions = tk.Frame(footer, bg=T['bg'])
        actions.pack(fill='x', pady=(self._px(6), 0))
        self.inspect_button = self._button(actions, '检查备份', self.inspect_archive)
        self.inspect_button.pack(side='left')
        self.restore_button = self._button(actions, '恢复此备份…', self.confirm_restore)
        self.restore_button.pack(side='right')
        self.status = tk.Label(footer, text='选择操作后会在这里显示结果', bg=T['bg'],
                               fg=T['fg2'], font=self._font(FONT_SM), anchor='w',
                               justify='left', wraplength=self._px(300))
        self.status.pack(fill='x', pady=(self._px(6), 0))
        self.status.bind('<Configure>', lambda e: self.status.configure(wraplength=max(1, e.width)))
        self.body = ScrollFrame(self.win)
        self.body.canvas.configure(width=1, height=1)
        self.body.pack(fill='both', expand=True, padx=self._px(16), pady=self._px(10))
        content = self.body.inner
        self._label(content, '完整备份与恢复', bold=True)
        self._label(content, '完整备份包含当前资料、设置与记录引用的图片。普通 JSON 导出不能用于恢复。')
        self._label(content, '备份包为明文，请妥善保存。文件类型记录只保留原路径，不复制所引用文件的正文。')
        self._label(content, '选择完整备份包（ZIP）', bold=True)
        path_row = tk.Frame(content, bg=T['bg'])
        path_row.pack(fill='x', pady=self._px(5))
        self.select_button = self._button(path_row, '选择…', self.choose_archive)
        self.select_button.pack(side='right', padx=(self._px(8), 0))
        self.path_entry = tk.Entry(path_row, textvariable=self.archive, font=self._font(FONT),
                                   bg=T['card'], fg=T['fg'], insertbackground=T['fg'],
                                   relief='flat', bd=0, highlightthickness=1,
                                   highlightbackground=T['line'], highlightcolor=T['acc'])
        self.path_entry.pack(fill='x', expand=True, ipady=self._px(6))
        self.preview_label = self._label(content, '尚未检查备份包。检查通过后才能恢复。')
        self._controls = (self.create_button, self.select_button, self.inspect_button, self.path_entry)
        self._paint_busy()
        self.body.bind_wheel_tree()
        self._bind_focus_reveal(content)

    def _bind_focus_reveal(self, parent):
        for widget in parent.winfo_children():
            widget.bind('<FocusIn>', self._reveal_focused, add='+')
            self._bind_focus_reveal(widget)

    def _reveal_focused(self, event):
        canvas = self.body.canvas
        canvas.update_idletasks()
        extent = canvas.bbox('all')
        if not extent:
            return
        top = canvas.canvasy(0)
        y = event.widget.winfo_rooty() - canvas.winfo_rooty() + top
        bottom = y + event.widget.winfo_height()
        desired = y - self._px(6) if y < top else bottom - canvas.winfo_height() + self._px(6)
        if y < top or bottom > top + canvas.winfo_height():
            step = max(1, int(canvas.cget('yscrollincrement')))
            desired = (math.floor(desired / step) if desired < top else math.ceil(desired / step)) * step
            canvas.yview_moveto(max(0, desired) / max(1, extent[3]))

    def _alive(self):
        if self._closed:
            return False
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def _guard(self):
        if runtime.NO_SAVE:
            if self._alive():
                self._status('自测模式不选择文件、不创建备份或启动恢复')
            return False
        if not self._alive() or self._busy:
            return False
        # A failed revocation must never be replaced by a second live ticket.
        return self._cancel_restore()

    def _status(self, text, error=False):
        if self._alive():
            self.status.configure(text=text, fg=T['danger'] if error else T['fg2'])

    def _paint_busy(self):
        for widget in self._controls:
            widget.configure(state='disabled' if self._busy else 'normal')
        self.restore_button.configure(state='normal' if self.preview and not self._busy else 'disabled')

    def _archive_changed(self, *_):
        if getattr(self, '_setting_path', False):
            return
        self.preview = None
        if hasattr(self, 'preview_label') and self._alive():
            self.preview_label.configure(text='文件路径已更改，请重新检查备份包。')
            self._paint_busy()

    @staticmethod
    def _size(size):
        if size < 1024:
            return '%d 字节' % size
        unit, amount = ('MB', size / 1048576) if size >= 1048576 else ('KB', size / 1024)
        return '%.1f %s（%s 字节）' % (amount, unit, format(size, ','))

    @staticmethod
    def _created_time(value):
        try:
            return datetime.fromisoformat(value).astimezone().strftime('%Y-%m-%d %H:%M:%S（本机时间）')
        except (ValueError, TypeError, OverflowError, OSError):
            text = str(value)
            return text[:64] + ('…' if len(text) > 64 else '')

    def _show_preview(self, preview):
        self.preview = preview
        self._setting_path = True
        try:
            self.archive.set(str(preview.archive))
        finally:
            self._setting_path = False
        self.preview_label.configure(text=(
            '备份时间：%s\n程序版本：%s\n剪贴板历史：%d 条\n常用语：%d 条\n'
            '回收站：%d 条\n图片：%d 张\n内容大小：%s\n外部文件引用：%d 条（只保留路径）'
            % (self._created_time(preview.created_at), preview.app_version, preview.clip_count,
               preview.phrase_count, preview.trash_count, preview.image_count, self._size(preview.total_bytes),
               preview.external_file_count)))

    def choose_archive(self):
        if not self._guard():
            return
        path = filedialog.askopenfilename(parent=self.win, title='选择 ClawBoard 完整备份包',
            initialdir=str(self._base_dir), filetypes=[('完整备份包', '*.zip')])
        if path and self._guard():
            self.archive.set(path)
            self.inspect_archive()

    def create_backup(self):
        if not self._guard():
            return
        path = filedialog.asksaveasfilename(parent=self.win, title='保存完整备份包',
            initialdir=str(self._base_dir), initialfile=time.strftime('ClawBoard-backup-%Y%m%d-%H%M%S.zip'),
            defaultextension='.zip', filetypes=[('完整备份包', '*.zip')])
        if not path or not self._guard():
            return
        try:
            if not self.app.save_now():
                self._status('创建未开始：请先解决当前资料的保存问题', error=True)
                return
        except Exception:
            self._status('创建未开始：当前资料未能保存', error=True)
            return
        if self._guard():
            self._submit('create', path)

    def inspect_archive(self):
        if not self._guard():
            return
        path = self.archive.get().strip()
        if not path:
            self._status('请先选择完整备份包', error=True)
            return
        self.preview = None
        self.preview_label.configure(text='正在检查所选备份包…')
        self._submit('inspect', path)

    def _submit(self, operation, path):
        self._generation += 1
        generation = self._generation
        self._cancel.set()
        self._cancel = cancel = Event()
        self._busy = True
        self._paint_busy()
        self._status('正在创建完整备份…' if operation == 'create' else '正在检查备份包…')

        def current():
            return self._alive() and generation == self._generation and not cancel.is_set()

        def done(preview):
            if current():
                self._busy = False
                self._show_preview(preview)
                self._paint_busy()
                self._status('完整备份已创建' if operation == 'create' else '检查通过，可以恢复此备份')

        def failed(error):
            if current():
                self._busy = False
                self._paint_busy()
                text = str(error) if isinstance(error, (BackupError, BackupCancelled)) else '操作未完成，请检查文件和目录后重试'
                self._status(text, error=True)

        future = self._tasks.submit(getattr(self._service, operation), path, cancelled=cancel.is_set,
                                    key=self._key, on_result=done, on_error=failed)
        if future is None:
            self._busy = False
            self._paint_busy()
            self._status('后台任务繁忙，请稍后重试', error=True)

    def confirm_restore(self):
        if not self._guard() or self.preview is None:
            return
        preview = self.preview
        if Path(self.archive.get().strip()).absolute() != Path(preview.archive).absolute():
            self._archive_changed()
            return
        text = ('将用所选完整备份替换当前资料和设置。\n'
                '恢复前会自动完整备份当前库。\n'
                'ClawBoard 将正常退出，恢复完成后重新启动。\n'
                '外部文件仅保留原路径，备份不包含其正文。\n\n确定恢复此备份吗？')
        if messagebox.askyesno('确认恢复完整备份', text, parent=self.win, icon='warning', default='no'):
            self._start_restore(preview)

    def _cancel_restore(self):
        if self._restore_job is None:
            return True
        try:
            cancel_restore_job(self._restore_job, base_dir=self._base_dir)
        except Exception:
            self._status('恢复未开始，撤销请求失败。请保持程序打开并检查数据目录。', error=True)
            return False
        self._restore_job = None
        return True

    def _root_exists(self):
        try:
            return bool(self.app.root.winfo_exists())
        except tk.TclError:
            return False

    def _start_restore(self, preview):
        if not self._guard() or self.preview is not preview:
            return
        self._busy = self._restoring = True
        self._paint_busy()
        try:
            self._restore_job = prepare_restore_job(self._base_dir, preview.archive, preview.sha256)
            if runtime.NO_SAVE:
                raise BackupCancelled('自测模式不会启动恢复')
            launch_restore_job(self._restore_job)
            if runtime.NO_SAVE:
                raise BackupCancelled('自测模式不会退出程序或启动恢复')
            self.app.quit_app()
        except Exception:
            if self._cancel_restore():
                self._status('恢复未开始，请检查备份文件和当前资料的保存状态', error=True)
        else:
            # quit_app deliberately keeps the process open when its writer
            # cannot flush. Revoke now so a later ordinary exit cannot restore.
            if self._root_exists() and self._cancel_restore():
                self._status('恢复未开始：原程序未能正常退出，请先解决保存问题', error=True)
        finally:
            self._restoring = False
            if self._alive():
                self._busy = False
                self._paint_busy()

    def _window_scale(self, window=None):
        try:
            from clawboard.windows_system import dpi_scale
            return dpi_scale(window or self.win) * config.UI_SCALE
        except (ImportError, AttributeError, tk.TclError):
            return config.DPI_SCALE * config.UI_SCALE

    def _area(self, initial=False):
        target = self.app.root if initial else self.win
        try:
            from clawboard.windows_api import MONITORINFO, MONITOR_DEFAULTTONEAREST, u32
            from clawboard.windows_geometry import top_hwnd
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(info)
            monitor = u32.MonitorFromWindow(top_hwnd(target), MONITOR_DEFAULTTONEAREST)
            if u32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                r = info.rcWork
                return r.left, r.top, r.right, r.bottom
        except (ImportError, AttributeError, OSError):
            pass
        return 0, 0, target.winfo_screenwidth(), target.winfo_screenheight()

    def _fit(self, initial=False, ratio=1):
        self.win.update_idletasks()
        left, top, right, bottom = self._area(initial)
        margin = self._px(8)
        edge = max(0, self.win.winfo_rootx() - self.win.winfo_x())
        extra_w = edge * 2
        extra_h = max(0, self.win.winfo_rooty() - self.win.winfo_y()) + edge
        aw = max(1, right - left - margin * 2 - extra_w)
        ah = max(1, bottom - top - margin * 2 - extra_h)
        minimum_w, minimum_h = min(aw, self._px(320)), min(ah, self._px(300))
        width = min(aw, max(minimum_w, self._px(560) if initial else round(self.win.winfo_width() * ratio)))
        height = min(ah, max(minimum_h, self._px(640) if initial else round(self.win.winfo_height() * ratio)))
        x = self.app.root.winfo_rootx() + self._px(18) if initial else self.win.winfo_x()
        y = self.app.root.winfo_rooty() + self._px(18) if initial else self.win.winfo_y()
        x = max(left + margin, min(x, right - width - extra_w - margin))
        y = max(top + margin, min(y, bottom - height - extra_h - margin))
        self.win.minsize(1, 1)
        self.win.geometry('%dx%d%+d%+d' % (width, height, x, y))
        self.win.minsize(minimum_w, minimum_h)

    def _remember_metrics(self, parent):
        result = []
        for widget in parent.winfo_children():
            options = {}
            for key in ('padx', 'pady', 'highlightthickness', 'yscrollincrement'):
                if key in widget.keys():
                    options[key] = float(widget.cget(key)) / self._scale
            if isinstance(widget, tk.Canvas) and 'width' in widget.keys():
                options['width'] = float(widget.cget('width')) / self._scale
            manager, spacing = widget.winfo_manager(), {}
            if manager == 'pack':
                for key in ('padx', 'pady', 'ipadx', 'ipady'):
                    value = widget.pack_info().get(key, 0)
                    values = value if isinstance(value, (tuple, list)) else self.win.tk.splitlist(str(value))
                    spacing[key] = tuple(float(part) / self._scale for part in values)
            result.append((widget, options, spacing))
            result.extend(self._remember_metrics(widget))
        return result

    def _schedule(self, key, callback, delay=120):
        previous = self._jobs.pop(key, None)
        if previous:
            self.win.after_cancel(previous)
        if not self._closed:
            def run():
                self._jobs.pop(key, None)
                if self._alive():
                    callback()
            self._jobs[key] = self.win.after(delay, run)

    def _configured(self, event):
        if event.widget is self.win and not self._closed:
            self._schedule('dpi', self._sync_scale)

    def _sync_scale(self):
        if os.name == 'nt':
            from clawboard.windows_api import u32
            if u32.GetAsyncKeyState(1) & 0x8000:
                self._schedule('dpi', self._sync_scale)
                return
        new_scale = self._window_scale()
        if abs(new_scale - self._scale) < .001:
            return
        ratio, self._scale = new_scale / self._scale, new_scale
        scroll = self.body.canvas.yview()[0]
        for template, font in self._fonts.items():
            font.configure(size=-self._px(abs(template[1]) * 96 / 72))
        for widget, options, spacing in self._metrics:
            widget.configure(**{key: round(value * new_scale) for key, value in options.items()})
            if hasattr(widget, 'w') and isinstance(widget, tk.Canvas):
                widget.w = round(float(widget.cget('width')))
            if spacing:
                widget.pack_configure(**{key: tuple(round(value * new_scale) for value in values)
                                         for key, values in spacing.items()})
        self._fit(ratio=ratio)
        self.win.update_idletasks()
        self.body._on_inner()
        self.body.canvas.yview_moveto(scroll)

    def _dispose(self):
        if self._closed:
            return
        self._closed = True
        self._generation += 1
        self._cancel.set()
        self._tasks.invalidate(self._key)
        for job in self._jobs.values():
            try:
                self.win.after_cancel(job)
            except tk.TclError:
                pass
        self._jobs.clear()
        trace = getattr(self, '_archive_trace', None)
        if trace:
            try:
                self.archive.trace_remove('write', trace)
            except tk.TclError:
                pass
        self._archive_trace = None
        try:
            self.app.root.unbind('<<ClawBoardUIScaleChanged>>', self._scale_binding)
        except tk.TclError:
            pass
        self._scale_binding = None

    def _destroyed(self, event):
        if event.widget is self.win:
            self._dispose()

    def close(self):
        if self._closed or self._restoring:
            return
        if not self._cancel_restore():
            return
        self._dispose()
        self.win.destroy()
