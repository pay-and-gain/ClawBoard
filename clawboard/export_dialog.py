"""Tk export adapter; workers receive only copied records and a destination."""
import os
import ctypes
import tkinter as tk
from copy import deepcopy
from clawboard import runtime
from threading import Event
from clawboard.config import BASE_DIR, FONT, FONT_B, FONT_SM, scaled
from clawboard.theme import T
from clawboard.widgets import ScrollFrame, dark_top, safe_release
from clawboard.exports import write_items, new_export_path


class ExportDialog:
    """F5：把历史导出成 TXT / CSV / JSON / Markdown"""

    def __init__(self, app):
        self.app = app
        self._closed = False
        self._export_pending = False
        self._export_cancel = Event()
        self._export_key = ('export', id(self))
        self._focus_job = self._fit_job = None
        ids = set(app.vlist.multi)
        items = [x for x in app.vlist.items if x['id'] in ids] if ids else list(app.vlist.items)
        self.items = items
        if not items:
            app.tip('没有可导出的内容')
            return
        self.win = tk.Toplevel(app.root)
        self.win.transient(app.root)
        self._bar = dark_top(self.win, '批量导出')
        self._bar.configure(height=scaled(36))
        self.win.attributes('-topmost', True)
        self.win.protocol('WM_DELETE_WINDOW', self.close)
        self.win.bind('<Destroy>', self._destroyed, add='+')
        self.win.bind('<Escape>', lambda e: self.close())
        self._focus_job = self.win.after(60, self._focus_later)
        # Reserve actions first so constrained work areas only shrink the body.
        btns = tk.Frame(self.win, bg=T['bg'])
        btns.pack(side='bottom', fill='x', padx=scaled(14), pady=scaled(10))
        self._body = ScrollFrame(self.win)
        self._body.canvas.configure(width=1, height=1)
        self._body.pack(fill='both', expand=True, padx=scaled(14), pady=scaled(10))
        body = self._body.inner
        tk.Label(body, text='共 %d 条待导出（多选优先，否则导出当前筛选结果）'
                 % len(items), bg=T['bg'], fg=T['fg'], font=FONT, anchor='w',
                 justify='left', wraplength=scaled(440)).pack(fill='x')
        self.fmt = tk.StringVar(value='txt')
        self.rows = []
        for v, label in (('txt', 'TXT（序号/时间/来源/内容）'),
                         ('csv', 'CSV（Excel 友好，带 BOM）'),
                         ('json', 'JSON（保留所选记录字段）'),
                         ('md', 'Markdown（适合归档笔记）')):
            r = tk.Frame(body, bg=T['bg'])
            r.pack(fill='x', pady=2)
            dot = tk.Label(r, text='○', bg=T['bg'], fg=T['fg2'], font=FONT, cursor='hand2')
            dot.pack(side='left')
            tk.Label(r, text=label, bg=T['bg'], fg=T['fg'], font=FONT_SM,
                     cursor='hand2').pack(side='left')

            def pick(_, v=v):
                self.fmt.set(v)
                self.paint()
            for w in (dot, r):
                w.bind('<Button-1>', pick)
            r._dot = dot
            r._v = v
            self.rows.append(r)
        self.paint()
        tk.Label(body, text='JSON 保留所选记录字段，不包含设置、图片本体或所引用文件的正文。'
                 '\n整库恢复请使用设置中的完整备份包。',
                 bg=T['bg'], fg=T['fg2'], font=FONT_SM, anchor='w',
                 justify='left', wraplength=scaled(440)).pack(fill='x', pady=(6, 0))
        sens = sum(1 for x in items if x.get('sens'))
        if sens:
            tk.Label(body, text='⚠ 其中 %d 条含敏感内容，导出为明文' % sens,
                     bg=T['bg'], fg=T['danger'], font=FONT_SM, anchor='w').pack(fill='x', pady=4)
        b = tk.Label(btns, text='导出到本目录', bg=T['acc'], fg=T.get('on_acc', '#fff'), font=FONT_B,
                     padx=14, pady=5, cursor='hand2')
        b.pack(side='right')
        b.bind('<Button-1>', lambda e: self.do_export())
        self._export_button = b
        b2 = tk.Label(btns, text='取消', bg=T['card_h'], fg=T['fg'], font=FONT,
                      padx=14, pady=5, cursor='hand2')
        b2.pack(side='right', padx=(0, 6))
        b2.bind('<Button-1>', lambda e: self.close())
        self._cancel_button = b2
        self._body.bind_wheel_tree()
        self._fit_window(btns)
        # The first native map can reset a Toplevel's position on another DPI.
        self._fit_job = self.app.root.after(80, lambda: self._fit_later(btns))

    def _focus_later(self):
        self._focus_job = None
        if self._alive():
            self.win.lift()
            self.win.focus_force()

    def _fit_later(self, footer):
        self._fit_job = None
        if self._alive():
            self._fit_window(footer)

    def _cancel_window_jobs(self):
        for owner, name in ((self.win, '_focus_job'), (self.app.root, '_fit_job')):
            job = getattr(self, name, None)
            setattr(self, name, None)
            if job:
                try:
                    owner.after_cancel(job)
                except tk.TclError:
                    pass

    def _fit_window(self, footer):
        self.win.update_idletasks()
        parent = self.app.root
        area = (0, 0, parent.winfo_screenwidth(), parent.winfo_screenheight())
        try:
            from clawboard.windows_api import u32, MONITORINFO, MONITOR_DEFAULTTONEAREST
            from clawboard.windows_geometry import top_hwnd
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(info)
            monitor = u32.MonitorFromWindow(top_hwnd(parent), MONITOR_DEFAULTTONEAREST)
            if u32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                r = info.rcWork
                area = (r.left, r.top, r.right, r.bottom)
        except (ImportError, AttributeError, OSError):
            pass
        left, top, right, bottom = area
        margin = scaled(8)
        width = min(right - left - margin * 2, max(scaled(480),
                    self._body.inner.winfo_reqwidth() + scaled(36),
                    footer.winfo_reqwidth() + scaled(28)))
        height = min(bottom - top - margin * 2, self._bar.winfo_reqheight()
                     + self._body.inner.winfo_reqheight() + footer.winfo_reqheight() + scaled(40))
        x = max(left + margin, min(parent.winfo_rootx() + (parent.winfo_width() - width) // 2,
                                  right - width - margin))
        y = max(top + margin, min(parent.winfo_rooty() + (parent.winfo_height() - height) // 2,
                                 bottom - height - margin))
        self.win.geometry('%dx%d%+d%+d' % (max(1, width), max(1, height), x, y))

    def paint(self):
        cur = self.fmt.get()
        for r in self.rows:
            r._dot.configure(text='●' if r._v == cur else '○',
                             fg=T['acc'] if r._v == cur else T['fg2'])

    def _alive(self):
        if getattr(self, '_closed', False):
            return False
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def _destroyed(self, event):
        if event.widget is self.win:
            self._cancel_window_jobs()
            self._closed = True
            self._export_cancel.set()
            self.app.application.tasks.invalidate(self._export_key)

    def close(self):
        if getattr(self, '_closed', False):
            return
        self._closed = True
        self._cancel_window_jobs()
        self._export_cancel.set()
        self.app.application.tasks.invalidate(self._export_key)
        safe_release(self.win)
        self.win.destroy()

    def do_export(self):
        if runtime.NO_SAVE:
            self.app.tip('自测模式不写导出文件')
            return
        if not self._alive() or self._export_pending:
            return
        fmt = self.fmt.get()
        # Capture immutable input before the worker starts. Reading App/Tk from
        # the job would race with a user edit, deletion, or dialog shutdown.
        raw = [self.app.find_raw_item(item['id']) for item in self.items]
        raw = deepcopy([item for item in raw if item is not None])
        if not raw:
            self.app.tip('待导出条目已被删除')
            return
        path = new_export_path(BASE_DIR, fmt)
        self._export_pending = True
        self._export_cancel.clear()
        self._export_button.configure(text='正在导出…')

        def done(result):
            if self._alive():
                self._export_pending = False
                self.app.tip('已导出 %d 条 → %s' % (len(raw), os.path.basename(result)))
                self.close()

        def failed(error):
            if self._alive():
                self._export_pending = False
                self._export_button.configure(text='导出到本目录')
                self.app.note('导出失败（%s）' % type(error).__name__)
                self.app.tip('导出失败：%s' % error)

        future = self.app.application.tasks.submit(
            write_items, path, raw, fmt, cancelled=self._export_cancel.is_set,
            key=self._export_key, on_result=done, on_error=failed)
        if future is None:
            self._export_pending = False
            self._export_button.configure(text='导出到本目录')
            self.app.tip('后台任务繁忙，请稍后重试')
