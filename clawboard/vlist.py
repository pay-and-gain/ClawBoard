# -*- coding: utf-8 -*-
"""VirtualList 虚拟滚动列表：固定行高窗口化渲染，5000 条只创建可视区 widget。"""
import tkinter as tk

from clawboard.config import (scaled, ITEM_H, CARD_GAP, WHEEL_LINES,
                              FONT, FONT_SM, FONT_MONO)
from clawboard.theme import T
from clawboard.classify import preview
from clawboard.widgets import Tip, ThinBar, pack_static_then_fill


class VirtualList(tk.Frame):
    """固定行高窗口化渲染：5000 条只创建可视区 widget"""

    def __init__(self, master, on_click, on_menu, on_hover):
        tk.Frame.__init__(self, master, bg=T['bg'])
        self.on_click = on_click
        self.on_menu = on_menu
        self.on_hover = on_hover
        self.tip = Tip(self.winfo_toplevel())
        self.items = []
        self.sel = None
        self.multi = set()
        self.kw = ''
        self.pool = {}
        self.wids = {}
        self._vw = 0
        self._last_w = -1
        self._maxc = 0
        self._maxc2 = 40
        self.canvas = tk.Canvas(self, bg=T['bg'], highlightthickness=0, bd=0)
        self.sb = ThinBar(self, self._bar_move, width=8, on_wheel=self._wheel)
        # 顺序很重要：canvas 的请求宽度是 378px，先 pack 它会把后 pack 的滑动条压成 1px
        pack_static_then_fill(self, self.sb, self.canvas)
        self.canvas.configure(yscrollcommand=self.sb.set)
        self._acc = 0.0        # 滚轮增量累积：触控板/高精度滚轮的 delta 常小于 120
        self.show_num = False  # 按住 Ctrl 时在行首显示 1..9/0
        self.empty_msg = None  # 自定义空列表提示（None=用默认）；各 Tab 文案不同
        self._empty = None     # 空列表时那句提示文字（canvas text item）
        self.canvas.bind('<MouseWheel>', self._wheel)
        self.canvas.bind('<Configure>', lambda e: self.update_view())

    def set_empty_text(self, msg):
        """设置空列表提示文案（None 恢复默认）。

        剪贴板 Tab 默认提示"复制点什么"，但常用语 Tab 空着时这句话是错的 ——
        所以由编排层按 Tab 传入合适文案，列表控件本身不关心业务语义。
        """
        self.empty_msg = msg

    def _show_empty(self):
        """列表为空时给一句话，别留一大片空白让人以为程序坏了"""
        w = max(60, self.canvas.winfo_width())
        h = max(60, self.canvas.winfo_height())
        msg = ('没有匹配「%s」的条目' % self.kw if self.kw
               else (self.empty_msg or '这里还没有内容\n复制点什么，它就会出现在这里'))
        try:
            if self._empty is None:
                self._empty = self.canvas.create_text(
                    w // 2, h // 2, text=msg, fill=T['fg2'], font=FONT,
                    justify='center')
            else:
                self.canvas.itemconfigure(self._empty, text=msg)
                self.canvas.coords(self._empty, w // 2, h // 2)
        except tk.TclError:
            pass

    def _hide_empty(self):
        if self._empty is not None:
            try:
                self.canvas.delete(self._empty)
            except tk.TclError:
                pass
            self._empty = None

    def set_data(self, items, sel, kw):
        self.items = items
        self.sel = sel
        self.kw = kw
        self.clear_pool()
        self.canvas.yview_moveto(0)
        self.update_view()

    def clear_pool(self):
        for i in list(self.pool):
            self._drop(i)

    def _drop(self, i):
        w = self.pool.pop(i, None)
        wid = self.wids.pop(i, None)
        try:
            if wid:
                self.canvas.delete(wid)
        except Exception:
            pass
        try:
            if w:
                w.destroy()
        except Exception:
            pass

    def _wheel(self, e):
        """滚轮滚动。delta/120 直接取整会让触控板（delta=40/±1）永远为 0 滚不动，
        所以先把增量累加起来，攒够一格再滚。"""
        d = getattr(e, 'delta', 0)
        if not d:
            return 'break'
        self._acc += d / 120.0
        steps = int(self._acc)
        if not steps:
            return 'break'
        self._acc -= steps
        self.scroll_rows(-steps * WHEEL_LINES)
        return 'break'

    def _bar_move(self, first):
        """拖滑动条：first 是滑块顶端对应的比例"""
        self.canvas.yview_moveto(first)
        self.update_view()

    def scroll_rows(self, rows):
        """按行滚动（负值向下），夹在首尾之间，滚到头不会滚出空白"""
        n = len(self.items)
        if n <= 0 or not rows:
            return
        total = n * scaled(ITEM_H)
        h = max(1, self.canvas.winfo_height())
        top = self.canvas.canvasy(0) + rows * scaled(ITEM_H)
        top = max(0.0, min(max(0.0, total - h), top))
        self.canvas.yview_moveto(top / float(total))
        self.update_view()

    def yview_step(self, px):
        """按像素步进滚动（bench 与键盘翻页用）"""
        self.canvas.yview_scroll(max(1, int(px / scaled(ITEM_H))), 'units')

    def scroll_to_index(self, i):
        total = max(1, len(self.items) * scaled(ITEM_H))
        h = max(1, self.canvas.winfo_height())
        self.canvas.yview_moveto(max(0.0, min(1.0, (i * scaled(ITEM_H) - h / 2.0) / float(total))))
        self.update_view()

    def update_view(self):
        n = len(self.items)
        w = max(60, self.canvas.winfo_width())
        self._vw = w
        if self._last_w != w:
            self.canvas.configure(scrollregion=(0, 0, w, max(1, n * scaled(ITEM_H))))
            self._last_w = w
        else:
            self.canvas.configure(scrollregion=(0, 0, w, max(1, n * scaled(ITEM_H))))
        if n == 0:
            self.clear_pool()
            self._show_empty()
            return
        self._hide_empty()
        h = max(scaled(ITEM_H), self.canvas.winfo_height())
        top = self.canvas.canvasy(0)
        start = max(0, int(top // scaled(ITEM_H)))
        end = min(n, int((top + h) // scaled(ITEM_H)) + 2)
        for i in list(self.pool):
            if i < start or i >= end:
                self._drop(i)
        for i in range(start, end):
            f = self.pool.get(i)
            if f is None:
                f = self._mk_item(i)
                self.pool[i] = f
                self.wids[i] = self.canvas.create_window(
                    (0, i * scaled(ITEM_H) + scaled(CARD_GAP) // 2), window=f, anchor='nw',
                    width=w, height=scaled(ITEM_H) - scaled(CARD_GAP))
            else:
                self.canvas.coords(self.wids[i], 0, i * scaled(ITEM_H) + scaled(CARD_GAP) // 2)
                if f._vw != w:
                    self.canvas.itemconfig(self.wids[i], width=w)
                    f._vw = w
            f._idx = i
            self._layout(f, w)          # 宽度变了就重排：窄窗口下给正文让位
            self._fill(f, i)

    def _mk_item(self, i):
        f = tk.Frame(self.canvas, bg=T['card'], height=scaled(ITEM_H) - scaled(CARD_GAP), cursor='hand2')
        f.pack_propagate(False)
        f._idx = i
        f._vw = 0
        f._lw = None      # 上次布局用的宽度（见 _layout）
        f._numw = 0       # 当前序号列宽度，0 表示被让位给正文了
        # 序号列：按住 Ctrl 时显示 1..9/0，提示「Ctrl+数字直接粘贴」（Ditto QListCtrl.cpp:610）
        f._num = tk.Label(f, bg=T['card'], font=FONT_SM, fg=T['acc'], anchor='w')
        f._num.place(x=6, y=7, width=16, height=16)
        row = tk.Frame(f, bg=T['card'])
        row.place(x=24, y=6, relwidth=1, width=-112, height=18)
        f._row = row
        f._l1a = tk.Label(row, bg=T['card'], font=FONT, anchor='w')
        f._l1b = tk.Label(row, bg=T['card'], font=FONT, anchor='w', fg=T['acc'])
        f._l1c = tk.Label(row, bg=T['card'], font=FONT, anchor='w')
        for lb in (f._l1a, f._l1b, f._l1c):
            lb.pack(side='left')
        f._badge = tk.Label(f, bg=T['card'], font=FONT_SM, fg=T['fg2'], anchor='e')
        f._badge.place(relx=1.0, x=-10, y=6, anchor='ne', height=18, width=80)
        f._l2 = tk.Label(f, bg=T['card'], font=FONT_SM, fg=T['fg2'], anchor='w')
        f._l2.place(x=24, y=28, relwidth=1, width=-32, height=16)
        for wg in (f, row, f._num, f._l1a, f._l1b, f._l1c, f._l2, f._badge):
            wg.bind('<Button-1>', lambda e, ff=f: self.on_click(ff._idx, e))
            wg.bind('<Button-3>', lambda e, ff=f: self.on_menu(e, ff._idx))
            wg.bind('<Enter>', lambda e, ff=f: (self._hover(ff._idx, True),
                                                self.on_hover(ff._idx, e.x_root, e.y_root)))
            wg.bind('<Leave>', lambda e, ff=f: (self._hover(ff._idx, False),
                                                self.tip.hide()))
            # 鼠标停在条目上时事件不会冒泡到 canvas，必须逐个子控件接管滚轮
            wg.bind('<MouseWheel>', self._wheel)
        return f

    def _paint(self, f, c):
        f.configure(bg=c)
        f._row.configure(bg=c)
        f._num.configure(bg=c)
        f._l1a.configure(bg=c)
        f._l1b.configure(bg=c)
        f._l1c.configure(bg=c)
        f._l2.configure(bg=c)
        f._badge.configure(bg=c)

    def _find(self, cid):
        """按 id 找到可视区里对应的卡片（滚出可视区的条目没有 widget，返回 None）。"""
        for i, it in enumerate(self.items):
            if it.get('id') == cid:
                return self.pool.get(i)
        return None

    def flash(self, cid, times=3, gap=140):
        """让某条卡片快速闪几下作为反馈（粘贴/收藏等），不整窗闪。

        只改背景色、不碰选中态：base 取「选中/普通」色，闪烁期间在强调色与
        base 之间来回切，最后停在 base。条目被滚出可视区（_find 返回 None）时
        闪烁自然终止，不会有悬挂的 after。"""
        f = self._find(cid)
        if f is None:
            return
        base = T['card_s'] if cid == self.sel else T['card']
        flash_c = T['acc']

        def tick(remaining):
            f2 = self._find(cid)
            if f2 is None or remaining <= 0:
                return
            self._paint(f2, flash_c)
            self.after(gap, lambda r=remaining: tock(r))

        def tock(remaining):
            f2 = self._find(cid)
            if f2 is not None:
                self._paint(f2, base)
            if remaining > 1:
                self.after(gap, lambda r=remaining: tick(r - 1))

        tick(times)

    def _hover(self, i, on):
        f = self.pool.get(i)
        if not f or not (0 <= i < len(self.items)):
            return
        if self.items[i].get('id') == self.sel:
            return
        self._paint(f, T['card_h'] if on else T['card'])

    def _layout(self, f, w):
        """按卡片实际宽度分配横向空间。
        窄的时候先让序号列和徽章退出：窗口被拖到 192px 宽时，若还固定给徽章留 88px、
        给序号留 24px，正文只剩 60 多像素，看着就像"面板里没有内容"。"""
        if getattr(f, '_lw', None) == w:
            return
        f._lw = w
        num = 16 if w >= 190 else 0
        badge = 80 if w >= 240 else (48 if w >= 180 else 0)
        x0 = (6 + num + 2) if num else 7
        right = (badge + 10) if badge else 7
        f._numw = num
        f._num.place_configure(x=6, y=7, width=max(1, num), height=16)
        f._row.place_configure(x=x0, y=6, relwidth=1, width=-(x0 + right), height=18)
        f._l2.place_configure(x=x0, y=28, relwidth=1, width=-(x0 + 7), height=16)
        f._badge.place_configure(relx=1.0, x=-10, y=6, anchor='ne', height=18,
                                 width=max(1, badge))

    def _first_hit(self, body):
        """找出该高亮哪个词。
        原实现拿整串 `self.kw` 去 find，搜「hello world」这种多词时永远找不到 → 不高亮。
        CopyQ filterlineedit.cpp:198 是按空白拆词逐词匹配的（AND），这里照做：
        整串命中就整串高亮，否则取第一个能命中的词。"""
        kw = (self.kw or '').strip()
        if not kw:
            return '', -1
        low = body.lower()
        p = low.find(kw.lower())
        if p >= 0:
            return kw, p
        for w in kw.split():
            p = low.find(w.lower())
            if p >= 0:
                return w, p
        return '', -1

    def _fill(self, f, i):
        it = self.items[i]
        if it.get('id') == self.sel:
            c = T['card_s']
        elif it.get('id') in self.multi:
            c = T['card_m']
        else:
            c = T['card']
        self._paint(f, c)
        body = it.get('disp') or it.get('text', '')
        w = self._vw or 300
        maxc = max(8, int(w / 7.2))
        if self._maxc != maxc:
            self._maxc = maxc
            self._maxc2 = max(8, int(w / 6.5))
        f._num.configure(text=('0' if i == 9 else str(i + 1))
                         if (self.show_num and i < 10 and f._numw) else '')
        # 自适应：代码/JSON 用等宽字体，链接用强调色 —— 一眼看出这行是什么东西
        ka = it.get('kind_auto') or 'text'
        ft = FONT_MONO if ka in ('code', 'json') else FONT
        fg = T['acc'] if ka == 'url' else T['fg']
        kw, pos = self._first_hit(body)
        if pos >= 0 and kw:
            s = max(0, pos - 6)
            seg = body[s:s + maxc]
            a = seg[:pos - s]
            b = seg[pos - s:pos - s + len(kw)]
            cc = seg[pos - s + len(kw):]
            f._l1a.configure(text=a, fg=fg, font=ft)
            f._l1b.configure(text=b, font=ft)
            f._l1c.configure(text=preview(cc, max(1, maxc - len(a) - len(b))),
                             fg=fg, font=ft)
        else:
            f._l1a.configure(text=preview(body, maxc), fg=fg, font=ft)
            f._l1b.configure(text='', font=ft)
            f._l1c.configure(text='', font=ft)
        f._l2.configure(text=preview(it.get('sub', ''), self._maxc2 or 40),
                        fg=T['acc'] if it.get('kind') == 'phrase' else T['fg2'])
        f._badge.configure(text=it.get('badge', ''))
