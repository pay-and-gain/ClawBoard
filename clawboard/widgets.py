# -*- coding: utf-8 -*-
"""通用控件 + 弹窗 + 布局 / 事件 helper。

坑①/坑② 固化点：
  pack_static_then_fill()  固定尺寸控件先 pack、带 expand 的控件后 pack
  bind_recursive()         Tk 事件不冒泡，逐个给子控件接管事件
"""
import re
import tkinter as tk

from clawboard.config import FONT, FONT_B, FONT_SM, FONT_MONO, WHEEL_LINES, scaled
from clawboard.theme import T
from clawboard.runtime import uid
from clawboard.classify import preview


def pack_static_then_fill(container, fixed_widget, fill_widget,
                          fixed_side='right', fixed_kwargs=None, fill_side='left'):
    """坑①固化：Tk 的 pack 按调用顺序分配空间。

    带 expand 的控件必须在固定尺寸控件之后 pack，否则会把后者压成 1px
    （滚动条/按钮被压成 1px 都是这个坑）。统一走本 helper，新代码默认不踩坑。
    """
    fixed_kwargs = dict(fixed_kwargs) if fixed_kwargs else {'fill': 'y'}
    fixed_widget.pack(side=fixed_side, **fixed_kwargs)
    fill_widget.pack(side=fill_side, fill='both', expand=True)


def bind_recursive(widget, seq, fn):
    """坑②固化：Tk 事件不会从子控件冒泡到父控件。

    滚轮/双击必须逐个绑到每个子控件（含深层），否则鼠标停在子控件上时事件丢失。
    递归接管 widget 的所有子孙。
    """
    for c in widget.winfo_children():
        c.bind(seq, fn)
        bind_recursive(c, seq, fn)


def dark_top(win, title):
    win.configure(bg=T['bg'])
    win.overrideredirect(True)
    win.attributes('-topmost', True)
    bar = tk.Frame(win, bg=T['panel'], height=30)
    bar.pack(fill='x')
    bar.pack_propagate(False)
    tk.Label(bar, text=title, bg=T['panel'], fg=T['fg'], font=FONT_B).pack(side='left', padx=10)
    return bar


def center_on(win, parent, w, h):
    win.update_idletasks()
    px, py = parent.winfo_rootx(), parent.winfo_rooty()
    pw, ph = parent.winfo_width(), parent.winfo_height()
    area = (0, 0, parent.winfo_screenwidth(), parent.winfo_screenheight())
    try:
        import ctypes
        from clawboard.windows_api import u32, MONITORINFO, MONITOR_DEFAULTTONEAREST
        from clawboard.windows_geometry import top_hwnd
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(info)
        monitor = u32.MonitorFromWindow(top_hwnd(parent), MONITOR_DEFAULTTONEAREST)
        if u32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            r = info.rcWork
            area = r.left, r.top, r.right, r.bottom
    except (ImportError, AttributeError, OSError):
        pass
    left, top, right, bottom = area
    margin = min(scaled(8), max(0, (right - left - 1) // 2), max(0, (bottom - top - 1) // 2))
    w, h = min(w, max(1, right - left - 2 * margin)), min(h, max(1, bottom - top - 2 * margin))
    x = max(left + margin, min(px + (pw - w) // 2, right - w - margin))
    y = max(top + margin, min(py + (ph - h) // 2, bottom - h - margin))
    win.geometry('%dx%d%+d%+d' % (w, h, x, y))


def safe_release(win):
    """关闭弹窗时释放（可能根本没 grab 过，不能让它抛异常打断流程）"""
    try:
        win.grab_release()
    except Exception:
        pass


class Dialog:
    """非模态输入对话框：on_ok 回调，绝不阻塞主循环"""

    def __init__(self, parent, title, fields, on_ok=None, ok_text='确定'):
        self.result = None
        self.on_ok = on_ok
        self.parent = parent
        self._closed, self._focus_job = False, None
        self.win = tk.Toplevel(parent)
        self.win.transient(parent)
        self.bar = dark_top(self.win, title)
        self.win.attributes('-topmost', True)
        # Actions own their space before editable content can expand.
        self.actions = tk.Frame(self.win, bg=T['bg'])
        self.actions.pack(fill='x', padx=12, pady=(6, 0))
        self.ok_button = self._mk_btn(self.actions, ok_text, T['acc'], self._ok)
        self.ok_button.pack(side='right', padx=(6, 0))
        self.cancel_button = self._mk_btn(self.actions, '取消', T['card_h'], self._cancel)
        self.cancel_button.pack(side='right')
        self.body = ScrollFrame(self.win)
        self.body.canvas.configure(width=1, height=1)
        self.body.pack(fill='both', expand=True, padx=12, pady=10)
        body = self.body.inner
        self.vars = {}
        for label, default, multi in fields:
            if label:
                tk.Label(body, text=label, bg=T['bg'], fg=T['fg2'], font=FONT_SM,
                         anchor='w').pack(fill='x')
            if multi:
                w = tk.Text(body, width=1, height=5, bg=T['card'], fg=T['fg'],
                            insertbackground=T['fg'], relief='flat', font=FONT,
                            wrap='word', bd=0, highlightthickness=1,
                            highlightbackground=T['line'], highlightcolor=T['acc'])
                w.insert('1.0', default or '')
                w.pack(fill='x', pady=(2, 8))
                self.vars[label] = (None, w)
            else:
                v = tk.StringVar(value=default or '')
                e = tk.Entry(body, textvariable=v, bg=T['card'], fg=T['fg'],
                             insertbackground=T['fg'], relief='flat', font=FONT, bd=0,
                             highlightthickness=1, highlightbackground=T['line'],
                             highlightcolor=T['acc'])
                e.pack(fill='x', ipady=4, pady=(2, 8))
                self.vars[label] = (v, None)
        self.body.bind_wheel_tree()
        for _, widget in self.vars.values():
            if widget is not None:
                widget.unbind('<MouseWheel>')
        self.win.bind('<Destroy>', lambda e: self._dispose() if e.widget is self.win else None, add='+')
        self._focus_job = self.win.after(60, self._focus_later)
        self.win.bind('<Return>', lambda e: self._ok())
        self.win.bind('<Escape>', lambda e: self._cancel())
        self.win.protocol('WM_DELETE_WINDOW', self._cancel)

    def _mk_btn(self, master, text, color, cmd):
        b = tk.Button(master, text=text, command=cmd, bg=color, fg=T.get('on_acc', '#fff') if color == T['acc'] else T.get('on_danger', '#fff') if color == T['danger'] else T['fg'], font=FONT_B,
                      padx=14, pady=5, cursor='hand2', relief='flat', bd=0, takefocus=True)
        b.bind('<Return>', lambda e: (cmd(), 'break')[1])
        b.bind('<Enter>', lambda e: b.configure(bg=T['acc2'] if color == T['acc'] else T['line']))
        b.bind('<Leave>', lambda e: b.configure(bg=color))
        return b

    def _ok(self):
        if self._closed:
            return
        out = [w.get('1.0', 'end-1c') if w is not None else v.get()
               for v, w in self.vars.values()]
        self.result = out
        self._dispose()
        safe_release(self.win)
        self.win.destroy()
        if self.on_ok:
            self.on_ok(out)

    def _cancel(self):
        if self._closed:
            return
        self.result = None
        self._dispose()
        safe_release(self.win)
        self.win.destroy()

    def show(self, w=380, h=None):
        if h is None:
            self.win.update_idletasks()
            h = self.win.winfo_reqheight()
        center_on(self.win, self.parent, max(w, self.actions.winfo_reqwidth() + 24),
                  max(h, self.bar.winfo_reqheight() + self.actions.winfo_reqheight() + scaled(80)))
        self.win.update_idletasks()
        self.win.minsize(min(self.win.winfo_width(), max(scaled(240), self.actions.winfo_reqwidth() + 24)),
                         min(self.win.winfo_height(), self.bar.winfo_reqheight() + self.actions.winfo_reqheight() + scaled(80)))
        return self.result

    def _focus_later(self):
        self._focus_job = None
        if not self._closed:
            self.win.lift()
            self.win.focus_force()

    def _dispose(self):
        self._closed = True
        job, self._focus_job = self._focus_job, None
        if job:
            try:
                self.win.after_cancel(job)
            except tk.TclError:
                pass


class SplitDialog:
    MODES = ['自动（换行/逗号/分号/顿号/空格）', '按换行', '按逗号', '按空格', '按分号', '自定义分隔符']

    def __init__(self, app, text):
        self.app = app
        self._closed, self._focus_job, self._action_columns = False, None, None
        self.win = tk.Toplevel(app.root)
        self.win.transient(app.root)
        self.bar = dark_top(self.win, '拆词')
        self.bar.configure(height=scaled(30))
        self.win.attributes('-topmost', True)
        self._focus_job = self.win.after(60, self._focus_later)
        # 先保留操作区，再分配可伸缩内容；长预览和高 DPI 都不能挤掉取消按钮。
        self.footer = tk.Frame(self.win, bg=T['bg'])
        self.footer.pack(fill='x', padx=scaled(12), pady=scaled(8))
        self.action_buttons = [self.mk(self.footer, '拆成常用语', T['acc'], self.ok),
                               self.mk(self.footer, '预览', T['card_h'], self.do_preview),
                               self.mk(self.footer, '取消', T['card_h'], self.cancel)]
        self._layout_actions(1)
        body = tk.Frame(self.win, bg=T['bg'])
        body.pack(fill='both', expand=True, padx=scaled(12), pady=scaled(8))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=3)
        body.rowconfigure(4, weight=1)
        tk.Label(body, text='源文本', bg=T['bg'], fg=T['fg2'], font=FONT_SM,
                 anchor='w').grid(row=0, column=0, sticky='ew')
        source = tk.Frame(body, bg=T['bg'])
        source.grid(row=1, column=0, sticky='nsew', pady=(scaled(2), scaled(8)))
        self.txt = tk.Text(source, width=1, height=5, bg=T['card'], fg=T['fg'], insertbackground=T['fg'],
                           relief='flat', font=FONT, wrap='word', bd=0,
                           highlightthickness=1, highlightbackground=T['line'],
                           highlightcolor=T['acc'])
        self.txt.insert('1.0', text)
        source_scroll = tk.Scrollbar(source, command=self.txt.yview)
        self.txt.configure(yscrollcommand=source_scroll.set)
        pack_static_then_fill(source, source_scroll, self.txt)
        row = tk.Frame(body, bg=T['bg'])
        row.grid(row=2, column=0, sticky='ew', pady=(0, scaled(6)))
        tk.Label(row, text='分隔方式', bg=T['bg'], fg=T['fg2'], font=FONT_SM).pack(side='left')
        self.mode = tk.StringVar(value=self.MODES[0])
        mb = tk.Label(row, text='▾ 选择', bg=T['card'], fg=T['fg'], font=FONT_SM,
                      padx=8, pady=3, cursor='hand2')
        mb.pack(side='right')
        mb.bind('<Button-1>', lambda e: self.mode_menu(mb))
        self.custom = tk.Entry(body, bg=T['card'], fg=T['fg'], insertbackground=T['fg'],
                               relief='flat', font=FONT, bd=0, highlightthickness=1,
                               highlightbackground=T['line'], highlightcolor=T['acc'])
        self.custom.insert(0, '|')
        self.custom.grid(row=3, column=0, sticky='ew', pady=(0, scaled(6)))
        preview_box = tk.Frame(body, bg=T['bg'])
        preview_box.grid(row=4, column=0, sticky='nsew')
        self.prev = tk.Text(preview_box, width=1, height=3, bg=T['bg'], fg=T['acc'],
                            font=FONT_SM, wrap='word', relief='flat', bd=0, state='disabled')
        preview_scroll = tk.Scrollbar(preview_box, command=self.prev.yview)
        self.prev.configure(yscrollcommand=preview_scroll.set)
        pack_static_then_fill(preview_box, preview_scroll, self.prev)
        self.win.bind('<Escape>', lambda e: self.cancel())
        self.win.protocol('WM_DELETE_WINDOW', self.cancel)
        self.win.bind('<Configure>', lambda e: self._layout_actions(e.width - scaled(24)) if e.widget is self.win else None, add='+')
        self.win.bind('<Destroy>', lambda e: self._dispose() if e.widget is self.win else None, add='+')
        self.do_preview()
        self._fit_window()

    def _fit_window(self):
        self.win.update_idletasks()
        parent = self.app.root
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        area = (px, py, px + parent.winfo_screenwidth(), py + parent.winfo_screenheight())
        try:
            import ctypes
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
        margin = min(scaled(8), max(0, (right - left - 1) // 2), max(0, (bottom - top - 1) // 2))
        aw, ah = max(1, right - left - 2 * margin), max(1, bottom - top - 2 * margin)
        width = min(aw, max(scaled(380), self.footer.winfo_reqwidth() + scaled(24)))
        height = min(ah, max(scaled(360), self.win.winfo_reqheight()))
        x = max(left + margin, min(px + (pw - width) // 2, right - width - margin))
        y = max(top + margin, min(py + (ph - height) // 2, bottom - height - margin))
        # 负坐标属于合法副屏；不能像旧 center_on 一样直接截到主屏的 0。
        self.win.geometry('%dx%d%+d%+d' % (width, height, x, y))
        self.win.minsize(min(width, scaled(300)),
                         min(height, self.bar.winfo_reqheight() + self.footer.winfo_reqheight() + scaled(160)))

    def mk(self, master, text, color, cmd):
        b = tk.Button(master, text=text, command=cmd, bg=color, fg=T.get('on_acc', '#fff') if color == T['acc'] else T.get('on_danger', '#fff') if color == T['danger'] else T['fg'], font=FONT_B,
                      padx=12, pady=5, cursor='hand2', relief='flat', bd=0, takefocus=True)
        b.bind('<Return>', lambda e: (cmd(), 'break')[1])
        return b

    def _layout_actions(self, width):
        widths = sorted((b.winfo_reqwidth() + 4 for b in self.action_buttons), reverse=True)
        columns = 3 if width >= sum(widths) else 2 if width >= sum(widths[:2]) else 1
        if columns == self._action_columns or self._closed:
            return
        self._action_columns = columns
        for index in range(3):
            self.footer.columnconfigure(index, weight=int(index < columns))
        for index, button in enumerate(self.action_buttons):
            button.grid(row=index // columns, column=index % columns, sticky='ew', padx=2, pady=2)

    _focus_later, _dispose = Dialog._focus_later, Dialog._dispose

    def mode_menu(self, anchor):
        m = tk.Menu(self.win, tearoff=0, bg=T['panel'], fg=T['fg'], bd=0,
                    activebackground=T['card_h'], activeforeground=T['fg'],
                    font=FONT, relief='flat')
        for x in self.MODES:
            m.add_command(label=x, command=lambda x=x: (self.mode.set(x), self.do_preview()))
        m.tk_popup(anchor.winfo_rootx(), anchor.winfo_rooty() + anchor.winfo_height())

    def do_split(self):
        raw = self.txt.get('1.0', 'end-1c')
        m = self.mode.get()
        table = {self.MODES[0]: r'[\r\n,;；，、\s]+', self.MODES[1]: r'[\r\n]+',
                 self.MODES[2]: r'[,，]+', self.MODES[3]: r'[ \t]+', self.MODES[4]: r'[;；]+'}
        if m in table:
            parts = re.split(table[m], raw)
        else:
            sep = self.custom.get()
            parts = raw.split(sep) if sep else [raw]
        return [p.strip() for p in parts if p.strip()]

    def do_preview(self):
        parts = self.do_split()
        self._set_preview('预览：共 %d 条 → %s' %
                          (len(parts), ' | '.join(parts[:6]) + (' …' if len(parts) > 6 else '')))

    def _set_preview(self, text, color=None):
        self.prev.configure(state='normal', fg=color or T['acc'])
        self.prev.delete('1.0', 'end')
        self.prev.insert('1.0', text)
        self.prev.configure(state='disabled')

    def ok(self):
        if self._closed:
            return
        parts = self.do_split()
        if not parts:
            self._set_preview('没拆出任何内容', T['danger'])
            return
        g = self.app.cur_group()
        for p in parts:
            g['items'].insert(0, {'id': uid(), 'name': preview(p, 12), 'text': p})
        self.app.save(True)
        self.app.tab = 'phrase'
        self.app.render()
        self.app.tip('已拆出 %d 条常用语' % len(parts))
        self._dispose()
        safe_release(self.win)
        self.win.destroy()

    def cancel(self):
        if self._closed:
            return
        self._dispose()
        safe_release(self.win)
        self.win.destroy()


class Tip:
    """悬停提示：延迟 450ms 弹出，移开立即销毁"""

    def __init__(self, root):
        self.root = root
        self.win = None
        self.job = None

    def show(self, text, x, y):
        self.hide()
        self.job = self.root.after(450, lambda: self._pop(text, x, y))

    def _pop(self, text, x, y):
        self.hide()
        w = tk.Toplevel(self.root)
        w.overrideredirect(True)
        w.attributes('-topmost', True)
        tk.Label(w, text=text, bg=T['panel'], fg=T['fg'], font=FONT_SM,
                 justify='left', padx=8, pady=5, bd=1, relief='solid').pack()
        w.geometry('+%d+%d' % (x + 18, y + 18))
        self.win = w

    def hide(self):
        if self.job:
            try:
                self.root.after_cancel(self.job)
            except Exception:
                pass
            self.job = None
        if self.win:
            try:
                self.win.destroy()
            except Exception:
                pass
            self.win = None


class ThinBar(tk.Canvas):
    """自绘细滑动条：没有两端箭头，滑块颜色看得见、拖得动。

    直接实现 tk 的 yscrollcommand 协议，谁都能接：
        canvas.configure(yscrollcommand=bar.set)
    """

    MIN_THUMB = 28          # 滑块最小高度，再短就抓不住了

    def __init__(self, master, on_move, width=8, on_wheel=None):
        tk.Canvas.__init__(self, master, width=width, bg=T['bg'],
                           highlightthickness=0, bd=0)
        self.on_move = on_move
        self.w = width
        self._first = 0.0
        self._last = 1.0
        self._grab = None       # 按住滑块时，记录鼠标相对滑块顶端的偏移
        self._mode = 0          # 0 静默 1 悬停 2 拖动
        self.bind('<Configure>', lambda e: self._draw())
        self.bind('<Button-1>', self._press)
        self.bind('<B1-Motion>', self._move)
        self.bind('<ButtonRelease-1>', self._release)
        self.bind('<Enter>', lambda e: self._paint(1))
        self.bind('<Leave>', lambda e: self._paint(0))
        if on_wheel:
            self.bind('<MouseWheel>', on_wheel)

    # ---------- tk Scrollbar 协议 ----------
    def set(self, first, last):
        first, last = float(first), float(last)
        if abs(first - self._first) < 1e-6 and abs(last - self._last) < 1e-6:
            return
        self._first, self._last = first, last
        self._draw()

    def get(self):
        return (self._first, self._last)

    # ---------- 内部 ----------
    def _geom(self):
        """返回 (滑块顶端 y, 滑块高度, 轨道高度)"""
        h = max(1, self.winfo_height())
        span = max(0.0, min(1.0, self._last - self._first))
        if span >= 0.9999:
            return 0, h, h
        th = max(self.MIN_THUMB, int(h * span))
        y = int(self._first * (h - th) / (1.0 - span))
        return y, th, h

    def _draw(self):
        # 窗口销毁瞬间仍可能收到 <Configure>，此时 canvas 已不能画了，直接放弃
        try:
            self.delete('all')
            h = max(1, self.winfo_height())
            # Per-window DPI refresh can resize this canvas after construction.
            # Drawing at its initial width leaves a thin, misplaced thumb.
            width = max(1, self.winfo_width())
            self.create_rectangle(0, 0, width, h, fill=T['panel'], outline='')
            y, th, _ = self._geom()
            if th >= h:             # 内容不满一屏：只留一条淡轨道，不影响观感
                return
            if self._mode == 2:
                col = T['acc']      # 拖动中
            elif self._mode == 1:
                col = T['fg']       # 悬停
            else:
                col = T['fg2']      # 静默也看得见
            inset = min(1, width / 2)
            self.create_rectangle(inset, y + 1, width - inset, y + th - 1, fill=col, outline='')
        except tk.TclError:
            pass

    def _paint(self, mode):
        if self._grab is not None:
            self._mode = 2
            return
        self._mode = mode
        self._draw()

    def _press(self, e):
        y, th, h = self._geom()
        if th >= h:
            return
        if y <= e.y <= y + th:
            self._grab = e.y - y            # 抓住滑块本体
        else:
            self._grab = th // 2            # 点轨道：滑块中心跟过来
            self._move(e)
        self._mode = 2
        self._draw()

    def _move(self, e):
        if self._grab is None:
            return
        _, th, h = self._geom()
        span = max(0.0, min(1.0, self._last - self._first))
        if span >= 0.9999 or h - th <= 0:
            return
        y = max(0, min(h - th, e.y - self._grab))
        first = y * (1.0 - span) / (h - th)
        self._first = first
        self._last = first + span
        self._draw()
        self.on_move(first)

    def _release(self, e):
        self._grab = None
        self._paint(1)


class ScrollFrame(tk.Frame):
    """可滚动容器：内容放 .inner。滚轮 + 右侧细滚动条，内层宽度自动跟随。"""

    def __init__(self, master, bg=None):
        bg = bg or T['bg']
        tk.Frame.__init__(self, master, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0,
                                yscrollincrement=24)
        self.sb = ThinBar(self, lambda f: self.canvas.yview_moveto(f),
                          width=8, on_wheel=self._wheel)
        pack_static_then_fill(self, self.sb, self.canvas)   # 先占位，再让 canvas 吃掉剩余宽度
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._wid = self.canvas.create_window((0, 0), window=self.inner, anchor='nw')
        self._acc = 0.0
        self.inner.bind('<Configure>', self._on_inner)
        self.canvas.bind('<Configure>', self._on_canvas)
        self.canvas.bind('<MouseWheel>', self._wheel)

    def _on_inner(self, _=None):
        try:
            self.canvas.configure(scrollregion=self.canvas.bbox('all') or (0, 0, 0, 0))
        except tk.TclError:
            pass

    def _on_canvas(self, e):
        try:
            self.canvas.itemconfigure(self._wid, width=e.width)
        except tk.TclError:
            pass

    def bind_wheel_tree(self, w=None):
        """内容建好后调用一次：给所有子控件补上滚轮绑定（含后加的）"""
        w = w or self.inner
        bind_recursive(w, '<MouseWheel>', self._wheel)

    def _wheel(self, e):
        d = getattr(e, 'delta', 0)
        if not d:
            return 'break'
        self._acc += d / 120.0
        steps = int(self._acc)
        if not steps:
            return 'break'
        self._acc -= steps
        self.canvas.yview_scroll(-steps * WHEEL_LINES, 'units')
        return 'break'


class CopyToast:
    """复制提示浮窗（借鉴剪藏的果冻提示）。

    复制内容后在屏幕角落弹一个小卡片：写明行数 / 字符数 + 内容预览，
    淡入 → 停留 → 淡出，全程**不抢焦点**、不打断正在做的事。
    面板正好占着右下角时自动改到左下角，避免遮挡（剪藏同款处理）。
    """

    W, H = 300, 84
    GAP = 12

    def __init__(self, app, lines, chars, text, ms=1800):
        self.app = app
        self.ms = ms
        self.win = tk.Toplevel(app.root)
        self.win.overrideredirect(True)
        self.win.attributes('-topmost', True)
        self.win.attributes('-alpha', 0.0)          # 从全透明开始淡入
        self.win.configure(bg=T['line'])
        box = tk.Frame(self.win, bg=T['panel'])
        box.pack(fill='both', expand=True, padx=1, pady=1)
        head = tk.Frame(box, bg=T['panel'])
        head.pack(fill='x', padx=10, pady=(8, 0))
        tk.Label(head, text='已复制', bg=T['panel'], fg=T['acc'],
                 font=FONT_B).pack(side='left')
        tk.Label(head, text='%d 行 · %d 字符' % (lines, chars), bg=T['panel'],
                 fg=T['fg2'], font=FONT_SM).pack(side='right')
        tk.Label(box, text=text, bg=T['panel'], fg=T['fg'], font=FONT_SM,
                 anchor='w', justify='left').pack(fill='x', padx=10, pady=(4, 8))
        x, y = self._pos()
        self.win.geometry('%dx%d+%d+%d' % (self.W, self.H, x, y))
        self._fade_in(0.0)

    def _pos(self):
        """贴**面板所在屏幕**的角落、并与面板错开一侧。

        落点由 app.preview_corner 按面板所在显示器算好 —— 浮窗自己不再碰
        winfo_screenwidth/height（那只是主屏，面板在副屏时预览会跑错屏）。
        """
        try:
            return self.app.preview_corner(self.W, self.H)
        except Exception:
            return 12, 12

    def _fade_in(self, a):
        a = min(0.96, a + 0.16)
        try:
            self.win.attributes('-alpha', a)
        except Exception:
            return self._close()
        if a < 0.96:
            self.win.after(16, lambda: self._fade_in(a))
        else:
            self.win.after(self.ms, lambda: self._fade_out(0.96))

    def _fade_out(self, a):
        a -= 0.16
        try:
            self.win.attributes('-alpha', max(0.0, a))
        except Exception:
            return self._close()
        if a > 0:
            self.win.after(16, lambda: self._fade_out(a))
        else:
            self._close()

    def _close(self):
        try:
            self.win.destroy()
        except Exception:
            pass


class ContentPreview:
    """选中即预览：在屏幕角落显示条目的**完整内容**。

    借鉴剪藏（wincpl）的"角落完整预览"。面板里列表只显示截断的预览，
    想看全文得右键；这里选中就直接在角落给出全文，长文本可滚动，
    代码 / JSON 用等宽字体并保留缩进。

    只读展示，不抢焦点；面板收起或隐藏时由 app 负责销毁。
    """

    W, H = 460, 340
    GAP = 12

    def __init__(self, app, text, kind='text', meta=''):
        self.app = app
        self.win = tk.Toplevel(app.root)
        self.win.overrideredirect(True)
        self.win.attributes('-topmost', True)
        self.win.attributes('-alpha', 0.0)
        self.win.configure(bg=T['line'])
        box = tk.Frame(self.win, bg=T['panel'])
        box.pack(fill='both', expand=True, padx=1, pady=1)
        head = tk.Frame(box, bg=T['panel'])
        head.pack(fill='x', padx=10, pady=(8, 4))
        tk.Label(head, text='完整内容', bg=T['panel'], fg=T['acc'],
                 font=FONT_B).pack(side='left')
        if meta:
            tk.Label(head, text=meta, bg=T['panel'], fg=T['fg2'],
                     font=FONT_SM).pack(side='right')
        # 文本区：只读 Text + 细滚动条（固定尺寸先 pack，见坑①）
        wrap = tk.Frame(box, bg=T['panel'])
        wrap.pack(fill='both', expand=True, padx=8, pady=(0, 8))
        mono = kind in ('code', 'json')
        self.txt = tk.Text(wrap, bg=T['card'], fg=T['fg'], bd=0, relief='flat',
                           wrap='none' if mono else 'word',
                           font=(FONT_MONO if mono else FONT),
                           insertbackground=T['fg'], highlightthickness=0)
        # 先 pack 滚动条占位，否则会被 Text 的 expand 挤成 1px（坑①）
        bar = ThinBar(wrap, lambda f: self.txt.yview_moveto(f), width=8,
                      on_wheel=self._wheel)
        bar.pack(side='right', fill='y', padx=(4, 0))
        self.txt.configure(yscrollcommand=bar.set)
        self.txt.pack(side='left', fill='both', expand=True)
        self._preview_text = text or ''
        self._preview_offset = 0
        self._insert_job = None
        self._append_text_chunk()
        self.txt.bind('<MouseWheel>', self._wheel)
        x, y = self._pos()
        self.win.geometry('%dx%d+%d+%d' % (self.W, self.H, x, y))
        self._fade_in(0.0)

    def _append_text_chunk(self):
        self._insert_job = None
        try:
            self.txt.configure(state='normal')
            chunk = self._preview_text[self._preview_offset:self._preview_offset + 16384]
            self.txt.insert('end', chunk)
            self._preview_offset += len(chunk)
            self.txt.configure(state='disabled')
            if self._preview_offset < len(self._preview_text):
                self._insert_job = self.win.after(8, self._append_text_chunk)
            else:
                self._preview_text = ''
        except tk.TclError:
            self._preview_text = ''

    def _wheel(self, e):
        try:
            self.txt.yview_scroll(-3 if e.delta > 0 else 3, 'units')
        except Exception:
            pass
        return 'break'

    def _pos(self):
        """贴面板的另一侧角落，避免遮住面板自己（落点按**面板所在屏**算）。"""
        try:
            return self.app.preview_corner(self.W, self.H)
        except Exception:
            return 12, 12

    def _fade_in(self, a):
        a = min(0.96, a + 0.2)
        try:
            self.win.attributes('-alpha', a)
        except Exception:
            return
        if a < 0.96:
            self.win.after(14, lambda: self._fade_in(a))

    def close(self):
        try:
            if getattr(self, '_insert_job', None):
                self.win.after_cancel(self._insert_job)
                self._insert_job = None
            self.win.destroy()
        except Exception:
            pass


class ImagePreview:
    """图片条目的角落预览：加载 PNG 显示大图，太大则等比缩小。"""

    W, H = 460, 340
    GAP = 12

    def __init__(self, app, image_path=None, meta='', *, data=None):
        self.app = app
        self.win = tk.Toplevel(app.root)
        self.win.overrideredirect(True)
        self.win.attributes('-topmost', True)
        self.win.attributes('-alpha', 0.0)
        self.win.configure(bg=T['line'])
        box = tk.Frame(self.win, bg=T['panel'])
        box.pack(fill='both', expand=True, padx=1, pady=1)
        head = tk.Frame(box, bg=T['panel'])
        head.pack(fill='x', padx=10, pady=(8, 4))
        tk.Label(head, text='图片', bg=T['panel'], fg=T['acc'],
                 font=FONT_B).pack(side='left')
        if meta:
            tk.Label(head, text=meta, bg=T['panel'], fg=T['fg2'],
                     font=FONT_SM).pack(side='right')
        self.img = tk.PhotoImage(data=data) if data is not None else tk.PhotoImage(file=image_path)
        while self.img.width() > self.W or self.img.height() > self.H:
            self.img = self.img.subsample(2, 2)
        tk.Label(box, image=self.img, bg=T['card']).pack(fill='both', expand=True,
                                                         padx=8, pady=(0, 8))
        x, y = self._pos()
        w = max(140, self.img.width() + 20)
        h = max(100, self.img.height() + 44)
        self.win.geometry('%dx%d+%d+%d' % (w, h, x, y))
        self._fade_in(0.0)

    def _pos(self):
        """贴面板的另一侧角落（落点按**面板所在屏**算，不再自算 winfo_screen*）。"""
        try:
            return self.app.preview_corner(self.W, self.H)
        except Exception:
            return 12, 12

    def _fade_in(self, a):
        a = min(0.96, a + 0.2)
        try:
            self.win.attributes('-alpha', a)
        except Exception:
            return
        if a < 0.96:
            self.win.after(14, lambda: self._fade_in(a))

    def close(self):
        try:
            self.win.destroy()
        except Exception:
            pass
