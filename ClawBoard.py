# -*- coding: utf-8 -*-
"""
ClawBoard - 悬浮剪切板 & 常用语面板
零第三方依赖，仅用 Python 自带 tkinter + ctypes(Win32)
适配 Windows 10
"""
import os
import re
import json
import time
import ctypes
import threading
import tkinter as tk
from tkinter import messagebox
from ctypes import wintypes

# ---------------- 主题 ----------------
BG      = '#1e2027'
PANEL   = '#252831'
CARD    = '#2c303b'
CARD_H  = '#39404f'
CARD_S  = '#33465f'
FG      = '#e6e8ee'
FG2     = '#9aa0ad'
ACC     = '#4f8cff'
ACC2    = '#2f6fe0'
DANGER  = '#e05c5c'
LINE    = '#333844'

FONT      = ('Microsoft YaHei UI', 9)
FONT_B    = ('Microsoft YaHei UI', 9, 'bold')
FONT_SM   = ('Microsoft YaHei UI', 8)
FONT_TITLE= ('Microsoft YaHei UI', 10, 'bold')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, 'ClawBoard数据.json')

# ---------------- Win32 剪贴板 ----------------
u32 = ctypes.WinDLL('user32', use_last_error=True)
k32 = ctypes.WinDLL('kernel32', use_last_error=True)

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

u32.GetClipboardSequenceNumber.restype = wintypes.DWORD
u32.GetClipboardSequenceNumber.argtypes = []
u32.OpenClipboard.argtypes = [wintypes.HWND]
u32.OpenClipboard.restype = wintypes.BOOL
u32.CloseClipboard.restype = wintypes.BOOL
u32.EmptyClipboard.restype = wintypes.BOOL
u32.GetClipboardData.argtypes = [wintypes.UINT]
u32.GetClipboardData.restype = wintypes.HANDLE
u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
u32.SetClipboardData.restype = wintypes.HANDLE
u32.GetForegroundWindow.restype = wintypes.HWND
u32.SetForegroundWindow.argtypes = [wintypes.HWND]
u32.SetForegroundWindow.restype = wintypes.BOOL
u32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, wintypes.DWORD, ctypes.c_ulong]
u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
u32.GetWindowThreadProcessId.restype = wintypes.DWORD

k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
k32.GlobalAlloc.restype = wintypes.HANDLE
k32.GlobalLock.argtypes = [wintypes.HANDLE]
k32.GlobalLock.restype = ctypes.c_void_p
k32.GlobalUnlock.argtypes = [wintypes.HANDLE]
k32.GlobalUnlock.restype = wintypes.BOOL
k32.GlobalSize.argtypes = [wintypes.HANDLE]
k32.GlobalSize.restype = ctypes.c_size_t

VK_CONTROL = 0x11
KEYEVENTF_KEYUP = 0x0002


def clip_seq():
    try:
        return u32.GetClipboardSequenceNumber()
    except Exception:
        return 0


def clip_read():
    """读取系统剪贴板文本，失败返回 None"""
    if not u32.OpenClipboard(None):
        return None
    try:
        h = u32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = k32.GlobalLock(h)
        if not p:
            return None
        try:
            return ctypes.wstring_at(p)
        finally:
            k32.GlobalUnlock(h)
    finally:
        u32.CloseClipboard()


def clip_write(text):
    """写入系统剪贴板文本"""
    data = text.encode('utf-16-le') + b'\x00\x00'
    if not u32.OpenClipboard(None):
        return False
    try:
        u32.EmptyClipboard()
        h = k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not h:
            return False
        p = k32.GlobalLock(h)
        if not p:
            return False
        ctypes.memmove(p, data, len(data))
        k32.GlobalUnlock(h)
        u32.SetClipboardData(CF_UNICODETEXT, h)
        return True
    finally:
        u32.CloseClipboard()
        global LAST_SEQ
        LAST_SEQ = clip_seq()


LAST_SEQ = clip_seq()


def send_ctrl_v():
    u32.keybd_event(VK_CONTROL, 0, 0, 0)
    u32.keybd_event(ord('V'), 0, 0, 0)
    u32.keybd_event(ord('V'), 0, KEYEVENTF_KEYUP, 0)
    u32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


# ---------------- 小工具 ----------------
_uid_seq = [0]


def uid():
    _uid_seq[0] += 1
    return '%d_%d' % (int(time.time() * 1000), _uid_seq[0])


def now_str():
    return time.strftime('%H:%M')


def preview(text, n=90):
    t = ' '.join(text.split())
    return t if len(t) <= n else t[:n] + '…'


def dark_top(win, title):
    """把一个 Toplevel 变成暗色无边框小窗"""
    win.configure(bg=BG)
    win.overrideredirect(True)
    win.attributes('-topmost', True)
    bar = tk.Frame(win, bg=PANEL, height=30)
    bar.pack(fill='x')
    bar.pack_propagate(False)
    tk.Label(bar, text=title, bg=PANEL, fg=FG, font=FONT_B).pack(side='left', padx=10)
    return bar


def center_on(win, parent, w, h):
    win.update_idletasks()
    px = parent.winfo_rootx()
    py = parent.winfo_rooty()
    pw = parent.winfo_width()
    ph = parent.winfo_height()
    x = px + (pw - w) // 2
    y = py + (ph - h) // 2
    win.geometry('%dx%d+%d+%d' % (w, h, max(x, 0), max(y, 0)))


class Dialog:
    """通用暗色输入对话框"""

    def __init__(self, parent, title, fields, on_ok=None, ok_text='确定'):
        """on_ok 不为 None 时走非模态回调，不会卡住主循环"""
        self.result = None
        self.on_ok = on_ok
        self.parent = parent
        self.win = tk.Toplevel(parent)
        self.win.transient(parent)
        bar = dark_top(self.win, title)
        self.win.grab_set()
        body = tk.Frame(self.win, bg=BG)
        body.pack(fill='both', expand=True, padx=12, pady=10)
        self.vars = {}
        for i, (label, default, multi) in enumerate(fields):
            tk.Label(body, text=label, bg=BG, fg=FG2, font=FONT_SM, anchor='w').pack(fill='x')
            if multi:
                w = tk.Text(body, height=5, bg=CARD, fg=FG, insertbackground=FG,
                            relief='flat', font=FONT, wrap='word', bd=0,
                            highlightthickness=1, highlightbackground=LINE,
                            highlightcolor=ACC)
                w.insert('1.0', default or '')
                w.pack(fill='x', pady=(2, 8))
            else:
                v = tk.StringVar(value=default or '')
                e = tk.Entry(body, textvariable=v, bg=CARD, fg=FG, insertbackground=FG,
                             relief='flat', font=FONT, bd=0,
                             highlightthickness=1, highlightbackground=LINE,
                             highlightcolor=ACC)
                e.pack(fill='x', ipady=4, pady=(2, 8))
            self.vars[label] = (v if not multi else None, w if multi else None)

        btns = tk.Frame(self.win, bg=BG)
        btns.pack(fill='x', padx=12, pady=(0, 12))
        self._mk_btn(btns, ok_text, ACC, self._ok).pack(side='right', padx=(6, 0))
        self._mk_btn(btns, '取消', '#3a3f4d', self._cancel).pack(side='right')
        self.win.bind('<Return>', lambda e: self._ok())
        self.win.bind('<Escape>', lambda e: self._cancel())
        self.win.protocol('WM_DELETE_WINDOW', self._cancel)

    def _mk_btn(self, master, text, color, cmd):
        b = tk.Label(master, text=text, bg=color, fg='#ffffff', font=FONT_B,
                     padx=14, pady=5, cursor='hand2')
        b.bind('<Button-1>', lambda e: cmd())
        b.bind('<Enter>', lambda e: b.configure(bg=ACC2 if color == ACC else '#4a5060'))
        b.bind('<Leave>', lambda e: b.configure(bg=color))
        return b

    def _ok(self):
        out = []
        for label, (v, w) in self.vars.items():
            out.append(w.get('1.0', 'end-1c') if w is not None else v.get())
        self.result = out
        self.win.grab_release()
        self.win.destroy()
        if self.on_ok:
            self.on_ok(out)

    def _cancel(self):
        self.result = None
        self.win.grab_release()
        self.win.destroy()

    def show(self, w=380, h=None):
        if h:
            center_on(self.win, self.parent, w, h)
        else:
            self.win.update_idletasks()
            center_on(self.win, self.parent, w, self.win.winfo_reqheight())
        if self.on_ok is None:
            self.parent.wait_window(self.win)
        return self.result


# ---------------- 可滚动列表 ----------------
class ScrollList(tk.Frame):
    def __init__(self, master, **kw):
        tk.Frame.__init__(self, master, bg=BG, **kw)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0)
        self.canvas.pack(side='left', fill='both', expand=True)
        self.sb = tk.Scrollbar(self, orient='vertical', command=self.canvas.yview,
                               bg=PANEL, troughcolor=BG, activebackground=ACC,
                               relief='flat', bd=0, width=6)
        self.sb.pack(side='right', fill='y')
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.inner = tk.Frame(self.canvas, bg=BG)
        self.win_id = self.canvas.create_window((0, 0), window=self.inner, anchor='nw')
        self.inner.bind('<Configure>',
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>',
                         lambda e: self.canvas.itemconfig(self.win_id, width=e.width))
        self.canvas.bind_all('<MouseWheel>', self._wheel)

    def _wheel(self, e):
        w = self.winfo_containing(e.x_root, e.y_root)
        node = w
        while node is not None:
            if node == self.canvas:
                self.canvas.yview_scroll(int(-1 * (e.delta / 120)), 'units')
                return
            node = getattr(node, 'master', None)

    def clear(self):
        for c in self.inner.winfo_children():
            c.destroy()

    def width(self):
        self.update_idletasks()
        return self.canvas.winfo_width()


# ---------------- 主程序 ----------------
class ClawBoard:
    def __init__(self, root):
        self.root = root
        self.tab = 'clip'           # clip | phrase
        self.sel_clip = None
        self.sel_phrase = None
        self.search = tk.StringVar()
        self.autopaste = True
        self.collapsed = False
        self.prev_hwnd = None
        self.save_timer = None
        self._need_show = False

        self.data = self.load_data()

        root.title('ClawBoard')
        root.overrideredirect(True)
        root.attributes('-topmost', True)
        root.attributes('-alpha', 0.97)
        root.configure(bg=BG)

        self.build_ui()
        self.apply_geometry()
        self.render()
        self.root.after(120, self.render)   # 尺寸稳定后重排一次换行
        self.poll_clip()
        self.track_foreground()

    # ---------- 数据 ----------
    def load_data(self):
        d = {'clip': [], 'groups': [{'name': '默认', 'items': []}],
             'gi': 0, 'geom': None, 'autopaste': True}
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                for k in d:
                    if k in loaded:
                        d[k] = loaded[k]
            except Exception:
                pass
        if not d['groups']:
            d['groups'] = [{'name': '默认', 'items': []}]
        d['gi'] = min(max(0, d.get('gi', 0)), len(d['groups']) - 1)
        self.autopaste = d.get('autopaste', True)
        return d

    def save(self, later=False):
        def do():
            self.data['autopaste'] = self.autopaste
            self.data['geom'] = self.root.geometry()
            try:
                with open(DATA_FILE, 'w', encoding='utf-8') as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=1)
            except Exception:
                pass
            self.save_timer = None
        if later:
            if self.save_timer:
                self.root.after_cancel(self.save_timer)
            self.save_timer = self.root.after(600, do)
        else:
            do()

    # ---------- UI 骨架 ----------
    def build_ui(self):
        r = self.root
        # 标题栏
        self.bar = tk.Frame(r, bg=PANEL, height=30, cursor='fleur')
        self.bar.pack(fill='x')
        self.bar.pack_propagate(False)
        tk.Label(self.bar, text='⚡ ClawBoard', bg=PANEL, fg=ACC, font=FONT_TITLE).pack(side='left', padx=8)
        self.bar.bind('<ButtonPress-1>', self.start_move)
        self.bar.bind('<B1-Motion>', self.do_move)
        self.bar.bind('<Double-Button-1>', lambda e: self.toggle_collapse())

        for txt, cmd in (('✕', self.quit), ('📌', self.toggle_pin), ('—', self.toggle_collapse)):
            b = tk.Label(self.bar, text=txt, bg=PANEL, fg=FG2, font=FONT, width=3, cursor='hand2')
            b.pack(side='right')
            b.bind('<Button-1>', lambda e, c=cmd: c())
            b.bind('<Enter>', lambda e, b=b: b.configure(fg=FG))
            b.bind('<Leave>', lambda e, b=b: b.configure(fg=FG2))

        # 主体容器（折叠时整体隐藏，避免 pack 顺序错乱）
        self.body = tk.Frame(r, bg=BG)
        self.body.pack(fill='both', expand=True)

        # Tab 栏
        tabs = tk.Frame(self.body, bg=BG, height=32)
        tabs.pack(fill='x')
        tabs.pack_propagate(False)
        self.tab_clip = self.mk_tab(tabs, '剪贴板', 'clip')
        self.tab_phr = self.mk_tab(tabs, '常用语', 'phrase')

        # 分组条（仅常用语）
        self.gbar = tk.Frame(self.body, bg=BG, height=28)
        self.gname = tk.Label(self.gbar, text='', bg=BG, fg=FG, font=FONT_B, cursor='hand2')
        self.gname.pack(side='left', padx=(8, 2))
        self.gname.bind('<Button-1>', lambda e: self.group_menu())
        tk.Label(self.gbar, text='▾', bg=BG, fg=FG2, font=FONT_SM, cursor='hand2').pack(side='left')
        self.gbar.bind('<Button-1>', lambda e: self.group_menu())

        # 列表
        self.list = ScrollList(self.body)
        self.list.pack(fill='both', expand=True, padx=(6, 0), pady=4)

        # 底部工具条
        self.tool = tk.Frame(self.body, bg=PANEL, height=36)
        self.tool.pack(fill='x')
        self.tool.pack_propagate(False)

        e = tk.Entry(self.tool, textvariable=self.search, bg=CARD, fg=FG, insertbackground=FG,
                     relief='flat', font=FONT_SM, bd=0,
                     highlightthickness=1, highlightbackground=LINE, highlightcolor=ACC)
        e.pack(side='left', padx=6, ipady=3, fill='x', expand=True)
        e.bind('<KeyRelease>', lambda ev: self.render())
        self.search.set('')
        tk.Label(self.tool, text='搜索', bg=PANEL, fg=FG2, font=FONT_SM).pack(side='left', padx=(0, 6))

        self.mk_tool_btn('＋', '新增常用语', self.add_phrase)
        self.mk_tool_btn('拆', '拆词：把一段文字拆成多条常用语', self.split_words)
        self.mk_tool_btn('删', '删除选中项', self.del_sel)
        self.mk_tool_btn('清', '清空当前列表', self.clear_list)

        # 右下拉伸把手
        self.grip = tk.Label(r, text='◢', bg=BG, fg=LINE, font=('Consolas', 9), cursor='sizing')
        self.grip.place(relx=1.0, rely=1.0, anchor='se')
        self.grip.bind('<ButtonPress-1>', self.start_resize)
        self.grip.bind('<B1-Motion>', self.do_resize)

    def mk_tab(self, master, text, key):
        f = tk.Frame(master, bg=BG, cursor='hand2')
        f.pack(side='left', fill='y')
        lb = tk.Label(f, text=text, bg=BG, fg=FG2, font=FONT_B, padx=14, pady=6)
        lb.pack()
        bar = tk.Frame(f, bg=BG, height=2)
        bar.pack(fill='x', side='bottom')
        for w in (f, lb):
            w.bind('<Button-1>', lambda e: self.set_tab(key))
        f._lb = lb
        f._bar = bar
        f._key = key
        return f

    def mk_tool_btn(self, text, tip, cmd):
        b = tk.Label(self.tool, text=text, bg=CARD, fg=FG, font=FONT_B, width=3, cursor='hand2')
        b.pack(side='left', padx=2, pady=5)
        b.bind('<Button-1>', lambda e: cmd())
        b.bind('<Enter>', lambda e: (b.configure(bg=CARD_H), self.tip(tip)))
        b.bind('<Leave>', lambda e: b.configure(bg=CARD))
        return b

    def tip(self, text):
        self.bar.winfo_children()[0].configure(text='⚡ ' + text)

    # ---------- 布局 / 交互 ----------
    def apply_geometry(self):
        g = self.data.get('geom')
        ok = False
        if g and re.match(r'^\d+x\d+\+\d+\+\d+$', g):
            self.root.geometry(g)
            ok = True
        if not ok:
            w, h = 340, 470
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            self.root.geometry('%dx%d+%d+%d' % (w, h, sw - w - 14, sh - h - 62))

    def start_move(self, e):
        self._mx, self._my = e.x_root, e.y_root

    def do_move(self, e):
        dx = e.x_root - self._mx
        dy = e.y_root - self._my
        x = self.root.winfo_x() + dx
        y = self.root.winfo_y() + dy
        self.root.geometry('+%d+%d' % (x, y))
        self._mx, self._my = e.x_root, e.y_root

    def start_resize(self, e):
        self._rx, self._ry = e.x_root, e.y_root
        self._rw, self._rh = self.root.winfo_width(), self.root.winfo_height()

    def do_resize(self, e):
        w = max(240, self._rw + (e.x_root - self._rx))
        h = max(200, self._rh + (e.y_root - self._ry))
        self.root.geometry('%dx%d' % (w, h))
        self.render()

    def toggle_pin(self):
        cur = bool(self.root.attributes('-topmost'))
        self.root.attributes('-topmost', not cur)
        self.tip('已取消置顶' if cur else '窗口已置顶')

    def toggle_collapse(self):
        self.collapsed = not self.collapsed
        if self.collapsed:
            self._restore = self.root.geometry()
            x = self.root.winfo_x()
            y = self.root.winfo_y()
            self.body.pack_forget()
            self.root.geometry('210x30+%d+%d' % (x, y))
        else:
            self.body.pack(fill='both', expand=True)
            self.root.geometry(self._restore)
            self.render()

    def quit(self):
        self.save()
        self.root.destroy()

    # ---------- Tab / 分组 ----------
    def set_tab(self, key):
        self.tab = key
        self.render()

    def group_menu(self):
        m = tk.Menu(self.root, tearoff=0, bg=PANEL, fg=FG, bd=0,
                    activebackground=CARD_H, activeforeground=FG,
                    font=FONT, relief='flat')
        for i, g in enumerate(self.data['groups']):
            m.add_command(label=('● ' if i == self.data['gi'] else '   ') + g['name'],
                          command=lambda i=i: self.switch_group(i))
        m.add_separator()
        m.add_command(label='＋ 新建分组', command=self.new_group)
        m.add_command(label='✎ 重命名当前分组', command=self.rename_group)
        m.add_command(label='✕ 删除当前分组', command=self.del_group)
        m.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())

    def switch_group(self, i):
        self.data['gi'] = i
        self.save(True)
        self.render()

    def new_group(self):
        def done(v):
            if v and v[0].strip():
                self.data['groups'].append({'name': v[0].strip(), 'items': []})
                self.data['gi'] = len(self.data['groups']) - 1
                self.save(True)
                self.render()
        Dialog(self.root, '新建分组', [('分组名称', '新分组', False)], on_ok=done).show(320)

    def rename_group(self):
        g = self.cur_group()

        def done(v):
            if v and v[0].strip():
                g['name'] = v[0].strip()
                self.save(True)
                self.render()
        Dialog(self.root, '重命名分组', [('分组名称', g['name'], False)], on_ok=done).show(320)

    def del_group(self):
        if len(self.data['groups']) <= 1:
            messagebox.showinfo('提示', '至少要保留一个分组')
            return
        g = self.cur_group()
        if not messagebox.askyesno('确认', '删除分组「%s」及其 %d 条常用语？' % (g['name'], len(g['items']))):
            return
        i = self.data['gi']
        del self.data['groups'][i]
        self.data['gi'] = max(0, i - 1)
        self.save(True)
        self.render()

    def cur_group(self):
        return self.data['groups'][self.data['gi']]

    # ---------- 渲染 ----------
    def render(self):
        # tab 高亮
        for t in (self.tab_clip, self.tab_phr):
            on = (t._key == self.tab)
            t._lb.configure(fg=FG if on else FG2)
            t._bar.configure(bg=ACC if on else BG)
        # 分组条
        if self.tab == 'phrase':
            if not self.gbar.winfo_ismapped():
                self.gbar.pack(fill='x', before=self.list)
            self.gname.configure(text=self.cur_group()['name'])
        else:
            if self.gbar.winfo_ismapped():
                self.gbar.pack_forget()

        self.list.clear()
        q = self.search.get().strip().lower()
        wrap = max(120, self.list.width() - 26)

        if self.tab == 'clip':
            items = self.data['clip']
            for it in items:
                if q and q not in it['text'].lower():
                    continue
                self.mk_card(it['id'], preview(it['text'], 140), it.get('time', ''),
                             selected=(it['id'] == self.sel_clip), wrap=wrap, kind='clip')
            if not self.list.inner.winfo_children():
                self.empty_tip('还没有复制记录\n去任意地方 Ctrl+C 试试')
        else:
            items = self.cur_group()['items']
            for it in items:
                if q and q not in (it['name'] + it['text']).lower():
                    continue
                head = it['name'] if it['name'] else preview(it['text'], 30)
                self.mk_card(it['id'], preview(it['text'], 140), head,
                             selected=(it['id'] == self.sel_phrase), wrap=wrap, kind='phrase')
            if not self.list.inner.winfo_children():
                self.empty_tip('这个分组还是空的\n点底部「＋」添加常用语')

    def empty_tip(self, text):
        tk.Label(self.list.inner, text=text, bg=BG, fg=FG2, font=FONT,
                 justify='left', pady=30).pack(anchor='w', padx=10)

    def mk_card(self, cid, body, sub, selected, wrap, kind):
        c = tk.Frame(self.list.inner, bg=CARD_S if selected else CARD, cursor='hand2')
        c.pack(fill='x', padx=6, pady=3)
        inner = tk.Frame(c, bg=c['bg'])
        inner.pack(fill='x', padx=8, pady=6)
        if kind == 'phrase':
            tk.Label(inner, text=sub, bg=c['bg'], fg=ACC, font=FONT_B,
                     anchor='w', wraplength=wrap, justify='left').pack(fill='x')
            tk.Label(inner, text=body, bg=c['bg'], fg=FG, font=FONT,
                     anchor='w', wraplength=wrap, justify='left').pack(fill='x')
        else:
            tk.Label(inner, text=body, bg=c['bg'], fg=FG, font=FONT,
                     anchor='w', wraplength=wrap, justify='left').pack(fill='x')
            tk.Label(inner, text=sub, bg=c['bg'], fg=FG2, font=FONT_SM,
                     anchor='w').pack(fill='x')

        def set_bg(w, color):
            try:
                w.configure(bg=color)
            except Exception:
                pass
            for ch in w.winfo_children():
                set_bg(ch, color)

        def enter(_):
            if cid != (self.sel_clip if kind == 'clip' else self.sel_phrase):
                set_bg(c, CARD_H)

        def leave(_):
            if cid != (self.sel_clip if kind == 'clip' else self.sel_phrase):
                set_bg(c, CARD)

        def click(_):
            self.on_click(cid, kind)

        def menu(e):
            self.item_menu(e, cid, kind)

        for w in (c, inner) + tuple(inner.winfo_children()):
            w.bind('<Button-1>', click)
            w.bind('<Button-3>', menu)
            w.bind('<Enter>', enter)
            w.bind('<Leave>', leave)

    # ---------- 行为 ----------
    def on_click(self, cid, kind):
        if kind == 'clip':
            self.sel_clip = cid
            it = self.find(cid, 'clip')
        else:
            self.sel_phrase = cid
            it = self.find(cid, 'phrase')
        if not it:
            return
        text = it['text']
        self.render()
        clip_write(text)
        if self.autopaste:
            hwnd = self.prev_hwnd
            self.root.withdraw()
            self.root.update()
            threading.Thread(target=self._paste_worker, args=(hwnd,), daemon=True).start()

    def _paste_worker(self, hwnd):
        """后台线程：把焦点还给上一个窗口再按 Ctrl+V"""
        try:
            if hwnd:
                time.sleep(0.08)
                u32.SetForegroundWindow(wintypes.HWND(hwnd))
                time.sleep(0.10)
                send_ctrl_v()
        except Exception:
            pass
        time.sleep(0.15)
        self._need_show = True

    def find(self, cid, kind):
        pool = self.data['clip'] if kind == 'clip' else self.cur_group()['items']
        for it in pool:
            if it['id'] == cid:
                return it
        return None

    def item_menu(self, e, cid, kind):
        it = self.find(cid, kind)
        if not it:
            return
        m = tk.Menu(self.root, tearoff=0, bg=PANEL, fg=FG, bd=0,
                    activebackground=CARD_H, activeforeground=FG, font=FONT, relief='flat')
        m.add_command(label='复制', command=lambda: clip_write(it['text']))
        m.add_command(label='粘贴到上一窗口', command=lambda: self.on_click(cid, kind))
        m.add_separator()
        if kind == 'clip':
            m.add_command(label='＋ 存为常用语', command=lambda: self.save_as_phrase(it['text']))
        else:
            m.add_command(label='✎ 编辑内容', command=lambda: self.edit_phrase(cid))
            m.add_command(label='🏷 命名', command=lambda: self.rename_phrase(cid))
        m.add_command(label='拆 拆词', command=lambda: self.split_words(it['text']))
        m.add_separator()
        m.add_command(label='✕ 删除', command=lambda: self.del_item(cid, kind))
        m.tk_popup(e.x_root, e.y_root)

    def del_item(self, cid, kind):
        if kind == 'clip':
            self.data['clip'] = [x for x in self.data['clip'] if x['id'] != cid]
        else:
            g = self.cur_group()
            g['items'] = [x for x in g['items'] if x['id'] != cid]
        self.save(True)
        self.render()

    def del_sel(self):
        if self.tab == 'clip':
            if not self.sel_clip:
                return self.tip('先选中一条')
            self.del_item(self.sel_clip, 'clip')
            self.sel_clip = None
        else:
            if not self.sel_phrase:
                return self.tip('先选中一条')
            self.del_item(self.sel_phrase, 'phrase')
            self.sel_phrase = None

    def clear_list(self):
        if self.tab == 'clip':
            if not messagebox.askyesno('确认', '清空全部剪贴板历史？'):
                return
            self.data['clip'] = []
            self.sel_clip = None
        else:
            if not messagebox.askyesno('确认', '清空分组「%s」？' % self.cur_group()['name']):
                return
            self.cur_group()['items'] = []
            self.sel_phrase = None
        self.save(True)
        self.render()

    # ---------- 常用语增删改 ----------
    def add_phrase(self):
        init = clip_read() or ''

        def done(v):
            name, text = v[0].strip(), v[1]
            if text.strip():
                self.push_phrase(name, text)
        Dialog(self.root, '新增常用语',
               [('名称（可留空，留空则自动取开头）', '', False),
                ('内容', init, True)], on_ok=done).show(400, 300)

    def save_as_phrase(self, text):
        def done(v):
            if v and v[1].strip():
                self.push_phrase(v[0].strip(), v[1])
        Dialog(self.root, '存为常用语',
               [('名称（可留空）', preview(text, 20), False),
                ('内容', text, True)], on_ok=done).show(400, 300)

    def push_phrase(self, name, text):
        g = self.cur_group()
        g['items'].insert(0, {'id': uid(), 'name': name, 'text': text})
        self.save(True)
        self.tab = 'phrase'
        self.render()

    def edit_phrase(self, cid):
        it = self.find(cid, 'phrase')
        if not it:
            return

        def done(v):
            if v and v[0].strip():
                it['text'] = v[0]
                self.save(True)
                self.render()
        Dialog(self.root, '编辑内容', [('内容', it['text'], True)], on_ok=done).show(400, 240)

    def rename_phrase(self, cid):
        it = self.find(cid, 'phrase')
        if not it:
            return

        def done(v):
            if v is not None:
                it['name'] = v[0].strip()
                self.save(True)
                self.render()
        Dialog(self.root, '命名', [('名称', it.get('name', ''), False)], on_ok=done).show(340)

    # ---------- 拆词 ----------
    def split_words(self, text=None):
        if text is None:
            if self.tab == 'clip' and self.sel_clip:
                it = self.find(self.sel_clip, 'clip')
                text = it['text'] if it else (clip_read() or '')
            elif self.tab == 'phrase' and self.sel_phrase:
                it = self.find(self.sel_phrase, 'phrase')
                text = it['text'] if it else (clip_read() or '')
            else:
                text = clip_read() or ''
        SplitDialog(self, text)

    # ---------- 剪贴板监听 ----------
    def poll_clip(self):
        global LAST_SEQ
        if self._need_show:
            self._need_show = False
            self.root.deiconify()
            self.root.attributes('-topmost', True)
            self.render()
        try:
            seq = clip_seq()
            if seq != LAST_SEQ:
                LAST_SEQ = seq
                txt = clip_read()
                if txt and txt.strip():
                    dup = [x for x in self.data['clip'] if x['text'] == txt]
                    if dup:
                        self.data['clip'].remove(dup[0])
                    self.data['clip'].insert(0, {'id': uid(), 'text': txt, 'time': now_str()})
                    if len(self.data['clip']) > 200:
                        self.data['clip'] = self.data['clip'][:200]
                    self.save(True)
                    if self.tab == 'clip':
                        self.render()
        except Exception:
            pass
        self.root.after(400, self.poll_clip)

    def track_foreground(self):
        try:
            h = u32.GetForegroundWindow()
            if h and h != self.root.winfo_id():
                self.prev_hwnd = h
        except Exception:
            pass
        self.root.after(300, self.track_foreground)


# ---------------- 拆词窗口 ----------------
class SplitDialog:
    MODES = ['自动（换行/逗号/分号/顿号/空格）', '按换行', '按逗号', '按空格', '按分号', '自定义分隔符']

    def __init__(self, app, text):
        self.app = app
        self.src = text
        self.win = tk.Toplevel(app.root)
        self.win.transient(app.root)
        dark_top(self.win, '拆词')
        self.win.configure(bg=BG)
        self.win.grab_set()

        body = tk.Frame(self.win, bg=BG)
        body.pack(fill='both', expand=True, padx=12, pady=8)

        tk.Label(body, text='源文本', bg=BG, fg=FG2, font=FONT_SM, anchor='w').pack(fill='x')
        self.txt = tk.Text(body, height=5, bg=CARD, fg=FG, insertbackground=FG, relief='flat',
                           font=FONT, wrap='word', bd=0, highlightthickness=1,
                           highlightbackground=LINE, highlightcolor=ACC)
        self.txt.insert('1.0', text)
        self.txt.pack(fill='x', pady=(2, 8))

        row = tk.Frame(body, bg=BG)
        row.pack(fill='x', pady=(0, 6))
        tk.Label(row, text='分隔方式', bg=BG, fg=FG2, font=FONT_SM).pack(side='left')
        self.mode = tk.StringVar(value=self.MODES[0])
        mb = tk.Label(row, text='▾ 选择', bg=CARD, fg=FG, font=FONT_SM, padx=8, pady=3, cursor='hand2')
        mb.pack(side='right')
        mb.bind('<Button-1>', lambda e: self.mode_menu(mb))

        self.custom = tk.Entry(body, bg=CARD, fg=FG, insertbackground=FG, relief='flat',
                               font=FONT, bd=0, highlightthickness=1,
                               highlightbackground=LINE, highlightcolor=ACC)
        self.custom.insert(0, '|')
        self.custom.pack(fill='x', pady=(0, 6))

        self.prev = tk.Label(body, text='', bg=BG, fg=ACC, font=FONT_SM, anchor='w',
                             wraplength=330, justify='left')
        self.prev.pack(fill='x', pady=(0, 6))

        btns = tk.Frame(body, bg=BG)
        btns.pack(fill='x')
        self.mk(btns, '拆成常用语', ACC, self.ok).pack(side='right', padx=(6, 0))
        self.mk(btns, '预览', '#3a3f4d', self.do_preview).pack(side='right')
        self.mk(btns, '取消', '#3a3f4d', self.cancel).pack(side='left')
        self.win.bind('<Escape>', lambda e: self.cancel())
        self.win.protocol('WM_DELETE_WINDOW', self.cancel)
        self.do_preview()
        center_on(self.win, self.app.root, 380, 360)

    def mk(self, master, text, color, cmd):
        b = tk.Label(master, text=text, bg=color, fg='#fff', font=FONT_B, padx=12, pady=5, cursor='hand2')
        b.bind('<Button-1>', lambda e: cmd())
        return b

    def mode_menu(self, anchor):
        m = tk.Menu(self.win, tearoff=0, bg=PANEL, fg=FG, bd=0,
                    activebackground=CARD_H, activeforeground=FG, font=FONT, relief='flat')
        for x in self.MODES:
            m.add_command(label=x, command=lambda x=x: (self.mode.set(x), self.do_preview()))
        m.tk_popup(anchor.winfo_rootx(), anchor.winfo_rooty() + anchor.winfo_height())

    def do_split(self):
        raw = self.txt.get('1.0', 'end-1c')
        m = self.mode.get()
        if m == self.MODES[0]:
            parts = re.split(r'[\r\n,;；，、\s]+', raw)
        elif m == self.MODES[1]:
            parts = re.split(r'[\r\n]+', raw)
        elif m == self.MODES[2]:
            parts = re.split(r'[,，]+', raw)
        elif m == self.MODES[3]:
            parts = re.split(r'[ \t]+', raw)
        elif m == self.MODES[4]:
            parts = re.split(r'[;；]+', raw)
        else:
            sep = self.custom.get()
            parts = raw.split(sep) if sep else [raw]
        return [p.strip() for p in parts if p.strip()]

    def do_preview(self):
        parts = self.do_split()
        self.prev.configure(text='预览：共 %d 条 → %s' % (len(parts), ' | '.join(parts[:6]) + (' …' if len(parts) > 6 else '')))

    def ok(self):
        parts = self.do_split()
        if not parts:
            self.prev.configure(text='没拆出任何内容', fg=DANGER)
            return
        g = self.app.cur_group()
        for p in parts:
            g['items'].insert(0, {'id': uid(), 'name': preview(p, 12), 'text': p})
        self.app.save(True)
        self.app.tab = 'phrase'
        self.app.render()
        self.app.tip('已拆出 %d 条常用语' % len(parts))
        self.win.grab_release()
        self.win.destroy()

    def cancel(self):
        self.win.grab_release()
        self.win.destroy()


# ---------------- 入口 ----------------
def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    app = ClawBoard(root)
    root.protocol('WM_DELETE_WINDOW', app.quit)
    root.mainloop()


if __name__ == '__main__':
    main()
