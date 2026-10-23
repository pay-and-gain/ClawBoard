"""Tk export adapter; workers receive only copied records and a destination."""
import os
import tkinter as tk
from copy import deepcopy
from clawboard import runtime
from threading import Event
from clawboard.config import BASE_DIR, FONT, FONT_B, FONT_SM
from clawboard.theme import T
from clawboard.widgets import dark_top, center_on, safe_release
from clawboard.exports import write_items, new_export_path


class ExportDialog:
    """F5：把历史导出成 TXT / CSV / JSON / Markdown"""

    def __init__(self, app):
        self.app = app
        self._closed = False
        self._export_pending = False
        self._export_cancel = Event()
        self._export_key = ('export', id(self))
        ids = set(app.vlist.multi)
        items = [x for x in app.vlist.items if x['id'] in ids] if ids else list(app.vlist.items)
        self.items = items
        if not items:
            app.tip('没有可导出的内容')
            return
        self.win = tk.Toplevel(app.root)
        self.win.transient(app.root)
        dark_top(self.win, '批量导出')
        self.win.attributes('-topmost', True)
        self.win.protocol('WM_DELETE_WINDOW', self.close)
        self.win.bind('<Destroy>', self._destroyed, add='+')
        self.win.bind('<Escape>', lambda e: self.close())
        self.win.after(60, lambda: (self.win.lift(), self.win.focus_force()))
        body = tk.Frame(self.win, bg=T['bg'])
        body.pack(fill='both', expand=True, padx=14, pady=10)
        tk.Label(body, text='共 %d 条待导出（多选优先，否则导出当前筛选结果）'
                 % len(items), bg=T['bg'], fg=T['fg'], font=FONT, anchor='w').pack(fill='x')
        self.fmt = tk.StringVar(value='txt')
        self.rows = []
        for v, label in (('txt', 'TXT（序号/时间/来源/内容）'),
                         ('csv', 'CSV（Excel 友好，带 BOM）'),
                         ('json', 'JSON（完整字段，可再导入）'),
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
        sens = sum(1 for x in items if x.get('sens'))
        if sens:
            tk.Label(body, text='⚠ 其中 %d 条含敏感内容，导出为明文' % sens,
                     bg=T['bg'], fg=T['danger'], font=FONT_SM, anchor='w').pack(fill='x', pady=4)
        btns = tk.Frame(body, bg=T['bg'])
        btns.pack(fill='x', pady=(8, 0))
        b = tk.Label(btns, text='导出到本目录', bg=T['acc'], fg='#fff', font=FONT_B,
                     padx=14, pady=5, cursor='hand2')
        b.pack(side='right')
        b.bind('<Button-1>', lambda e: self.do_export())
        self._export_button = b
        b2 = tk.Label(btns, text='取消', bg=T['card_h'], fg=T['fg'], font=FONT,
                      padx=14, pady=5, cursor='hand2')
        b2.pack(side='right', padx=(0, 6))
        b2.bind('<Button-1>', lambda e: self.close())
        center_on(self.win, app.root, 480, 340)

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
            self._closed = True
            self._export_cancel.set()
            self.app.application.tasks.invalidate(self._export_key)

    def close(self):
        if getattr(self, '_closed', False):
            return
        self._closed = True
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
