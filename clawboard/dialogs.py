# -*- coding: utf-8 -*-
"""三个业务弹窗：SettingsWindow / TransformWindow / ExportDialog。"""
import json
import os
import time
import threading
import subprocess
import tkinter as tk

from clawboard.config import (
    APP_NAME, APP_VER, BASE_DIR, DATA_FILE, DEFAULT_SETTINGS, SCHEMA_VERSION,
    WHEEL_LINES, FONT, FONT_B, FONT_SM, UI_SCALE_LEVELS,
)
from clawboard.theme import T, set_theme
from clawboard.runtime import tx
from clawboard.classify import byte_size, detect_content_type
from clawboard.timefmt import full_time, now_ms
from clawboard.clipboard import clip_write
from clawboard.win32 import get_autostart, set_autostart
from clawboard.widgets import ScrollFrame, ThinBar, dark_top, center_on, safe_release


class SettingsWindow:
    HKS = [('Ctrl+Shift+V（默认）', 'ctrl+shift+v'), ('Alt+V', 'alt+v'),
           ('Ctrl+Alt+V', 'ctrl+alt+v'), ('不启用', 'none')]

    def __init__(self, app):
        self.app = app
        st = app.st
        self.win = tk.Toplevel(app.root)
        self.win.transient(app.root)
        dark_top(self.win, '设置')
        self.win.attributes('-topmost', True)
        self.win.after(60, lambda: (self.win.lift(), self.win.focus_force()))
        # 内容放进可滚动容器：选项变多了也不怕窗口装不下。
        # 注意：**先不 pack** —— 固定尺寸的底部区（数据管理 + 按钮）必须先 pack 到底部，
        # 否则带 expand 的滚动区会先把空间吃掉，底部按钮被压成 17px（实测踩过）。
        self.sc = ScrollFrame(self.win)
        body = self.sc.inner
        self.row_switch(body, '监听剪贴板', 'listen')
        self.row_switch(body, '单击后自动粘贴到上一窗口', 'autopaste')
        self.row_switch(body, '粘贴时去掉首尾空白（PDF/网页复制常带前导空格）', 'trim_paste')
        self.row_switch(body, '敏感内容打码显示', 'mask_sensitive')
        self.row_switch(body, '敏感内容不入库', 'skip_sensitive')
        self.row_switch(body, '列表中显示时间', 'show_time')
        self.row_switch(body, '记录来源窗口标题（隐私）', 'record_title')
        self.row_switch(body, '靠边自动隐藏（贴屏幕边缘自动收起）', 'edge_hide')
        self.row_autostart_switch(body)
        self.row_close_action(body)
        self.row_theme(body)
        self.row_bgcolor(body)
        self.row_switch(body, '窗口圆角（Win11 质感）', 'rounded',
                        after=self.app.apply_effects)
        self.row_switch(body, '毛玻璃背景（Acrylic，观感依赖桌面壁纸）', 'frosted',
                        after=self.app.apply_effects)
        self.row_switch(body, '复制后弹出提示（行数/字符数）', 'show_toast')
        # P1-2 音效：盲操（不看屏幕）时的听觉确认，默认关、两个开关互相独立
        self.row_switch(body, '复制音（剪贴板记下新内容时轻响一声）', 'sound_copy')
        self.row_switch(body, '粘贴音（成功粘贴后轻响一声）', 'sound_paste')
        self.row_switch(body, '键盘浏览时角落显示完整内容', 'show_preview')
        self.row_switch(body, '触发词快速粘贴（在常用语里设触发词，如 dz→地址）',
                        'trigger_enabled', after=self.app.apply_trigger_setting)
        self.row_ui_scale(body)
        self.row_switch(body, '折叠时贴到屏幕右下角', 'collapse_to_corner')
        self.row_hotkey(body)
        self.row_int(body, '历史最大条数（10-5000）', 'max_items')
        self.row_int(body, '捕获长度下限（0=不限）', 'min_len', lo=0, hi=1000)
        self.row_int(body, '捕获长度上限（0=不限）', 'max_len', lo=0, hi=200000, width=9)
        self.row_switch(body, '遵守「别记录我」标记（密码管理器用）', 'smart_private')
        self.row_switch(body, '清空历史时保留收藏项', 'keep_on_clear')
        self.row_text(body, '忽略这些程序（逗号分隔，支持 * ?）', 'ignore_apps',
                      '例：keepass, *bitwarden*, 微信')
        self.row_text(body, '忽略标题匹配的窗口（正则，分号分隔）', 'ignore_titles',
                      '例：密码; Password; ^私密')
        # ---- 底部按钮区（先 pack 到最底部；固定尺寸控件必须先占位，否则被 expand 挤扁）----
        btns = tk.Frame(self.win, bg=T['bg'])
        btns.pack(side='bottom', fill='x', padx=14, pady=(8, 10))
        b = tk.Label(btns, text='关闭', bg=T['acc'], fg='#fff', font=FONT_B,
                     padx=16, pady=5, cursor='hand2')
        b.pack(side='right')
        b.bind('<Button-1>', lambda e: (app.save(True), safe_release(self.win),
                                        self.win.destroy()))
        q = tk.Label(btns, text='退出程序', bg=T['danger'], fg='#fff', font=FONT_B,
                     padx=14, pady=5, cursor='hand2')
        q.pack(side='left')
        q.bind('<Button-1>', lambda e: (app.save(True), safe_release(self.win),
                                        self.win.destroy(), app.quit_app()))

        # ---- 数据管理区（在按钮区之上）：导出全部 / 彻底清理 ----
        danger = tk.Frame(self.win, bg=T['bg'])
        danger.pack(side='bottom', fill='x', padx=14, pady=(6, 0))
        tk.Label(danger, text='数据', bg=T['bg'], fg=T['fg2'], font=FONT_SM,
                 anchor='w').pack(fill='x')
        drow = tk.Frame(danger, bg=T['bg'])
        drow.pack(fill='x', pady=(2, 0))
        ex = tk.Label(drow, text='导出全部数据', bg=T['card'], fg=T['fg'],
                      font=FONT_SM, padx=10, pady=4, cursor='hand2')
        ex.pack(side='left')
        ex.bind('<Button-1>', lambda e: self.export_all())
        wb = tk.Label(drow, text='彻底清理所有数据', bg=T['danger'], fg='#fff',
                      font=FONT_SM, padx=10, pady=4, cursor='hand2')
        wb.pack(side='left', padx=(8, 0))
        wb.bind('<Button-1>', lambda e: self.wipe_all())

        # ---- 可滚动内容区（最后 pack，吃剩余空间）----
        self.sc.pack(fill='both', expand=True, padx=(14, 8), pady=(10, 0))
        self.win.bind('<Escape>', lambda e: (safe_release(self.win), self.win.destroy()))
        self.sc.bind_wheel_tree()          # 所有子控件接管滚轮
        center_on(self.win, app.root, 380, 470)
        self.win.after(80, self.sc._on_inner)

    def export_all(self):
        """把剪贴板历史 + 常用语全部导出为一个 JSON 文件。

        选 JSON 的理由：① 保留全部字段（时间/来源/类型/收藏/标签…），
        ② 结构清晰、将来可直接再导入，③ 格式化后人也读得懂。
        文件名带时间戳，不会互相覆盖。
        """
        clip = self.app.data.get('clip') or []
        groups = self.app.data.get('groups') or []
        n_phrase = sum(len(g.get('items') or []) for g in groups)
        if not clip and not n_phrase:
            self.app.tip('没有可导出的内容')
            return
        payload = {
            'app': APP_NAME,
            'version': APP_VER,
            'exported_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'clip_count': len(clip),
            'phrase_count': n_phrase,
            'clip': clip,
            'groups': groups,
        }
        name = 'ClawBoard导出_全部_%s.json' % time.strftime('%Y%m%d_%H%M%S')
        path = os.path.join(BASE_DIR, name)
        tmp = path + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=1)
            os.replace(tmp, path)          # 先写临时文件再原子替换，防半截文件
            self.app.tip('已导出 %d 条剪贴板 + %d 条常用语 → %s'
                         % (len(clip), n_phrase, name))
        except Exception as e:
            self.app.tip('导出失败：%s' % e)

    def wipe_all(self):
        """一键彻底清理：清空全部数据 + 关闭开机自启 + 删除数据文件。

        目的是让用户"无忧删除程序"—— 清完只剩程序本体，直接删文件夹即可。
        不可撤销，所以先弹二次确认（列出会删掉什么）。
        """
        def do():
            # 1) 关闭开机自启（清 HKCU\...\Run\ClawBoard）
            try:
                set_autostart(False)
            except Exception:
                pass
            # 2) 清空内存里的数据
            self.app.data['clip'] = []
            self.app.data['groups'] = [{'name': '默认', 'items': []}]
            self.app.data['gi'] = 0
            self.app.data['search_history'] = []
            self.app.data['geom'] = None
            try:
                self.app.save(True)
            except Exception:
                pass
            # 3) 删除数据文件与全部备份轮转
            removed = 0
            for p in (DATA_FILE, DATA_FILE + '.bak', DATA_FILE + '.bak.1',
                      DATA_FILE + '.bak.2', DATA_FILE + '.tmp'):
                try:
                    if os.path.exists(p):
                        os.remove(p)
                        removed += 1
                except Exception:
                    pass
            try:
                self.app.render()
            except Exception:
                pass
            self.app.tip('已彻底清理：删除 %d 个数据文件，已关闭开机自启' % removed)

        self.app.confirm(
            '确定要彻底清理吗？此操作不可撤销：\n\n'
            '· 删除全部剪贴板历史与常用语\n'
            '· 关闭开机自启（清理注册表项）\n'
            '· 删除本地全部数据文件与备份\n\n'
            '清理完成后，直接删除程序文件夹即彻底卸载。', do)

    def row_ui_scale(self, master):
        """界面等比缩放：点击在 50%/75%/100%/125%/150% 间循环切换"""
        r = tk.Frame(master, bg=T['bg'])
        r.pack(fill='x', pady=3)
        tk.Label(r, text='界面缩放（整体等比缩放，Ctrl+= / Ctrl+- 也可调）',
                 bg=T['bg'], fg=T['fg'], font=FONT, anchor='w').pack(side='left')
        lb = tk.Label(r, text='', bg=T['card'], fg=T['fg'], font=FONT_SM,
                      padx=8, pady=2, cursor='hand2')
        lb.pack(side='right')

        def paint():
            v = float(self.app.st.get('ui_scale') or 1.0)
            lb.configure(text='%d%%' % int(v * 100))

        def setv(_=None):
            levels = list(UI_SCALE_LEVELS)
            cur = float(self.app.st.get('ui_scale') or 1.0)
            i = levels.index(cur) if cur in levels else levels.index(1.0)
            nxt = levels[(i + 1) % len(levels)]
            self.app.set_ui_scale(nxt)
            paint()

        lb.bind('<Button-1>', setv)
        paint()

    def row_close_action(self, master):
        """点 ✕ 的行为：默认隐藏到托盘，也可改成直接退出"""
        r = tk.Frame(master, bg=T['bg'])
        r.pack(fill='x', pady=3)
        tk.Label(r, text='点标题栏 ✕ 时', bg=T['bg'], fg=T['fg'], font=FONT,
                 anchor='w').pack(side='left')
        lb = tk.Label(r, text='', bg=T['card'], fg=T['fg'], font=FONT_SM,
                      padx=8, pady=2, cursor='hand2')
        lb.pack(side='right')

        def paint():
            v = self.app.st.get('close_action', 'hide')
            lb.configure(text='隐藏到托盘' if v == 'hide' else '直接退出程序')

        def setv(val):
            self.app.st['close_action'] = val
            self.app.save(True)
            paint()
            self.app.tip('✕ 现在会%s' % ('隐藏到托盘' if val == 'hide' else '直接退出'))

        def menu(_=None):
            m = tk.Menu(self.win, tearoff=0, bg=T['panel'], fg=T['fg'], bd=0,
                        activebackground=T['card_h'], activeforeground=T['fg'],
                        font=FONT, relief='flat')
            m.add_command(label='隐藏到托盘（继续后台监听）', command=lambda: setv('hide'))
            m.add_command(label='直接退出程序', command=lambda: setv('quit'))
            m.tk_popup(lb.winfo_rootx(), lb.winfo_rooty() + lb.winfo_height())
        lb.bind('<Button-1>', menu)
        paint()

    def row_switch(self, master, text, key, after=None):
        r = tk.Frame(master, bg=T['bg'])
        r.pack(fill='x', pady=3)
        tk.Label(r, text=text, bg=T['bg'], fg=T['fg'], font=FONT, anchor='w').pack(side='left')
        st = self.app.st
        lb = tk.Label(r, text='', bg=T['card'], font=FONT_B, width=6, cursor='hand2')
        lb.pack(side='right')

        def paint():
            on = bool(st.get(key))
            lb.configure(text='开' if on else '关',
                         fg='#fff' if on else T['fg2'],
                         bg=T['acc'] if on else T['card'])

        def toggle(_=None):
            st[key] = not st.get(key)
            paint()
            self.app.save(True)
            if after:                     # 需要立即生效的开关（如圆角/毛玻璃外观）
                try:
                    after()
                except Exception:
                    pass
        lb.bind('<Button-1>', toggle)
        paint()

    def row_theme(self, master):
        r = tk.Frame(master, bg=T['bg'])
        r.pack(fill='x', pady=3)
        tk.Label(r, text='主题', bg=T['bg'], fg=T['fg'], font=FONT).pack(side='left')
        for name, label in (('dark', '暗色'), ('light', '亮色')):
            lb = tk.Label(r, text=label, bg=T['card'], fg=T['fg'], font=FONT,
                          padx=8, pady=2, cursor='hand2')
            lb.pack(side='right', padx=2)
            lb.bind('<Button-1>', lambda e, n=name: self.set_theme(n))

    def set_theme(self, name):
        self.app.st['theme'] = name
        self.app.save(True)
        set_theme(name)
        self.app.rebuild()
        safe_release(self.win)
        self.win.destroy()

    def row_hotkey(self, master):
        r = tk.Frame(master, bg=T['bg'])
        r.pack(fill='x', pady=3)
        tk.Label(r, text='全局唤起热键', bg=T['bg'], fg=T['fg'], font=FONT).pack(side='left')
        cur = [l for l, v in self.HKS if v == self.app.st.get('hotkey')]
        lb = tk.Label(r, text=cur[0] if cur else '未设置', bg=T['card'], fg=T['fg'],
                      font=FONT_SM, padx=8, pady=2, cursor='hand2')
        lb.pack(side='right')
        lb.bind('<Button-1>', lambda e: self.hk_menu(lb))

    def hk_menu(self, anchor):
        m = tk.Menu(self.win, tearoff=0, bg=T['panel'], fg=T['fg'], bd=0,
                    activebackground=T['card_h'], activeforeground=T['fg'],
                    font=FONT, relief='flat')
        for label, val in self.HKS:
            m.add_command(label=label, command=lambda v=val: self.set_hk(v))
        m.tk_popup(anchor.winfo_rootx(), anchor.winfo_rooty() + anchor.winfo_height())

    def set_hk(self, val):
        self.app.st['hotkey'] = val
        self.app.save(True)
        self.app.apply_hotkey()
        self.app.rebuild()
        self.app.tip('热键已更新' if val != 'none' else '热键已关闭')
        safe_release(self.win)
        self.win.destroy()

    def row_int(self, master, text, key, lo=10, hi=5000, width=7):
        r = tk.Frame(master, bg=T['bg'])
        r.pack(fill='x', pady=3)
        tk.Label(r, text=text, bg=T['bg'], fg=T['fg'], font=FONT).pack(side='left')
        v = tk.StringVar(value=str(self.app.st.get(key)))
        e = tk.Entry(r, textvariable=v, bg=T['card'], fg=T['fg'], insertbackground=T['fg'],
                     relief='flat', font=FONT, bd=0, width=width, justify='right',
                     highlightthickness=1, highlightbackground=T['line'],
                     highlightcolor=T['acc'])
        e.pack(side='right')

        def commit(_=None):
            try:
                n = min(hi, max(lo, int(v.get())))
            except Exception:
                n = int(DEFAULT_SETTINGS[key])
            self.app.st[key] = n
            v.set(str(n))
            self.app.save(True)
        e.bind('<Return>', commit)
        e.bind('<FocusOut>', commit)

    BG_CHOICES = (('默认（跟随主题）', ''), ('墨黑', '#12141a'), ('深蓝灰', '#1e2027'),
                  ('午夜蓝', '#16202e'), ('墨绿', '#16241f'), ('深紫', '#1d1a2b'),
                  ('浅灰', '#f4f5f8'), ('米白', '#faf7f0'), ('纯白', '#ffffff'))

    def row_bgcolor(self, master):
        """换背景：只选一个底色，面板/卡片/边框/文字色由 apply_theme 自动推导"""
        r = tk.Frame(master, bg=T['bg'])
        r.pack(fill='x', pady=3)
        tk.Label(r, text='背景色（选底色，其余自动配）', bg=T['bg'], fg=T['fg'],
                 font=FONT).pack(side='left')
        lb = tk.Label(r, text='', bg=T['card'], font=FONT_B, width=10, cursor='hand2')
        lb.pack(side='right')

        def paint():
            cur = (self.app.st.get('bg_color') or '').strip().lower()
            lb.configure(text=next((n for n, c in self.BG_CHOICES
                                    if c.lower() == cur), '默认'))

        def pick(c):
            self.app.st['bg_color'] = c
            self.app.save(True)
            self.app.rebuild()
            self.app.tip('背景已更换' if c else '已恢复主题默认背景')

        def menu(_=None):
            m = tk.Menu(self.win, tearoff=0, bg=T['panel'], fg=T['fg'], bd=0,
                        activebackground=T['card_h'], activeforeground=T['fg'],
                        font=FONT, relief='flat')
            for name, c in self.BG_CHOICES:
                m.add_command(label=name, command=lambda cc=c: pick(cc))
            m.tk_popup(lb.winfo_rootx(), lb.winfo_rooty() + lb.winfo_height())
        lb.bind('<Button-1>', menu)
        paint()

    def row_text(self, master, text, key, hint=''):
        """文本型设置：忽略名单这类可能写很长，占一整行，回车或失焦时提交"""
        r = tk.Frame(master, bg=T['bg'])
        r.pack(fill='x', pady=3)
        tk.Label(r, text=text, bg=T['bg'], fg=T['fg'], font=FONT,
                 anchor='w').pack(fill='x')
        if hint:
            tk.Label(r, text=hint, bg=T['bg'], fg=T['fg2'], font=FONT_SM,
                     anchor='w').pack(fill='x')
        v = tk.StringVar(value=str(self.app.st.get(key) or ''))
        e = tk.Entry(r, textvariable=v, bg=T['card'], fg=T['fg'], insertbackground=T['fg'],
                     relief='flat', font=FONT_SM, bd=0, highlightthickness=1,
                     highlightbackground=T['line'], highlightcolor=T['acc'])
        e.pack(fill='x', ipady=3, pady=(2, 0))

        def commit(_=None):
            self.app.st[key] = v.get().strip()
            self.app.save(True)
        e.bind('<Return>', commit)
        e.bind('<FocusOut>', commit)
        return e

    def row_autostart_switch(self, master):
        """开机自启：直接读写当前用户注册表 Run 项，状态以注册表真实值为准"""
        r = tk.Frame(master, bg=T['bg'])
        r.pack(fill='x', pady=3)
        tk.Label(r, text='开机自启（写当前用户注册表，可随时关）', bg=T['bg'],
                 fg=T['fg'], font=FONT, anchor='w').pack(side='left')
        lb = tk.Label(r, text='', bg=T['card'], font=FONT_B, width=6, cursor='hand2')
        lb.pack(side='right')

        def paint():
            on, _ = get_autostart()
            lb.configure(text='开' if on else '关',
                         fg='#fff' if on else T['fg2'],
                         bg=T['acc'] if on else T['card'])

        def toggle(_=None):
            on, _ = get_autostart()
            ok = set_autostart(not on)
            paint()
            if not ok:
                self.app.tip('开机自启设置失败（注册表不可写）')
            else:
                self.app.tip('开机自启已开启' if not on else '开机自启已关闭')
        lb.bind('<Button-1>', toggle)
        paint()

        r2 = tk.Frame(master, bg=T['bg'])
        r2.pack(fill='x', pady=(0, 4))
        b = tk.Label(r2, text='不想改注册表？点这里打开启动文件夹手动放快捷方式',
                     bg=T['bg'], fg=T['fg2'], font=FONT_SM, cursor='hand2', anchor='w')
        b.pack(anchor='w')
        b.bind('<Button-1>', lambda e: self.open_startup())

    @staticmethod
    def open_startup():
        path = os.path.join(os.environ.get('APPDATA', ''),
                            r'Microsoft\Windows\Start Menu\Programs\Startup')
        try:
            if os.path.isdir(path):
                os.startfile(path)
            else:
                subprocess.Popen(['explorer', path])
        except Exception:
            pass


class TransformWindow:
    """F4：左侧选变换，右侧看结果，底部三个动作。>5MB 走异步，不卡 UI"""

    def __init__(self, app, text, item=None):
        self.app = app
        self.item = item
        self.win = tk.Toplevel(app.root)
        self.win.transient(app.root)
        dark_top(self.win, '文本变换')
        self.win.attributes('-topmost', True)
        self.win.after(60, lambda: (self.win.lift(), self.win.focus_force()))
        mid = tk.Frame(self.win, bg=T['bg'])
        mid.pack(fill='both', expand=True, padx=10, pady=6)

        lf = tk.Frame(mid, bg=T['bg'])
        lf.pack(side='left', fill='y')
        self.lb = tk.Listbox(lf, bg=T['card'], fg=T['fg'], bd=0, relief='flat',
                             highlightthickness=1, highlightbackground=T['line'],
                             selectbackground=T['acc'], font=FONT_SM,
                             width=20, height=20)
        sb = ThinBar(lf, lambda f: self.lb.yview_moveto(f), width=8)
        self.lb.configure(yscrollcommand=sb.set)
        self.lb.pack(side='left', fill='y')
        sb.pack(side='left', fill='y', padx=(2, 0))
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
        tk.Label(rf, text='原文', bg=T['bg'], fg=T['fg2'], font=FONT_SM,
                 anchor='w').pack(fill='x')
        self.src = tk.Text(rf, height=9, bg=T['card'], fg=T['fg'],
                           insertbackground=T['fg'], relief='flat', font=FONT_SM,
                           wrap='word', bd=0, highlightthickness=1,
                           highlightbackground=T['line'], highlightcolor=T['acc'])
        self.src.insert('1.0', text[:200000])
        self.src.pack(fill='both', expand=True)
        tk.Label(rf, text='结果', bg=T['bg'], fg=T['fg2'], font=FONT_SM,
                 anchor='w').pack(fill='x')
        self.out = tk.Text(rf, height=9, bg=T['card'], fg=T['fg'],
                           insertbackground=T['fg'], relief='flat', font=FONT_SM,
                           wrap='word', bd=0, highlightthickness=1,
                           highlightbackground=T['line'], highlightcolor=T['acc'])
        self.out.pack(fill='both', expand=True)

        btns = tk.Frame(self.win, bg=T['bg'])
        btns.pack(fill='x', padx=10, pady=(0, 10))
        for label, cmd in (('复制到剪贴板', self.copy_out),
                           ('存为新条目', self.save_new),
                           ('覆盖原条目', self.overwrite)):
            b = tk.Label(btns, text=label, bg=T['card'], fg=T['fg'], font=FONT,
                         padx=10, pady=5, cursor='hand2')
            b.pack(side='left', padx=3)
            b.bind('<Button-1>', lambda e, c=cmd: c())
        b = tk.Label(btns, text='关闭', bg=T['acc'], fg='#fff', font=FONT_B,
                     padx=14, pady=5, cursor='hand2')
        b.pack(side='right')
        b.bind('<Button-1>', lambda e: (safe_release(self.win), self.win.destroy()))
        self.win.bind('<Escape>', lambda e: (safe_release(self.win), self.win.destroy()))
        center_on(self.win, app.root, 760, 540)

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

    def run(self):
        sel = self.lb.curselection()
        if not sel:
            return
        key = self._keys[int(sel[0])]
        if key is None:          # 分隔占位行：不触发任何变换
            return
        src = self.src.get('1.0', 'end-1c')
        if len(src.encode('utf-8')) > 5 * 1024 * 1024:
            self.out.delete('1.0', 'end')
            self.out.insert('1.0', '内容超过 5MB，后台处理中…')
            threading.Thread(target=self._work, args=(key, src), daemon=True).start()
        else:
            self._work(key, src)

    def _work(self, key, src):
        try:
            res, err = tx().apply(key, src), None
        except Exception as e:
            res, err = '', str(e)
        try:
            self.win.after(0, lambda: self._show(res, err))
        except Exception:
            pass

    def _show(self, res, err):
        self.out.delete('1.0', 'end')
        if err:
            self.out.configure(fg=T['danger'])
            self.out.insert('1.0', '变换失败：' + err)
        else:
            self.out.configure(fg=T['fg'])
            self.out.insert('1.0', res[:500000])

    def _out_text(self):
        t = self.out.get('1.0', 'end-1c')
        if not t:
            self.app.tip('先选一个变换')
            return None
        return t

    def copy_out(self):
        t = self._out_text()
        if t is not None:
            clip_write(t)
            self.app.tip('结果已复制到剪贴板')

    def save_new(self):
        t = self._out_text()
        if t is None:
            return
        self.app.tab = 'clip'
        self.app.ingest(t)
        self.app.tip('已存为新条目（原条目保留）')

    def overwrite(self):
        t = self._out_text()
        if t is None:
            return
        raw = self.app.find_raw_item(self.item['id']) if self.item else None
        if not raw:
            self.app.tip('没有可覆盖的原条目，请用「存为新条目」')
            return
        raw['text'] = t
        raw['content_size'] = byte_size(t)
        raw['content_type'] = detect_content_type(t)
        raw['updated_at'] = now_ms()      # created_at 原样保留
        self.app.save(True)
        self.app.render()
        self.app.tip('已覆盖原条目（首次复制时间未改）')


class ExportDialog:
    """F5：把历史导出成 TXT / CSV / JSON / Markdown"""

    def __init__(self, app):
        self.app = app
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
        b2 = tk.Label(btns, text='取消', bg=T['card_h'], fg=T['fg'], font=FONT,
                      padx=14, pady=5, cursor='hand2')
        b2.pack(side='right', padx=(0, 6))
        b2.bind('<Button-1>', lambda e: (safe_release(self.win), self.win.destroy()))
        center_on(self.win, app.root, 480, 340)

    def paint(self):
        cur = self.fmt.get()
        for r in self.rows:
            r._dot.configure(text='●' if r._v == cur else '○',
                             fg=T['acc'] if r._v == cur else T['fg2'])

    def do_export(self):
        fmt = self.fmt.get()
        stamp = time.strftime('%Y%m%d-%H%M%S')
        path = os.path.join(BASE_DIR, '导出_%s.%s' % (stamp, fmt if fmt != 'md' else 'md'))
        tmp = path + '.tmp'
        raw = [self.app.find_raw_item(x['id']) for x in self.items]
        raw = [x for x in raw if x]
        try:
            if fmt == 'txt':
                lines = []
                for i, it in enumerate(raw, 1):
                    lines.append('[%d] %s | %s | %s\n%s\n' % (
                        i, full_time(it.get('created_at')),
                        it.get('source_app') or 'unknown',
                        it.get('content_type') or 'text', it.get('text', '')))
                data = '\n'.join(lines).encode('utf-8')
            elif fmt == 'csv':
                import csv
                import io
                buf = io.StringIO()
                w = csv.writer(buf)
                w.writerow(['时间(本地)', '来源应用', '类型', '大小(字节)', '内容'])
                for it in raw:
                    w.writerow([full_time(it.get('created_at')),
                                it.get('source_app') or 'unknown',
                                it.get('content_type') or 'text',
                                it.get('content_size') or 0,
                                it.get('text', '').replace('\n', '\\n')])
                data = buf.getvalue().encode('utf-8-sig')     # BOM 防 Excel 中文乱码
            elif fmt == 'json':
                data = json.dumps({'version': SCHEMA_VERSION, 'items': raw},
                                  ensure_ascii=False, indent=1).encode('utf-8')
            else:
                lines = ['# 剪贴板导出 %s\n' % time.strftime('%F %T')]
                for it in raw:
                    lines.append('## %s · %s\n\n```\n%s\n```\n' % (
                        full_time(it.get('created_at')),
                        it.get('source_app') or 'unknown', it.get('text', '')))
                data = '\n'.join(lines).encode('utf-8')
            with open(tmp, 'wb') as f:
                f.write(data)
            os.replace(tmp, path)          # 先写 tmp 再改名，不留半截文件
        except Exception as e:
            self.app.note('导出失败：%s' % e)
            self.app.tip('导出失败：%s' % e)
            return
        self.app.tip('已导出 %d 条 → %s' % (len(raw), os.path.basename(path)))
        safe_release(self.win)
        self.win.destroy()
