# -*- coding: utf-8 -*-
"""首次启动引导：空数据判定 + 引导卡片（纯 UI）+ 示例数据生成。

为什么单独成文件：
  引导是「一辈子只走一次」的边缘路径，塞进 app_ui 的渲染主路径只会把真正高频的
  逻辑挤得难读，也逼近「单文件 800 行」红线。放这里既隔离了边缘分支，也方便单测。

为什么卡片不写数据：
  引导卡片只负责让人看懂「这是什么、怎么用」。示例数据**只有用户主动点「载入示例」**
  时才由调用方（app_ui.load_samples）写进 self.data —— 否则新用户第一眼就会在真实存档里
  看到一堆自己没复制过的东西，既困惑、也违背「不污染真实数据」。

数据格式：本模块不新增 settings 字段、不改任何已有字段语义。示例条目按 ingest() 的
字段形态构造，Python 版 / C 版共用同一份数据文件时读到的都是普通文本记录。

自适应（P1-1 修复轮）：
  卡片被 app_ui 以 place(relheight=1) 铺满列表区，所以它的高度 = 列表区可用高度。
  当 UI 缩到 0.5 且窗口取最小尺寸时，可用高度会小于内容自然高度 —— 此时按优先级收起
  次要行（先快捷键行、再仓库链接、最后欢迎语副文案），**三步说明与主按钮永远保留**，
  避免主按钮被挤出可视区（这正是要修的低危缺陷）。内边距全部走 scaled()，随缩放一起缩。
"""
import time
import tkinter as tk

from clawboard.config import (APP_NAME, FONT, FONT_B, FONT_SM, FONT_TITLE, scaled)
from clawboard.theme import T
from clawboard.runtime import uid
from clawboard.classify import byte_size, classify, detect_content_type

REPO_URL = 'https://github.com/pay-and-gain/ClawBoard'
REPO_LABEL = 'github.com/pay-and-gain/ClawBoard'
DEFAULT_HOTKEY = 'ctrl+shift+v'

# 示例条目标题行：覆盖多种类型（链接 / 代码 / JSON / 颜色 / 普通文本 / 多行），
# 让新用户一眼看到「这面板能认出不同内容」。字段合法且可正常删除、粘贴。
_SAMPLE_ROWS = (
    ('https://github.com/pay-and-gain/ClawBoard', 'chrome.exe'),
    ('def greet(name):\n    return "Hello, " + name', 'code.exe'),
    ('{"tool": "ClawBoard", "version": "2.3.0"}', 'code.exe'),
    ('#4f8cff', 'photoshop.exe'),
    ('这是一条示例：你复制过的文字会自动出现在这里', 'notepad.exe'),
    ('你好，世界\n这是多行示例，用来演示「+N 行」角标', 'wechat.exe'),
)


def is_empty_data(data):
    """空数据 = 剪贴板为空 且 所有常用语分组都为空。

    刻意不引入"已引导过"的持久标记：用户把数据删光后应当再次看到引导，比"只引导一次"
    更符合直觉，也不需要新增字段（老版本读到即便忽略也毫无副作用）。
    """
    if not isinstance(data, dict):
        return True
    if data.get('clip'):
        return False
    for g in (data.get('groups') or []):
        if isinstance(g, dict) and g.get('items'):
            return False
    return True


def should_show(tab, query, data):
    """引导卡是否该显示：仅在剪贴板 Tab、搜索框为空、且整库为空时显示。

    抽成纯函数是为了可单测：渲染层只调用它，显示与否完全由数据决定，
    没有隐藏状态可比对，也就不会出现"删光了数据却看不到引导"的怪象。
    """
    return (tab == 'clip' and not (query or '').strip() and is_empty_data(data))


def _steps_text(hotkey):
    """三歩上手文案。热键从设置读，缺省回落到 ctrl+shift+v。"""
    hk = (hotkey or DEFAULT_HOTKEY).upper()
    return ('① 复制任意内容（文字 / 图片 / 文件），自动记下来\n'
            '② 按 %s 呼出这个面板\n'
            '③ ↑↓ 选中，回车即粘贴回刚才的窗口' % hk)


# 一行快捷键提示（放在三步下面，够用就好，不铺开成长表格）
HINT_TEXT = '快捷键：↑↓ 选择 · Enter 粘贴 · Ctrl+F 搜索 · Ctrl+1~9 快速粘贴 · Esc 隐藏'


def sample_items(base_ts=None):
    """生成示例记录（仅用户点「载入示例」时才写入 self.data）。

    为什么每条都显式给 created_at：norm_item 遇到缺 created_at 会补"估算值"并打上
    is_estimated=1；而示例是"看起来该很规整"的引导素材，不该显示成估算时间。
    各条错开 1 分钟，列表里的相对时间才不会全挤成同一刻。
    """
    base = int(base_ts if base_ts is not None else time.time() * 1000)
    n = len(_SAMPLE_ROWS)
    out = []
    for i, (txt, app) in enumerate(_SAMPLE_ROWS):
        ts = base - (n - i) * 60000
        out.append({
            'id': uid(),
            'text': txt,
            'created_at': ts,
            'updated_at': ts,
            'seq': i + 1,
            'source_app': app,
            'content_type': detect_content_type(txt),
            'kind_auto': classify(txt)[0],
            'content_size': byte_size(txt),
            'copy_count': 1,
            'fav': 0,
            'is_estimated': 0,
        })
    return out


class OnboardCard(tk.Frame):
    """空数据时的引导卡片：欢迎语 + 3 步上手 + 快捷键提示 + 仓库链接 + 载入示例按钮。

    纯 UI：不读也不写数据文件。显示 / 隐藏由 app_ui._sync_onboard 用 place/place_forget
    管理，卡片本身只管"长什么样"，因此不会和 vlist 的渲染逻辑耦合。

    自适应见模块 docstring：可用高度不足时按「hint → link → lead」的顺序收起次要行，
    title / steps / btn 三行永远保留，保证主按钮在任何缩放档 + 最小窗口下都完整可见。
    """

    # 空间不足时的收起顺序（越靠前越先被收起）；title/steps/btn 永不收起。
    _HIDE_ORDER = ('hint', 'link', 'lead')

    def __init__(self, master, on_load=None, on_repo=None, hotkey=DEFAULT_HOTKEY):
        tk.Frame.__init__(self, master, bg=T['bg'])
        self._on_load = on_load
        self._on_repo = on_repo
        self._avail = 0
        self._fitting = False
        self._hidden = ()
        self._rows = []      # [(name, widget, pack_args)]，pack 顺序即此列表顺序

        wrap = tk.Frame(self, bg=T['bg'])
        wrap.pack(fill='both', expand=True, padx=scaled(12), pady=scaled(8))
        self._wrap = wrap

        title = tk.Label(wrap, text='👋 欢迎使用 %s' % APP_NAME, bg=T['bg'], fg=T['fg'],
                         font=FONT_TITLE, anchor='w', bd=0, highlightthickness=0)
        self._add('title', title, {'fill': 'x'})

        self._lead = tk.Label(
            wrap,
            text='复制过的内容会自动收进这里；按热键呼出，选中回车即粘贴回刚才的窗口。',
            bg=T['bg'], fg=T['fg2'], font=FONT_SM, anchor='w', justify='left',
            bd=0, highlightthickness=0)
        self._add('lead', self._lead, {'fill': 'x', 'pady': (scaled(2), scaled(6))})

        self._steps = tk.Label(wrap, text=_steps_text(hotkey), bg=T['bg'], fg=T['fg'],
                               font=FONT, anchor='w', justify='left',
                               bd=0, highlightthickness=0)
        self._add('steps', self._steps, {'fill': 'x', 'pady': (0, scaled(5))})

        self._hint = tk.Label(wrap, text=HINT_TEXT, bg=T['bg'], fg=T['fg2'],
                              font=FONT_SM, anchor='w', justify='left',
                              bd=0, highlightthickness=0)
        self._add('hint', self._hint, {'fill': 'x', 'pady': (0, scaled(6))})

        self._link = tk.Label(wrap, text=REPO_LABEL, bg=T['bg'], fg=T['acc'],
                              font=(FONT[0], FONT[1], 'underline'), anchor='w',
                              cursor='hand2', bd=0, highlightthickness=0)
        self._add('link', self._link, {'fill': 'x'})
        self._link.bind('<Button-1>', lambda e: self._open_repo())
        self._link.bind('<Enter>', lambda e: self._link.configure(fg=T['acc2']))
        self._link.bind('<Leave>', lambda e: self._link.configure(fg=T['acc']))

        # 按钮文案自带"可随时删除"：省掉单独一行说明，窄面板下优先保住这个主操作
        self._btn = tk.Label(wrap, text='  载入示例数据（可随时删除）  ', bg=T['card'],
                             fg=T['fg'], font=FONT_B, cursor='hand2', pady=scaled(6),
                             bd=0, highlightthickness=0)
        self._add('btn', self._btn, {'anchor': 'w', 'pady': (scaled(8), 0)})
        self._btn.bind('<Button-1>', lambda e: self._click_load())
        self._btn.bind('<Enter>', lambda e: self._btn.configure(bg=T['card_h']))
        self._btn.bind('<Leave>', lambda e: self._btn.configure(bg=T['card']))

        self._relayout()
        wrap.bind('<Configure>', lambda e: self._reflow(e.width))
        # 卡片被 place(relheight=1) 铺满列表区 → 自身高度即可用高度，据此自适应收行
        self.bind('<Configure>', lambda e: self.set_available(e.height))

    # ---------- 布局 ----------
    def _add(self, name, widget, pack_args):
        widget._onboard_name = name
        self._rows.append((name, widget, pack_args))

    def _relayout(self):
        """按固定顺序重排：先全部收回，再按当前隐藏集合依次 pack。

        顺序必须写死 —— pack_forget 之后再 pack 只会追加到队尾，谁最后 pack
        谁跑到最下面，次序会乱（与 app_ui._layout_tool 踩的是同一个坑）。
        """
        for _, w, _ in self._rows:
            w.pack_forget()
        for name, w, pargs in self._rows:
            if name in self._hidden:
                continue
            w.pack(**pargs)

    def _set_hidden(self, names):
        names = tuple(n for n in self._HIDE_ORDER if n in set(names))
        if names == self._hidden:
            return
        self._hidden = names
        self._relayout()

    def visible_rows(self):
        """当前实际显示的行名（测试用，也便于调试）。"""
        return [n for n, _, _ in self._rows if n not in self._hidden]

    def set_available(self, avail_h):
        """列表区可用高度变化时调用（由卡片自身 <Configure> 驱动）。"""
        try:
            avail_h = int(avail_h)
        except Exception:
            return
        if avail_h <= 1 or avail_h == self._avail:
            return
        self._avail = avail_h
        self._autofit()

    def _autofit(self):
        """可用高度不足时，按 _HIDE_ORDER 逐步收起次要行，保证主按钮完整可见。"""
        if self._fitting or self._avail <= 0:
            return
        self._fitting = True
        try:
            for k in range(len(self._HIDE_ORDER) + 1):
                self._set_hidden(self._HIDE_ORDER[:k])
                self.update_idletasks()
                if self._wrap.winfo_reqheight() <= self._avail:
                    return
        finally:
            self._fitting = False

    def _reflow(self, width):
        """按卡片宽度设置自动换行宽度：窄面板下长句不再溢出被右侧裁掉。"""
        wl = max(120, width - 8)
        for lb in (self._lead, self._steps, self._hint):
            try:
                lb.configure(wraplength=wl)
            except tk.TclError:
                pass

    def update_hotkey(self, hotkey):
        """热键在设置里被改后刷新第②步文案（卡片只重画文字，不重建控件）。"""
        try:
            self._steps.configure(text=_steps_text(hotkey))
        except tk.TclError:
            pass

    # ---------- 回调 ----------
    def _open_repo(self):
        if self._on_repo:
            self._on_repo()

    def _click_load(self):
        if self._on_load:
            self._on_load()
