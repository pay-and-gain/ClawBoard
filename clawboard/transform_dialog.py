"""Tk text-transform adapter with asynchronous, complete result ownership."""
import tkinter as tk
from clawboard.config import WHEEL_LINES, FONT, FONT_B, FONT_SM, scaled
from clawboard.theme import T
from clawboard.runtime import tx
from clawboard.clipboard import clip_write
from clawboard.widgets import ThinBar, dark_top, center_on, safe_release


class TransformWindow:
    """变换任务与完整结果归属此对话框，UI 只展示有限预览。"""

    def __init__(self, app, text, item=None):
        self.app = app
        self.item = item
        self._closed = False
        self._pending = False
        self._ready = False
        self._truncated = False
        self._full_result = None
        self._task_key = ('transform', id(self))
        self._focus_job = None
        self._source_text = text
        self._source_truncated = len(text) > 200000
        self.win = tk.Toplevel(app.root)
        self.win.transient(app.root)
        self.bar = dark_top(self.win, '文本变换')
        self.win.attributes('-topmost', True)
        self.actions = tk.Frame(self.win, bg=T['bg'])
        self.actions.pack(fill='x', padx=10, pady=(6, 0))
        self.action_buttons = []
        for label, command in (('复制到剪贴板', self.copy_out), ('存为新条目', self.save_new),
                               ('覆盖原条目', self.overwrite), ('关闭', self.close)):
            button = tk.Button(self.actions, text=label, command=command, bg=T['card'], fg=T['fg'],
                               font=FONT, padx=8, pady=5, relief='flat', bd=0,
                               highlightthickness=1, highlightbackground=T['line'],
                               highlightcolor=T['acc'], takefocus=True)
            button.bind('<Return>', lambda event, cmd=command: (cmd(), 'break')[1])
            self.action_buttons.append(button)
        self._action_columns = self._narrow = None
        self._layout_actions(1)
        mid = tk.Frame(self.win, bg=T['bg'])
        mid.pack(fill='both', expand=True, padx=10, pady=6)
        self.mid = mid

        lf = tk.Frame(mid, bg=T['bg'])
        lf.pack(side='left', fill='y')
        self.left = lf
        self.lb = tk.Listbox(lf, bg=T['card'], fg=T['fg'], bd=0, relief='flat',
                             highlightthickness=1, highlightbackground=T['line'],
                             selectbackground=T['acc'], font=FONT_SM,
                             width=20, height=20)
        sb = ThinBar(lf, lambda f: self.lb.yview_moveto(f), width=8)
        self.lb.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y', padx=(2, 0))
        self.lb.pack(side='left', fill='both', expand=True)
        # Windows 的 Tk Listbox 自带没有任何滚轮绑定，必须自己接管
        self.lb.bind('<MouseWheel>', self.lb_wheel)
        # 智能推荐：把最可能的变换排到最前（加 ★ 前缀），其余按原顺序跟在后面。
        # self._keys 与 Listbox 的每一行一一对应（分隔占位行对应 None），
        # run() 只按 _keys 反查，避免依赖 label 文本。
        txm = tx()
        rec = txm.recommend(text)
        self._keys = []
        labels = {k: label for k, label, _ in txm.TRANSFORMS}
        if rec:
            recset = set(rec)
            for key in rec:
                if key in labels:
                    self.lb.insert('end', '★ ' + labels[key])
                    self._keys.append(key)
            self.lb.insert('end', '────────')
            self._keys.append(None)
            for key, label, _ in txm.TRANSFORMS:
                if key not in recset:
                    self.lb.insert('end', label)
                    self._keys.append(key)
        else:
            for key, label, _ in txm.TRANSFORMS:
                self.lb.insert('end', label)
                self._keys.append(key)
        self.lb.bind('<<ListboxSelect>>', lambda e: self.run())

        rf = tk.Frame(mid, bg=T['bg'])
        rf.pack(side='left', fill='both', expand=True, padx=(10, 0))
        self.right = rf
        tk.Label(rf, text='原文（预览已截断，变换使用完整原文）' if self._source_truncated else '原文', bg=T['bg'], fg=T['fg2'], font=FONT_SM,
                 anchor='w').pack(fill='x')
        self.src = tk.Text(rf, height=9, bg=T['card'], fg=T['fg'],
                           insertbackground=T['fg'], relief='flat', font=FONT_SM,
                           wrap='word', bd=0, highlightthickness=1,
                           highlightbackground=T['line'], highlightcolor=T['acc'])
        self.src.insert('1.0', text[:200000])
        if self._source_truncated:
            self.src.configure(state='disabled')
        self.src.pack(fill='both', expand=True)
        self.result_status = tk.Label(rf, text='结果', bg=T['bg'], fg=T['fg2'], font=FONT_SM, anchor='w')
        self.result_status.pack(fill='x')
        self.out = tk.Text(rf, height=9, bg=T['card'], fg=T['fg'],
                           insertbackground=T['fg'], relief='flat', font=FONT_SM,
                           wrap='word', bd=0, highlightthickness=1,
                           highlightbackground=T['line'], highlightcolor=T['acc'])
        self.out.pack(fill='both', expand=True)

        self.win.bind('<Escape>', lambda e: self.close())
        self.win.protocol('WM_DELETE_WINDOW', self.close)
        self.win.bind('<Destroy>', self._destroyed, add='+')
        self.win.bind('<Configure>', self._configured, add='+')
        self.win.update_idletasks()
        center_on(self.win, app.root, scaled(760), scaled(540))
        self.win.update_idletasks()
        self.win.minsize(min(self.win.winfo_width(), scaled(280)),
                         min(self.win.winfo_height(), self.bar.winfo_reqheight() + self.actions.winfo_reqheight() + scaled(150)))
        self._focus_job = self.win.after(60, self._focus_later)

    def _layout_actions(self, width):
        widths = [button.winfo_reqwidth() + 6 for button in self.action_buttons]
        columns = 4 if width >= sum(widths) else 2 if width >= max(sum(widths[:2]), sum(widths[2:])) else 1
        if columns == self._action_columns:
            return
        self._action_columns = columns
        for index in range(4):
            self.actions.columnconfigure(index, weight=1 if index < columns else 0)
        for index, button in enumerate(self.action_buttons):
            button.grid(row=index // columns, column=index % columns, sticky='ew', padx=3, pady=3)

    def _configured(self, event):
        if event.widget is not self.win or self._closed:
            return
        self._layout_actions(max(1, self.win.winfo_width() - 20))
        narrow = self.win.winfo_width() < scaled(560)
        if narrow == self._narrow:
            return
        self._narrow = narrow
        self.left.pack_forget()
        self.right.pack_forget()
        self.left.pack_propagate(False)
        self.left.configure(width=scaled(180), height=scaled(110) if narrow else 1)
        self.left.pack(side='top' if narrow else 'left', fill='x' if narrow else 'y')
        self.lb.pack_configure(fill='both', expand=True)
        self.right.pack(side='top' if narrow else 'left', fill='both', expand=True,
                        padx=0 if narrow else (10, 0))

    def _focus_later(self):
        self._focus_job = None
        if self._alive():
            self.win.lift()
            self.win.focus_force()

    def _cancel_focus(self):
        job = getattr(self, '_focus_job', None)
        self._focus_job = None
        if job:
            try:
                self.win.after_cancel(job)
            except tk.TclError:
                pass

    def lb_wheel(self, e):
        """变换列表的滚轮：同样按 1/120 格累积，触控板不丢事件"""
        d = getattr(e, 'delta', 0)
        if not d:
            return 'break'
        self._acc = getattr(self, '_acc', 0.0) + d / 120.0
        steps = int(self._acc)
        if not steps:
            return 'break'
        self._acc -= steps
        self.lb.yview_scroll(-steps * WHEEL_LINES, 'units')
        return 'break'

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
            self._cancel_focus()
            self.app.application.tasks.invalidate(self._task_key)

    def close(self):
        if getattr(self, '_closed', False):
            return
        self._closed = True
        self._cancel_focus()
        self.app.application.tasks.invalidate(self._task_key)
        safe_release(self.win)
        self.win.destroy()

    def run(self):
        if not self._alive():
            return
        selected = self.lb.curselection()
        if not selected:
            return
        key = self._keys[int(selected[0])]
        if key is None:
            return
        source = self._source_text if self._source_truncated else self.src.get('1.0', 'end-1c')
        self.app.application.tasks.invalidate(self._task_key)
        self._pending = True
        self._ready = False
        self._full_result = None
        self.out.configure(state='normal', fg=T['fg2'])
        self.out.delete('1.0', 'end')
        self.out.insert('1.0', '后台处理中…')
        self.out.configure(state='disabled')
        future = self.app.application.tasks.submit(
            self._work, key, source, key=self._task_key,
            on_result=lambda result: self._show(*result),
            on_error=lambda error: self._show('', str(error)))
        if future is None:
            self._show('', '后台任务繁忙，请稍后重试')

    @staticmethod
    def _work(key, source):
        # Pure worker: never reads App state or calls a widget/after callback.
        try:
            return tx().apply(key, source), None
        except Exception as error:
            return '', str(error)

    def _show(self, result, error):
        if not self._alive():
            return
        self._pending = False
        self._ready = error is None and isinstance(result, str)
        self._full_result = result if self._ready else None
        self._truncated = bool(self._ready and len(result) > 500000)
        self.out.configure(state='normal')
        self.out.delete('1.0', 'end')
        if not self._ready:
            self.out.configure(fg=T['danger'])
            self.out.insert('1.0', '变换失败：' + (str(error) if error is not None else '结果不是文本'))
            self.out.configure(state='disabled')
        else:
            self.out.configure(fg=T['fg'])
            self.out.insert('1.0', result[:500000])
            if self._truncated:
                self.out.configure(state='disabled')
        label = getattr(self, 'result_status', None)
        if label is not None:
            label.configure(text='结果 · 预览已截断，操作使用完整结果' if self._truncated else '结果')

    def _out_text(self):
        if not self._alive():
            return None
        if not getattr(self, '_ready', False) or getattr(self, '_pending', False):
            self.app.tip('正在处理，请稍后' if getattr(self, '_pending', False) else '请先完成一次成功的变换')
            return None
        if self._truncated:
            return self._full_result
        # A complete, small preview remains editable; explicit user edits win.
        return self.out.get('1.0', 'end-1c')

    def copy_out(self):
        text = self._out_text()
        if text is None:
            return
        if clip_write(text) is False:
            self.app.tip('剪贴板被占用，复制失败')
        else:
            self.app.tip('结果已复制到剪贴板')

    def save_new(self):
        text = self._out_text()
        if text is None:
            return
        self.app.tab = 'clip'
        if self.app.ingest(text, manual=True) is not False:
            self.app.tip('已存为新条目（原条目保留）')

    def overwrite(self):
        text = self._out_text()
        if text is None:
            return
        raw = self.app.find_raw_item(self.item['id']) if self.item else None
        if raw is None:
            self.app.tip('没有可覆盖的原条目，请用「存为新条目」')
            return
        self.app.application.history.replace_text(raw, text)
        self.app.save(True)
        self.app.render()
        self.app.tip('已覆盖原条目（首次复制时间未改）')
