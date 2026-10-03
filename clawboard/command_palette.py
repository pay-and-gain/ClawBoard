# -*- coding: utf-8 -*-
"""命令面板（Ctrl+Shift+P）：模糊过滤命令 + 回车执行。

UI 层职责：居中浮层（Toplevel + transient + topmost），顶部 Entry 输入即过滤，
下方 Listbox 展示「命令名 — 描述」，回车执行、Esc 关闭、↑↓ 移动选中。

纯逻辑部分（COMMANDS 注册表 + build_registry + filter_commands）不依赖 Tk，
可被 tests/_t30.py 直接单测。
"""
import tkinter as tk

from clawboard.config import FONT, FONT_SM
from clawboard.theme import T
from clawboard.widgets import dark_top, center_on, safe_release


# 命令注册表：(命令名, 描述, 解析回调)。解析回调接收 app，返回对应绑定方法。
# 用 lambda 而非直接绑定方法，是为了让本模块保持无 Tk 实例依赖、注册表可单测；
# build_registry(app) 在实例化面板时才把回调解析成真正的 bound method。
COMMANDS = [
    ('清空历史', '清空当前列表（按设置保留收藏）', lambda app: app.clear_list),
    ('暂停/恢复监听', '开关剪贴板监听', lambda app: app.toggle_listen),
    ('导出全部', '导出当前筛选或多选内容', lambda app: app.open_export),
    ('文本变换', '对选中内容做大小写/JSON 等变换', lambda app: app.open_transform),
    ('新增常用语', '把当前剪贴板内容存为常用语', lambda app: app.add_phrase),
    ('打开设置', '打开设置面板', lambda app: app.open_settings),
    ('面板置顶开关', '切换窗口是否始终置顶', lambda app: app.toggle_pin),
    ('折叠/展开面板', '把面板收成标题栏或展开', lambda app: app.toggle_collapse),
    ('退出程序', '退出 ClawBoard', lambda app: app.quit_app),
]


def build_registry(app):
    """把 COMMANDS 里的解析回调绑定到 app，得到可直接调用的 (命令名, 描述, 回调) 列表。"""
    return [(name, desc, resolve(app)) for name, desc, resolve in COMMANDS]


def filter_commands(query, commands):
    """对命令注册表做大小写不敏感子串过滤。

    - query 为空串 / 空白 / None：返回全部（保持注册表原序）
    - 非空：命中「命令名」或「描述」任一即保留
    - 排序：命令名前缀命中 > 命令名包含 > 描述包含；同级保持注册表原序

    返回与输入同构的三元组列表，便于 CommandPalette.refilter 直接消费。
    """
    q = (query or '').strip().lower()
    if not q:
        return list(commands)
    matched = []
    for i, (name, desc, cb) in enumerate(commands):
        nl = (name or '').lower()
        dl = (desc or '').lower()
        if q not in nl and q not in dl:
            continue
        if nl.startswith(q):
            rank = 0          # 名字前缀命中：最像用户想找的
        elif q in nl:
            rank = 1          # 名字包含
        else:
            rank = 2          # 描述包含
        matched.append((rank, i, name, desc, cb))
    matched.sort(key=lambda x: (x[0], x[1]))
    return [(n, d, cb) for _, _, n, d, cb in matched]


class CommandPalette:
    """居中浮层命令面板。构造入参 app（ClawBoard 实例）。"""

    W, H = 420, 360

    def __init__(self, app):
        self.app = app
        self.commands = build_registry(app)
        self.win = tk.Toplevel(app.root)
        self.win.transient(app.root)
        dark_top(self.win, '命令面板')
        self.win.attributes('-topmost', True)
        self.win.configure(bg=T['bg'])

        # 顶部输入框：输入即过滤（用 StringVar trace 监听，避免漏掉任何赋值来源）
        self.var = tk.StringVar()
        self.entry = tk.Entry(self.win, textvariable=self.var, bg=T['card'],
                              fg=T['fg'], insertbackground=T['fg'], relief='flat',
                              font=FONT, bd=0, highlightthickness=1,
                              highlightbackground=T['line'], highlightcolor=T['acc'])
        self.entry.pack(fill='x', padx=12, pady=(12, 6), ipady=5)
        self.var.trace_add('write', self._on_change)

        # 下方列表：展示过滤后的命令。exportselection=False 让选中高亮在
        # 输入框持有焦点时依然可见。
        self.lb = tk.Listbox(self.win, bg=T['card'], fg=T['fg'], bd=0, relief='flat',
                             highlightthickness=1, highlightbackground=T['line'],
                             selectbackground=T['acc'], selectforeground='#ffffff',
                             font=FONT_SM, activestyle='none', exportselection=False,
                             selectmode='browse')
        self.lb.pack(fill='both', expand=True, padx=12, pady=(0, 12))

        # 键盘交互统一绑在顶层窗口：Entry/Listbox 的事件都会冒泡到顶层 bindtag
        self.win.bind('<Escape>', lambda e: self._close_and_break())
        self.win.bind('<Return>', lambda e: self.execute())
        self.win.bind('<Up>', lambda e: self.move(-1))
        self.win.bind('<Down>', lambda e: self.move(1))
        # 双击列表项直接执行，单机由 Listbox 默认选中行为处理
        self.lb.bind('<Double-Button-1>', lambda e: self.execute())
        self.win.protocol('WM_DELETE_WINDOW', self.close)

        self.refilter()
        center_on(self.win, app.root, self.W, self.H)
        self.win.after(60, lambda: (self.win.lift(), self.entry.focus_force()))

    # ---------- 纯 UI 逻辑 ----------
    def _on_change(self, *_):
        self.refilter()

    def refilter(self):
        """按当前输入重建列表，并默认选中第一条。"""
        self.filtered = filter_commands(self.var.get(), self.commands)
        self.lb.delete(0, 'end')
        for name, desc, _cb in self.filtered:
            self.lb.insert('end', '%s — %s' % (name, desc))
        if self.filtered:
            self.lb.selection_clear(0, 'end')
            self.lb.selection_set(0)
            self.lb.activate(0)

    def move(self, delta):
        """↑↓ 移动选中项（循环内夹取，不越界）。"""
        size = self.lb.size()
        if not size:
            return 'break'
        try:
            cur = self.lb.curselection()
            idx = int(cur[0]) if cur else 0
        except Exception:
            idx = 0
        nxt = min(size - 1, max(0, idx + delta))
        self.lb.selection_clear(0, 'end')
        self.lb.selection_set(nxt)
        self.lb.activate(nxt)
        self.lb.see(nxt)
        return 'break'

    def execute(self):
        """执行当前选中命令：先关面板再调回调（有些回调会再弹窗）。"""
        if not self.filtered:
            return 'break'
        try:
            cur = self.lb.curselection()
            idx = int(cur[0]) if cur else 0
        except Exception:
            idx = 0
        if not (0 <= idx < len(self.filtered)):
            return 'break'
        _name, _desc, cb = self.filtered[idx]
        self.close()
        if callable(cb):
            try:
                cb()
            except Exception as e:
                self._note_failure(e)
        return 'break'

    def _note_failure(self, e):
        """回调执行异常不崩溃面板，写进运行日志（NO_SAVE 下静默）。"""
        try:
            self.app.note('命令面板执行失败：%s' % e)
        except Exception:
            pass

    def close(self):
        """释放并销毁浮层（可重复调用）。"""
        safe_release(self.win)
        try:
            self.win.destroy()
        except Exception:
            pass

    def _close_and_break(self):
        self.close()
        return 'break'
