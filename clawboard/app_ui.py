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
from clawboard.tag import TAG_LABELS
from clawboard.clipboard import mask_text
from clawboard.widgets import Dialog
from clawboard.vlist import VirtualList
from clawboard import onboard
from clawboard import update
from clawboard.ui_controls import UIActionButton
from clawboard.ui_icons import get_icon
from clawboard.query_presets import TYPE_FILTERS, clear_visual_filters, has_favorite, set_filter

import query as Q          # F3 查询解析器（独立模块，可单测）


class UiMixin:
    # ---------- UI ----------
    def build_ui(self):
        r = self.root
        # 重建主面板时保留独立弹窗及其编辑内容，不能遍历销毁所有 Toplevel。
        for name in ('bar', 'body', 'grip'):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.destroy()
        self.bar = tk.Frame(r, bg=T['panel'], height=scaled(BAR_H), cursor='fleur')
        self.bar.pack(fill='x')
        self.bar.pack_propagate(False)
        # 标题占满剩余宽度：整条标题栏（除了右边三个按钮）都是双击折叠的热区
        self.title_lb = tk.Label(self.bar, text=self._default_title(), bg=T['panel'],
                                 fg=T['fg'], font=FONT_TITLE, anchor='w')
        # 按钮必须先 pack：pack 按调用顺序分配空间，标题带 expand=True 后 pack 的话
        # 会把按钮挤成 1px（和之前滚动条被挤成 1px 是同一个坑）
        self._bar_btns = []
        for glyph, name, cmd, label in (('✕', 'close', self.hide, '隐藏面板'),
                                        ('📌', 'pin', self.toggle_pin, '面板置顶'),
                                        ('—', 'collapse', self.toggle_collapse, '折叠 / 展开')):
            b = UIActionButton(self.bar, text=glyph, icon=name, command=cmd,
                               tooltip=label, bg=T['panel'], size=24)
            b.pack(side='right', padx=scaled(1))
            self._bar_btns.append(b)
        self.workbench_btn = UIActionButton(self.bar, icon='workbench', command=self.open_workbench,
                                            tooltip='打开工作台（Ctrl+Shift+W）', bg=T['panel'], size=24)
        self.workbench_btn.pack(side='right', padx=scaled(2))
        self._brand_image = get_icon(r, 'logo', scaled(20))
        self.brand = tk.Label(self.bar, image=self._brand_image, bg=T['panel'])
        self.brand.pack(side='left', padx=(scaled(8), scaled(5)))
        self.title_lb.pack(side='left', padx=(0, scaled(4)), fill='x', expand=True)
        # 事件不会从子控件冒泡到父控件，所以标题文字上必须再绑一份：
        # 只绑 bar 的话，双击能用的只剩标题右侧那一小条空白（"很局限"就是这个原因）
        for w in (self.bar, self.title_lb, self.brand):
            w.bind('<ButtonPress-1>', self.start_move)
            w.bind('<B1-Motion>', self.do_move)
            w.bind('<Double-Button-1>', lambda e: self.toggle_collapse())

        self.body = tk.Frame(r, bg=T['bg'])
        self.body.pack(fill='both', expand=True)

        tabs = tk.Frame(self.body, bg=T['bg'], height=scaled(38))
        tabs.pack(fill='x')
        tabs.pack_propagate(False)
        self.filter_btn = tk.Button(tabs, text='筛选', command=self.filter_menu, bg=T['bg'],
                                    fg=T['fg2'], activebackground=T['card_h'], activeforeground=T['fg'],
                                    font=FONT_SM, bd=0, relief='flat', padx=scaled(6),
                                    highlightthickness=1, highlightbackground=T['bg'],
                                    highlightcolor=T.get('focus', T['acc']), takefocus=True)
        self.filter_btn.pack(side='right', padx=scaled(5), pady=scaled(5))
        self.filter_btn.bind('<Return>', lambda e: (self.filter_menu(), 'break')[1])
        self.tab_clip = self.mk_tab(tabs, '历史', 'clip')
        self.tab_phr = self.mk_tab(tabs, '常用语', 'phrase')
        self.tab_fav = self.mk_tab(tabs, '收藏', 'fav')

        self.gbar = tk.Frame(self.body, bg=T['bg'], height=scaled(28))
        self.gname = UIActionButton(self.gbar, text='', bg=T['bg'], fg=T['fg'],
                                    command=self.group_menu, size=None, font=FONT_B)
        self.gname.pack(side='left', padx=(8, 2))
        tk.Label(self.gbar, text='▾', bg=T['bg'], fg=T['fg2'], font=FONT_SM).pack(side='left')

        self.vlist = VirtualList(self.body, self.on_click_item,
                                 self.on_menu_item, self.on_hover_item)
        self.vlist.pack(fill='both', expand=True, padx=(scaled(6), 0), pady=scaled(4))
        # 空数据引导卡片：只创建不摆放（place），显示与否由 render() 决定。
        # 用 place 覆盖在 vlist 之上，而不是 pack 进队列 —— 这样不参与 pack 的
        # 空间分配，列表本身（含滚动/选中/多选）的逻辑一行都不用改。
        self.onboard = onboard.OnboardCard(
            self.body, on_load=self.load_samples, on_repo=self.open_repo,
            hotkey=self.st.get('hotkey', onboard.DEFAULT_HOTKEY))

        self.tool = tk.Frame(self.body, bg=T['panel'], height=scaled(TOOL_H))
        # 固定工具栏先分空间，列表最后伸缩；否则向上缩窗会把工具栏压成几像素。
        self.tool.pack(side='bottom', fill='x', before=self.vlist)
        self.tool.pack_propagate(False)
        # 横向同样先保留按钮，再让搜索框使用余量，避免窄窗里按钮被搜索框挤掉。
        self.tool_actions = tk.Frame(self.tool, bg=T['panel'])
        self.tool_actions.pack(side='right', fill='y')
        # Entry 的 width 按字符计，外层用像素限宽；宽窗也不再把空白全部分给搜索。
        self.search_box = tk.Frame(self.tool, bg=T['panel'], width=scaled(100))
        self.search_box.pack(side='left', padx=scaled(6))
        self.search_box.pack_propagate(False)
        self.search_entry = tk.Entry(self.search_box, textvariable=self.search, bg=T['card'],
                                     fg=T['fg'], insertbackground=T['fg'], relief='flat',
                                     font=FONT_SM, bd=0, width=8, highlightthickness=1,
                                     highlightbackground=T['line'], highlightcolor=T['acc'])
        self.search_box.configure(height=self.search_entry.winfo_reqheight() + scaled(6))
        self.search_entry.pack(fill='both', expand=True)
        # Entry 没有 placeholder，用一层灰字 Label 顶替：空着时提示可以怎么搜，
        # 一输入就消失。Label 会吃掉点击，所以补一个转发焦点
        self.search_ph = tk.Label(self.tool, bg=T['card'], fg=T['fg2'], font=FONT_SM,
                                  anchor='w', text='搜索…')
        self.search_ph.bind('<Button-1>', lambda e: self.search_entry.focus_set())
        if self._search_trace:
            self.search.trace_remove('write', self._search_trace)
        self._search_trace = self.search.trace_add('write', self._search_changed)
        self.search_entry.bind('<Escape>', lambda e: self.hide())
        self.search_entry.bind('<Return>', self.on_search_return)
        self.search_entry.bind('<Button-3>', lambda e: self.search_menu(e))
        self.search_entry.bind('<Control-a>', self.select_all_visible)
        self._tool_btns = []
        # 第三项是溢出菜单里的短文案：工具条的 tip 可以写长（悬停才看到），
        # 但菜单是整块弹出来的，用长提示会撑出一张比面板还宽的菜单
        for txt, tip2, menu2, cmd in (
                ('＋', '新增常用语', '新增常用语', self.add_phrase),
                ('删', '删除选中项', '删除选中项', self.del_sel),
                ('拆', '拆词：把一段文字拆成多条常用语', '拆词', self.split_words),
                ('清', '清空当前列表', '清空列表', self.clear_list),
                ('🔧', '文本变换（Ctrl+T）', '文本变换', self.open_transform),
                ('⚙', '设置', '设置', self.open_settings)):
            self._tool_btns.append((txt, self.mk_tool_btn(txt, tip2, cmd, menu2)))
        # 留一个 ⚙ 的句柄：发现新版本时可给它染色做提示（只改 fg，不动尺寸 → 不影响布局）
        self.setting_btn = next((b for t, b in self._tool_btns if t == '⚙'), None)
        # 窄面板放不下时的「⋯」溢出入口：收起的按钮都还能从这里点进去，功能不丢
        self.more_btn = UIActionButton(self.tool_actions, text='⋯', icon='more',
                                      command=self.more_menu, tooltip='更多操作', size=24)
        self.more_btn._pack_args = dict(side='left', padx=scaled(2), pady=scaled(9))
        # 面板变窄时按优先级收起次要按钮，别把它们挤成残废
        self._tool_hidden = ()
        self._last_tw = 0
        self.tool.bind('<Configure>', lambda e: self._layout_tool())
        self.tool.bind('<Map>', lambda e: self._layout_tool(), add='+')

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
        workbench = getattr(self, '_workbench_window', None)
        if workbench is not None and workbench.win.winfo_exists():
            workbench.refresh_style()

    def _sync_ph(self):
        """搜索框为空时显示灰字提示，有内容就藏起来"""
        try:
            if self.search.get():
                self.search_ph.place_forget()
            else:
                self.search_ph.place(in_=self.search_entry, x=5, rely=0.5, anchor='w',
                                     relwidth=1, width=-10)
        except Exception:
            pass

    def mk_tab(self, master, text, key):
        f = tk.Frame(master, bg=T['bg'], cursor='hand2')
        f.pack(side='left', fill='y')
        lb = tk.Button(f, text=text, bg=T['bg'], fg=T['fg2'], font=FONT_B,
                       command=lambda: self.set_tab(key), bd=0, relief='flat',
                       padx=scaled(8), pady=scaled(3), takefocus=True,
                       activebackground=T['card_h'], activeforeground=T['fg'],
                       highlightthickness=1, highlightbackground=T['bg'],
                       highlightcolor=T.get('focus', T['acc']))
        lb.pack(fill='both', expand=True)
        lb.bind('<Return>', lambda e: (self.set_tab(key), 'break')[1])
        bar = tk.Frame(f, bg=T['bg'], height=scaled(1))
        bar.pack(fill='x', side='bottom')
        f.bind('<Button-1>', lambda e: self.set_tab(key))
        f._lb, f._bar, f._key = lb, bar, key
        return f

    # 先缩短搜索框，再按实际控件宽度收起低频动作；新增、删除、拆词始终直接可见。
    TOOL_HIDE_PRIORITY = ('清', '🔧')

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
        sizes = {text: button.winfo_reqwidth() + 2 * button._pack_args['padx']
                 for text, button in self._tool_btns}
        more_width = self.more_btn.winfo_reqwidth() + 2 * self.more_btn._pack_args['padx']
        hidden = tuple(text for text in ('清', '🔧') if text in sizes)
        used = sum(size for key, size in sizes.items() if key not in hidden)
        if hidden:
            used += more_width
        for text in self.TOOL_HIDE_PRIORITY:
            if used + scaled(48 + 12) <= w:
                break
            if text not in hidden:
                hidden += (text,)
            used = sum(size for key, size in sizes.items() if key not in hidden) + more_width
        self.search_box.configure(width=max(1, min(scaled(100), w - used - scaled(12))))
        if hidden == getattr(self, '_tool_hidden', None):
            return
        self._tool_hidden = hidden
        for _, b in self._tool_btns:              # 全部收回，再按固定顺序排队
            b.pack_forget()
        self.more_btn.pack_forget()
        hide = set(hidden)
        for text, b in self._tool_btns:           # 固定顺序：＋删拆清🔧⚙
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
        names = {'＋': 'add', '删': 'delete', '拆': 'split', '清': 'clear',
                 '🔧': 'transform', '⚙': 'settings'}
        b = UIActionButton(self.tool_actions, text=text, icon=names[text], command=cmd,
                           tooltip=tip, size=24)
        # pady=9 垂直居中：TOOL_H 48 - 文字 25 - 9*2 = 5px 余量；参数存一份给 _layout_tool 复原
        b._pack_args = dict(side='left', padx=scaled(2), pady=scaled(9))
        b._tip_text = tip                 # 悬停提示（可以长）
        b._menu_text = menu_text or tip   # 溢出菜单里的短文案
        b._tip_cmd = cmd
        b.pack(**b._pack_args)
        return b

    def tip(self, text):
        # 提示太长会把标题栏顶满、盖到右侧按钮上，按可用宽度截断
        t = text or ''
        avail = max(80, self.title_lb.winfo_width() - 40)
        try:
            f = tkfont.Font(font=FONT_TITLE)
            while t and f.measure(t) > avail:
                t = t[:-1]
            if t != (text or ''):
                t = t.rstrip() + '…'
        except Exception:
            t = t[:18]
        self.title_lb.configure(text=t)
        self.root.after(2500, lambda: self.title_lb.configure(text=self._default_title()))

    def _default_title(self):
        readonly = bool(getattr(getattr(self, '_store', None), 'recovery_required', False))
        return APP_NAME + (' · 只读保护' if readonly else '')

    def confirm(self, text, on_yes):
        Dialog(self.root, '确认', [('', text, True)],
               on_ok=lambda v: on_yes(), ok_text='确定').show(430, 200)

    # ---------- Tab / 分组 ----------
    def set_tab(self, key):
        self.tab = 'clip' if key == 'fav' else key
        if key == 'fav':
            self.search.set(set_filter(self.search.get(), 'favorite', True))
        elif key == 'clip':
            self.search.set(set_filter(self.search.get(), 'favorite'))
        self.render()

    def filter_menu(self):
        menu = tk.Menu(self.root, tearoff=0, bg=T['panel'], fg=T['fg'], font=FONT,
                       activebackground=T['card_h'], activeforeground=T['fg'])
        for label, value in TYPE_FILTERS:
            menu.add_command(label=label, command=lambda v=value: self._set_visual_filter('type', v))
        menu.add_separator()
        menu.add_command(label='最近一天', command=lambda: self._set_visual_filter('time', '<1d'))
        menu.add_command(label='不限时间', command=lambda: self._set_visual_filter('time'))
        menu.add_separator()
        menu.add_command(label='清除可视筛选', command=lambda: self._apply_visual_query(
            clear_visual_filters(self.search.get())))
        menu.tk_popup(self.filter_btn.winfo_rootx(),
                      self.filter_btn.winfo_rooty() + self.filter_btn.winfo_height())

    def _set_visual_filter(self, field, value=None):
        self._apply_visual_query(set_filter(self.search.get(), field, value))

    def _apply_visual_query(self, query):
        self.search.set(query)
        self.render()

    def open_workbench(self):
        current = getattr(self, '_workbench_window', None)
        if current is not None and current.win.winfo_exists():
            current.refresh()
            current.win.deiconify()
            current.win.lift()
            current.win.focus_force()
            return
        from clawboard.workbench import WorkbenchWindow
        self._workbench_window = WorkbenchWindow(self, state=getattr(current, 'view_state', None))

    def locate_workbench_item(self, kind, cid, group_index=None):
        """Explicit navigation may change the quick-panel view; it never pastes."""
        if kind == 'phrase':
            groups = self.data.get('groups', [])
            if group_index is None or not 0 <= group_index < len(groups):
                return False
            pool = groups[group_index]['items']
        else:
            pool = self.data['clip']
        if not any(item.get('id') == cid for item in pool):
            self.tip('这条内容已不在当前资料中，请刷新工作台')
            return False
        if kind == 'phrase':
            self.data['gi'] = group_index
            self.sel_phrase = cid
        else:
            self.sel_clip = cid
        self.tab = 'phrase' if kind == 'phrase' else 'clip'
        self.search.set('')
        if getattr(self, 'hidden', False):
            self.toggle_show()
        if getattr(self, 'collapsed', False):
            self.toggle_collapse()
        self.render()
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        index = next((i for i, item in enumerate(self.vlist.items) if item.get('id') == cid), None)
        if index is not None:
            self.vlist.scroll_to_index(index)
        return True

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
            if len(self.data['groups']) <= 1:
                self.tip('至少要保留一个分组')
                return
            if not self._recycle_move([item['id'] for item in g['items']], group=g):
                return
            i = next(index for index, group in enumerate(self.data['groups']) if group is g)
            del self.data['groups'][i]
            self.data['gi'] = max(0, i - 1)
            self._recycle_changed()
        self.confirm('删除分组「%s」及其 %d 条常用语？内容移入回收站，可在30天内恢复。' %
                     (g['name'], len(g['items'])), do_del)

    # ---------- 渲染 ----------
    def visible_items(self):
        q = self.search.get().strip()
        pool = self.data['clip'] if self.tab == 'clip' else self.cur_group()['items']
        selection = self.sel_clip if self.tab == 'clip' else self.sel_phrase
        self.search_err = ''
        keyword = ''
        if q:
            application = getattr(self, 'application', None)
            if application is None:
                pool, condition = Q.match(q, pool)
            else:
                key = (q, self.tab, self.data.get('gi'), application.data_revision)
                cached = getattr(self, '_filter_result', None)
                if cached and cached[0] == key:
                    pool, condition = cached[1]
                else:
                    if getattr(self, '_filter_pending', None) != key:
                        self._start_filter(key, pool)
                    pool, condition = [], {'terms': [], 'errors': []}
            if condition['errors']:
                self.search_err = condition['errors'][0]
            pool = sorted(pool, key=lambda item: (
                -(item.get('pinned') or 0), -(item.get('use_count') or 0),
                -(item.get('last_used_at') or item.get('created_at') or 0)))
            keyword = condition['terms'][0] if condition['terms'] else ''
        projection = getattr(self, '_projection', None)
        if projection is None:
            from clawboard.viewmodels import ViewProjection
            self._projection = projection = ViewProjection()
        return projection.project(pool, self.tab, self.st), selection, keyword


    def _start_filter(self, key, pool):
        from copy import deepcopy
        snapshot = deepcopy(pool)
        self._filter_pending = key
        def accept(result):
            if self._filter_pending != key:
                return
            self._filter_pending = None
            current = (self.search.get().strip(), self.tab, self.data.get('gi'),
                       self.application.data_revision)
            if current == key:
                self._filter_result = (key, result)
            self.render()
        def failed(error):
            self._filter_pending = None
            self.note('搜索失败：' + type(error).__name__)
            self.tip('搜索未完成，请缩小范围后重试')
        submitted = self.application.tasks.submit(self.application.search.match, key[0], snapshot,
                                                key='filter', on_result=accept, on_error=failed)
        if submitted is None:
            self._filter_pending = None
            self.root.after(150, self.render)


    def _search_changed(self, *_):
        self._sync_ph()
        if self._search_job:
            self.root.after_cancel(self._search_job)
        self._search_job = self.root.after(120, self._finish_search_change)


    def _finish_search_change(self):
        self._search_job = None
        self.render()

    def ensure_current_results(self):
        """An action must never use rows from an earlier debounced query."""
        query = self.search.get().strip()
        view = (self.tab, self.data.get('gi'), query)
        ready = getattr(self, '_last_view_key', None) == view
        if query:
            key = (query, self.tab, self.data.get('gi'), self.application.data_revision)
            cached = self._filter_result
            ready = ready and not self._filter_pending and bool(cached and cached[0] == key)
        if ready:
            return True
        if self._search_job:
            self.root.after_cancel(self._search_job)
            self._search_job = None
        self.render()
        self.tip('搜索结果更新中，请稍后再试')
        return False

    def render(self):
        favorite = has_favorite(self.search.get())
        for t in (self.tab_clip, self.tab_phr, self.tab_fav):
            on = ((t._key == 'fav' and self.tab == 'clip' and favorite) or
                  (t._key == self.tab and (self.tab != 'clip' or not favorite)))
            t._lb.configure(fg=T['acc'] if on else T['fg2'],
                            bg=T['card_s'] if on else T['bg'])
            t._bar.configure(bg=T['bg'])
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
        # 常用语 Tab 空着时给针对性提示，而不是复述剪贴板那套"复制点什么"
        waiting = bool(self.search.get().strip() and self._filter_pending)
        self.vlist.set_empty_text('搜索中…' if waiting else
                                 ('还没有常用语，点 ＋ 新建' if self.tab == 'phrase' else None))
        view_key = (self.tab, self.data.get('gi'), self.search.get().strip())
        reset = getattr(self, '_last_view_key', None) != view_key
        self._last_view_key = view_key
        self.vlist.set_data(items, sel, kw, reset_scroll=reset, preserve_selection=waiting)
        if not waiting and getattr(self, '_dpi_deferred_view', None) is not None:
            self.restore_dpi_view()
        # 空数据引导：只在剪贴板 Tab、无搜索词、整库为空时显示；列表一旦有内容即自动隐藏。
        # 判定完全基于数据，所以"用户删光数据"后引导会自然回来。
        self._sync_onboard(onboard.should_show(self.tab, self.search.get(), self.data))

    # ---------- 空数据引导 ----------
    def _sync_onboard(self, show):
        """按需把引导卡片覆盖到列表区域 / 收起。

        卡片建在 build_ui 里、但从不参与 pack；这里用 place(in_=vlist) 精确铺满列表区，
        展开/折叠、重建 UI（换主题/缩放）都能自然跟随，不必单独记账。
        """
        ob = getattr(self, 'onboard', None)
        if ob is None:
            return
        try:
            if show:
                if not ob.winfo_ismapped():
                    ob.place(in_=self.vlist, relx=0, rely=0, relwidth=1, relheight=1)
                    ob.lift()
                ob.update_hotkey(self.st.get('hotkey', onboard.DEFAULT_HOTKEY))
            elif ob.winfo_ismapped():
                ob.place_forget()
        except tk.TclError:
            pass

    def load_samples(self):
        """把示例记录灌进剪贴板历史 —— 只在用户点「载入示例」时才调用。

        为什么不做成"空数据时自动写入"：那会在用户毫不知情的情况下改掉真实存档，
        新用户会疑惑"我明明没复制过这些"。示例必须是显式选择的结果，也正因如此，
        这一处是本功能里唯一会写数据的地方。
        """
        items = onboard.sample_items()
        for it in items:
            self.data['clip'].append(it)
        # 让 _seq 跟上示例里的最大 seq，否则之后 ingest 可能分配出重复 seq
        self._seq = max([self._seq] +
                        [int(x.get('seq') or 0) for x in self.data['clip']])
        self.application.history.sequence = max(self.application.history.sequence, self._seq)
        self.sel_clip = items[0]['id'] if items else None
        self.tab = 'clip'
        self.save(True)
        self.render()
        self.tip('已载入 %d 条示例，试试 ↑↓ 选择、回车粘贴' % len(items))

    def open_url(self, url):
        """用系统默认浏览器打开一个链接（标准库 webbrowser；失败只提示、不抛出）。"""
        import webbrowser
        try:
            webbrowser.open(url)
        except Exception as e:
            self.note('打开链接失败：%s' % e)

    def open_repo(self):
        """打开项目主页。"""
        self.open_url(onboard.REPO_URL)

    def open_releases(self):
        """打开最新 Release 下载页（P1-3「去下载」入口）。复用 open_url 同一套逻辑。"""
        self.open_url(onboard.RELEASES_URL)

    def refresh_update_marker(self):
        """发现新版本时给工具条 ⚙ 按钮染色（只改 fg，尺寸不变 → 不影响 _layout_tool）。

        为什么不加"点"或改文案：⚙ 按钮 width=3，多塞字符可能溢出/撑宽，进而打乱
        窄面板下的按钮收起阈值；改文字颜色零布局代价。悬停 tip 用现有设置提示即可。
        """
        b = getattr(self, 'setting_btn', None)
        if b is None:
            return
        try:
            if update.LATEST_NEW and update.LATEST:
                b.configure(fg=T['acc'])
            else:
                b.configure(fg=T['fg'])
        except tk.TclError:
            pass
