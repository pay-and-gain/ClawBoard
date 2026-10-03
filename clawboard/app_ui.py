# -*- coding: utf-8 -*-
"""UiMixin：主面板 UI 构建 + Tab/分组 + 渲染。

build_ui / _sync_ph / mk_tab / _layout_tool / more_menu / mk_tool_btn / tip / confirm
+ Tab/分组（set_tab / cur_group / group_menu / switch_group / new_group / rename_group /
  del_group）+ render / visible_items。
"""
import tkinter as tk
import tkinter.font as tkfont

from clawboard.config import (APP_NAME, BAR_H, TOOL_H, FONT, FONT_B, FONT_SM,
                              FONT_TITLE, scaled)
from clawboard.theme import T
from clawboard.classify import classify, byte_size, human_size, kind_icon, preview
from clawboard.timefmt import rel_time
from clawboard.clipboard import mask_text
from clawboard.widgets import Dialog
from clawboard.vlist import VirtualList

import query as Q          # F3 查询解析器（独立模块，可单测）


class UiMixin:
    # ---------- UI ----------
    def build_ui(self):
        r = self.root
        for w in list(r.winfo_children()):
            w.destroy()
        self.bar = tk.Frame(r, bg=T['panel'], height=scaled(BAR_H), cursor='fleur')
        self.bar.pack(fill='x')
        self.bar.pack_propagate(False)
        # 标题占满剩余宽度：整条标题栏（除了右边三个按钮）都是双击折叠的热区
        self.title_lb = tk.Label(self.bar, text='⚡ ' + APP_NAME, bg=T['panel'],
                                 fg=T['acc'], font=FONT_TITLE, anchor='w')
        # 按钮必须先 pack：pack 按调用顺序分配空间，标题带 expand=True 后 pack 的话
        # 会把按钮挤成 1px（和之前滚动条被挤成 1px 是同一个坑）
        self._bar_btns = []
        for txt, cmd, col in (('✕', self.hide, T['danger']),
                              ('📌', self.toggle_pin, None),
                              ('—', self.toggle_collapse, None)):
            # 按钮热区放大：更宽 + 更高（pady），不用瞄准
            b = tk.Label(self.bar, text=txt, bg=T['panel'], fg=T['fg2'], font=FONT,
                         width=4, pady=7, cursor='hand2')
            b.pack(side='right')
            b.bind('<Button-1>', lambda e, c=cmd: c())
            b.bind('<Enter>', lambda e, b=b, c=col: b.configure(fg=c or T['fg']))
            b.bind('<Leave>', lambda e, b=b: b.configure(fg=T['fg2']))
            self._bar_btns.append(b)
        self.title_lb.pack(side='left', padx=8, fill='x', expand=True)
        # 事件不会从子控件冒泡到父控件，所以标题文字上必须再绑一份：
        # 只绑 bar 的话，双击能用的只剩标题右侧那一小条空白（"很局限"就是这个原因）
        for w in (self.bar, self.title_lb):
            w.bind('<ButtonPress-1>', self.start_move)
            w.bind('<B1-Motion>', self.do_move)
            w.bind('<Double-Button-1>', lambda e: self.toggle_collapse())

        self.body = tk.Frame(r, bg=T['bg'])
        self.body.pack(fill='both', expand=True)

        tabs = tk.Frame(self.body, bg=T['bg'], height=32)
        tabs.pack(fill='x')
        tabs.pack_propagate(False)
        self.tab_clip = self.mk_tab(tabs, '剪贴板', 'clip')
        self.tab_phr = self.mk_tab(tabs, '常用语', 'phrase')

        self.gbar = tk.Frame(self.body, bg=T['bg'], height=28)
        self.gname = tk.Label(self.gbar, text='', bg=T['bg'], fg=T['fg'],
                              font=FONT_B, cursor='hand2')
        self.gname.pack(side='left', padx=(8, 2))
        self.gname.bind('<Button-1>', lambda e: self.group_menu())
        tk.Label(self.gbar, text='▾', bg=T['bg'], fg=T['fg2'], font=FONT_SM).pack(side='left')

        self.vlist = VirtualList(self.body, self.on_click_item,
                                 self.on_menu_item, self.on_hover_item)
        self.vlist.pack(fill='both', expand=True, padx=(6, 0), pady=4)

        self.tool = tk.Frame(self.body, bg=T['panel'], height=scaled(TOOL_H))
        self.tool.pack(fill='x')
        self.tool.pack_propagate(False)
        # width=8 只是"请求宽度"，靠 expand 去吃剩余空间。默认 20 字符会把工具条撑爆，
        # 于是最后一个按钮被压成 3px（又是这类"抢空间"的老问题）
        self.search_entry = tk.Entry(self.tool, textvariable=self.search, bg=T['card'],
                                     fg=T['fg'], insertbackground=T['fg'], relief='flat',
                                     font=FONT_SM, bd=0, width=8, highlightthickness=1,
                                     highlightbackground=T['line'], highlightcolor=T['acc'])
        self.search_entry.pack(side='left', padx=6, ipady=3, fill='x', expand=True)
        # Entry 没有 placeholder，用一层灰字 Label 顶替：空着时提示可以怎么搜，
        # 一输入就消失。Label 会吃掉点击，所以补一个转发焦点
        self.search_ph = tk.Label(self.tool, bg=T['card'], fg=T['fg2'], font=FONT_SM,
                                  anchor='w', text='搜索…')
        self.search_ph.bind('<Button-1>', lambda e: self.search_entry.focus_set())
        self.search.trace_add('write', lambda *a: self._sync_ph())
        self.search_entry.bind('<KeyRelease>', lambda e: self.render())
        self.search_entry.bind('<Escape>', lambda e: self.hide())
        self.search_entry.bind('<Return>', self.on_search_return)
        self.search_entry.bind('<Button-3>', lambda e: self.search_menu(e))
        self.search_entry.bind('<Control-a>', self.select_all_visible)
        self._tool_btns = []
        # 第三项是溢出菜单里的短文案：工具条的 tip 可以写长（悬停才看到），
        # 但菜单是整块弹出来的，用长提示会撑出一张比面板还宽的菜单
        for txt, tip2, menu2, cmd in (
                ('＋', '新增常用语', '新增常用语', self.add_phrase),
                ('拆', '拆词：把一段文字拆成多条常用语', '拆词', self.split_words),
                ('删', '删除选中项', '删除选中项', self.del_sel),
                ('清', '清空当前列表', '清空列表', self.clear_list),
                ('🔧', '文本变换（Ctrl+T）', '文本变换', self.open_transform),
                ('⚙', '设置', '设置', self.open_settings)):
            self._tool_btns.append((txt, self.mk_tool_btn(txt, tip2, cmd, menu2)))
        # 窄面板放不下时的「⋯」溢出入口：收起的按钮都还能从这里点进去，功能不丢
        self.more_btn = tk.Label(self.tool, text='⋯', bg=T['card'], fg=T['fg2'],
                                 font=FONT_B, width=3, cursor='hand2')
        self.more_btn._pack_args = dict(side='left', padx=2, pady=9)
        self.more_btn.bind('<Button-1>', self.more_menu)
        self.more_btn.bind('<Enter>',
                           lambda e: (self.more_btn.configure(bg=T['card_h']),
                                      self.tip('更多：新增 / 拆词 / 清空')))
        self.more_btn.bind('<Leave>', lambda e: self.more_btn.configure(bg=T['card']))
        # 面板变窄时按优先级收起次要按钮，别把它们挤成残废
        self._tool_hidden = ()
        self._last_tw = 0
        self.tool.bind('<Configure>', lambda e: self._layout_tool())

        self.grip = tk.Label(r, text='◢', bg=T['bg'], fg=T['line'], font=('Consolas', 9),
                             cursor='sizing')
        self.grip.place(relx=1.0, rely=1.0, anchor='se')
        self.grip.bind('<ButtonPress-1>', self.start_resize)
        self.grip.bind('<B1-Motion>', self.do_resize)
        self.grip.lower()      # 拖动手柄在右下角，压住工具条按钮的话按钮就像"被遮住"了
        # 窗口四周 6px 热区：四边 + 四角都能随意拉伸（不只右下角一个手柄）
        self.bind_edge_resize()
        # 兜住"手滑拖到看不见"：折叠状态下不设下限，否则折不成 210x30
        if not getattr(self, 'collapsed', False):
            mw, mh = self.min_size()
            self.root.minsize(mw, mh)
        self.root.after(60, self._sync_ph)     # 初始就该显示搜索框提示
        if getattr(self, 'collapsed', False):  # 换主题重建 UI 时要保住折叠态
            self.body.pack_forget()

    def _sync_ph(self):
        """搜索框为空时显示灰字提示，有内容就藏起来"""
        try:
            if self.search.get():
                self.search_ph.place_forget()
            else:
                self.search_ph.place(in_=self.search_entry, x=5, rely=0.5, anchor='w')
        except Exception:
            pass

    def mk_tab(self, master, text, key):
        f = tk.Frame(master, bg=T['bg'], cursor='hand2')
        f.pack(side='left', fill='y')
        lb = tk.Label(f, text=text, bg=T['bg'], fg=T['fg2'], font=FONT_B, padx=14, pady=6)
        lb.pack()
        bar = tk.Frame(f, bg=T['bg'], height=2)
        bar.pack(fill='x', side='bottom')
        for w in (f, lb):
            w.bind('<Button-1>', lambda e: self.set_tab(key))
        f._lb, f._bar, f._key = lb, bar, key
        return f

    # 窗口不够宽时按优先级把次要按钮收进「⋯」溢出菜单（🔧变换和 ⚙设置永远直接可见，
    # 删也跟着保留——有选中项时它是最高频的）。阈值按算式推出来，不是拍脑袋：
    #   按钮 30px + padx 2*2 = 34px；搜索框要留 ≥120px；entry padx 12px。
    #   关键：收 1 个按钮进「⋯」不省空间（少一个普通按钮多一个 ⋯，总位数不变），
    #   所以 ＋ 和 拆 必须同一阈值一起收，否则会出现"收了 1 个还是放不下"的尴尬档：
    #   6 位（全显：＋拆删清🔧⚙）→ W >= 34*6 + 12 + 120 = 336
    #   5 位（收 ＋拆）          → W >= 34*5 + 12 + 120 = 302
    #   MIN_W=280 → 4 位（收 ＋拆清 → 删🔧⚙ + ⋯）→ entry 132，够用
    # 注：v1.5.3 起移除了工具条上的「?」搜索语法帮助按钮（界面太挤），
    #     其功能仍在搜索框右键菜单里，入口没丢。
    TOOL_HIDE_AT = (('＋', 336), ('拆', 336), ('清', 302))

    def _layout_tool(self):
        """窄面板时把次要按钮收进「⋯」菜单，而不是让它们被压成残废。

        两个坑：
        1) pack_forget 之后再 pack 只能追加到队尾，谁在队尾谁跑到最右边。
           实测「宽 640 → 窄 349 → 宽 640」之后顺序变成 删🔧?⚙＋拆清（乱的）。
           所以宽度跨过阈值时按固定顺序整体重排一遍。
        2) 折叠时 body 被 pack_forget，宽度退化成 1px，这时算出来的显示集合是假的，
           还会把 _last_tw 写成 1，导致展开后不再重排。所以要先挡掉。
        """
        w = self.tool.winfo_width()
        if w <= 1 or not self.tool.winfo_ismapped():
            return
        if w == self._last_tw:
            return
        self._last_tw = w
        hidden = tuple(t for t, need in self.TOOL_HIDE_AT if w < scaled(need))
        if hidden == getattr(self, '_tool_hidden', None):
            return
        self._tool_hidden = hidden
        for _, b in self._tool_btns:              # 全部收回，再按固定顺序排队
            b.pack_forget()
        self.more_btn.pack_forget()
        hide = set(hidden)
        for text, b in self._tool_btns:           # 固定顺序：＋拆删清🔧?⚙
            if text not in hide:
                b.pack(**b._pack_args)
        if hidden:
            self.more_btn.pack(**self.more_btn._pack_args)

    def more_menu(self, e=None):
        """溢出菜单：收起的按钮一个都不丢，只是挪进菜单里"""
        hidden = getattr(self, '_tool_hidden', ()) or ()
        m = tk.Menu(self.root, tearoff=0, bg=T['panel'], fg=T['fg'], bd=0,
                    activebackground=T['card_h'], activeforeground=T['fg'],
                    font=FONT, relief='flat')
        for text, b in self._tool_btns:
            if text in hidden:
                m.add_command(label='%s  %s' % (text, b._menu_text),
                              command=b._tip_cmd)
        if e is not None:
            m.tk_popup(e.x_root, e.y_root)
        else:
            m.tk_popup(self.more_btn.winfo_rootx() + 2,
                       self.more_btn.winfo_rooty() - 8)

    def mk_tool_btn(self, text, tip, cmd, menu_text=None):
        # width=3 保证 emoji（🔧/⚙ 实测 17px）和汉字都完整显示；padx=2 让按钮之间
        # 有 4px 间距（padx=1 时 7 个按钮连成一坨，视觉上像被互相遮挡）。
        # 窄面板下由 _layout_tool 收进「⋯」菜单，宁可挪走也不要挤扁
        b = tk.Label(self.tool, text=text, bg=T['card'], fg=T['fg'], font=FONT_B,
                     width=3, cursor='hand2')
        # pady=9 垂直居中：TOOL_H 48 - 文字 25 - 9*2 = 5px 余量；参数存一份给 _layout_tool 复原
        b._pack_args = dict(side='left', padx=2, pady=9)
        b._tip_text = tip                 # 悬停提示（可以长）
        b._menu_text = menu_text or tip   # 溢出菜单里的短文案
        b._tip_cmd = cmd
        b.pack(**b._pack_args)
        b.bind('<Button-1>', lambda e: cmd())
        b.bind('<Enter>', lambda e: (b.configure(bg=T['card_h']), self.tip(tip)))
        b.bind('<Leave>', lambda e: b.configure(bg=T['card']))
        return b

    def tip(self, text):
        # 提示太长会把标题栏顶满、盖到右侧按钮上，按可用宽度截断
        t = text or ''
        avail = max(80, self.title_lb.winfo_width() - 40)
        try:
            f = tkfont.Font(font=FONT_TITLE)
            while t and f.measure('⚡ ' + t) > avail:
                t = t[:-1]
            if t != (text or ''):
                t = t.rstrip() + '…'
        except Exception:
            t = t[:18]
        self.title_lb.configure(text='⚡ ' + t)
        self.root.after(2500, lambda: self.title_lb.configure(text='⚡ ' + APP_NAME))

    def confirm(self, text, on_yes):
        Dialog(self.root, '确认', [('', text, True)],
               on_ok=lambda v: on_yes(), ok_text='确定').show(430, 200)

    # ---------- Tab / 分组 ----------
    def set_tab(self, key):
        self.tab = key
        self.render()

    def cur_group(self):
        return self.data['groups'][self.data['gi']]

    def group_menu(self):
        m = tk.Menu(self.root, tearoff=0, bg=T['panel'], fg=T['fg'], bd=0,
                    activebackground=T['card_h'], activeforeground=T['fg'],
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
            self.tip('至少要保留一个分组')
            return
        g = self.cur_group()

        def do_del():
            i = self.data['gi']
            del self.data['groups'][i]
            self.data['gi'] = max(0, i - 1)
            self.save(True)
            self.render()
        self.confirm('删除分组「%s」及其 %d 条常用语？此操作不可撤销。' %
                     (g['name'], len(g['items'])), do_del)

    # ---------- 渲染 ----------
    def visible_items(self):
        q = self.search.get().strip()
        out = []
        pool = self.data['clip'] if self.tab == 'clip' else self.cur_group()['items']
        sel = self.sel_clip if self.tab == 'clip' else self.sel_phrase
        self.search_err = ''
        kw = ''
        if q:
            pool, cond = Q.match(q, pool)
            if cond['errors']:
                self.search_err = cond['errors'][0]
            # 搜索态按「固定 → 使用次数 → 最近使用」排序；
            # 默认浏览（q 为空）保持插入顺序不动。
            pool = sorted(pool, key=lambda it: (
                -(it.get('pinned') or 0),
                -(it.get('use_count') or 0),
                -(it.get('last_used_at') or it.get('created_at') or 0),
            ))
            kw = cond['terms'][0] if cond['terms'] else ''
        for it in pool:
            text = it['text']
            name = it.get('name') or ''
            hits = it.get('sens') or []
            k = it.get('kind_auto')
            if not k:
                # 老记录（判定功能是后加的）补算一次并写回内存，之后不再重算
                k = classify(text)[0]
                it['kind_auto'] = k
            disp = text
            is_img = (it.get('content_type') == 'image')
            if is_img:
                k = 'image'
                disp = '图片 %s×%s' % (it.get('image_w'), it.get('image_h'))
            elif hits and self.st['mask_sensitive'] and not it.get('mask_off'):
                disp = mask_text(text, hits)
            size = int(it.get('content_size') or 0)
            if self.tab == 'phrase':
                sub = name or preview(text, 28)
                badge = human_size(byte_size(text))
            elif is_img:
                sub = '%s · 图片' % (it.get('source_app') or 'unknown')
                badge = '%s×%s' % (it.get('image_w'), it.get('image_h'))
            else:
                parts = []
                if self.st['show_time']:
                    parts.append(rel_time(it.get('created_at'), it.get('is_estimated')))
                parts.append(it.get('source_app') or 'unknown')
                nl = text.count('\n')
                if nl:
                    parts.append('+%d 行' % nl)     # PasteBar 的 "+N lines" 角标
                if int(it.get('copy_count') or 1) > 1:
                    parts.append('×%d' % it['copy_count'])
                if hits:
                    parts.append('⚠' + '/'.join(hits))
                sub = ' · '.join(parts)
                badge = '%s %s' % (kind_icon(k), human_size(size))
            if it.get('fav'):
                disp = '★ ' + disp
            if it.get('pinned'):
                disp = '📌 ' + disp
            out.append({'id': it['id'], 'disp': disp, 'text': text, 'sub': sub,
                        'badge': badge, 'kind': self.tab, 'sens': hits, 'kind_auto': k,
                        'created_at': it.get('created_at'),
                        'est': it.get('is_estimated'),
                        'app': it.get('source_app') or 'unknown',
                        'image_path': it.get('image_path')})
        return out, sel, kw

    def render(self):
        for t in (self.tab_clip, self.tab_phr):
            on = (t._key == self.tab)
            t._lb.configure(fg=T['fg'] if on else T['fg2'])
            t._bar.configure(bg=T['acc'] if on else T['bg'])
        if self.tab == 'phrase':
            if not self.gbar.winfo_ismapped():
                self.gbar.pack(fill='x', before=self.vlist)
            self.gname.configure(text=self.cur_group()['name'])
        else:
            if self.gbar.winfo_ismapped():
                self.gbar.pack_forget()
        items, sel, kw = self.visible_items()
        try:
            self.search_entry.configure(
                highlightbackground=T['danger'] if self.search_err else T['line'])
        except Exception:
            pass
        if self.search_err:
            self.tip('语法：' + self.search_err)
        self.vlist.set_data(items, sel, kw)
