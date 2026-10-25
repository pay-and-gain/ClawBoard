"""Tk settings adapter; persistence/export work is delegated to services."""
import os
import subprocess
import time
import tkinter as tk
from copy import deepcopy
from threading import Event
from clawboard import runtime, update
from clawboard.config import (APP_NAME, APP_VER, BASE_DIR, DATA_FILE, DEFAULT_SETTINGS,
                              FONT, FONT_B, FONT_SM, UI_SCALE_LEVELS)
from clawboard.theme import T, set_theme
from clawboard.win32 import get_autostart, set_autostart
from clawboard.widgets import ScrollFrame, dark_top, center_on, safe_release
from clawboard.exports import write_payload, new_export_path


class SettingsWindow:
    HKS = [('Ctrl+Shift+V（默认）', 'ctrl+shift+v'), ('Alt+V', 'alt+v'),
           ('Ctrl+Alt+V', 'ctrl+alt+v'), ('不启用', 'none')]

    def __init__(self, app):
        self.app = app
        self._closed = False
        self._export_pending = False
        self._export_cancel = Event()
        self._export_key = ('settings-export', id(self))
        st = app.st
        self.win = tk.Toplevel(app.root)
        self.win.transient(app.root)
        dark_top(self.win, '设置')
        self.win.attributes('-topmost', True)
        self.win.protocol('WM_DELETE_WINDOW', self.close)
        self.win.bind('<Destroy>', self._destroyed, add='+')
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
        self.row_switch(body, '列表中显示来源', 'show_source', after=app.render)
        self.row_switch(body, '列表中显示大小（字节数 / 图片尺寸）', 'show_size', after=app.render)
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
                      '例：keepass, *bitwarden*, 微信。⚠ 对「开机时补记」的剪贴板内容无效（补记无从得知来源应用），请依赖密码管理器自身的「不记录」标记')
        self.row_text(body, '忽略标题匹配的窗口（正则，分号分隔）', 'ignore_titles',
                      '例：密码; Password; ^私密')
        self.row_update(body)
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
        self.win.bind('<Escape>', lambda e: self.close())
        self.sc.bind_wheel_tree()          # 所有子控件接管滚轮
        center_on(self.win, app.root, 380, 470)
        self.win.after(80, self.sc._on_inner)

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

    def export_all(self):
        if runtime.NO_SAVE:
            self.app.tip('自测模式不写导出文件')
            return
        if not self._alive() or self._export_pending:
            return
        clip = deepcopy(self.app.data.get('clip') or [])
        groups = deepcopy(self.app.data.get('groups') or [])
        phrase_count = sum(len(group.get('items') or []) for group in groups)
        if not clip and not phrase_count:
            self.app.tip('没有可导出的内容')
            return
        payload = {'app': APP_NAME, 'version': APP_VER,
                   'exported_at': time.strftime('%Y-%m-%d %H:%M:%S'),
                   'clip_count': len(clip), 'phrase_count': phrase_count,
                   'clip': clip, 'groups': groups}
        path = new_export_path(BASE_DIR, 'json', prefix='ClawBoard导出_全部')

        def start():
            if runtime.NO_SAVE:
                self.app.tip('自测模式不写导出文件')
                return
            if not self._alive() or self._export_pending:
                return
            self._export_pending = True
            self._export_cancel.clear()

            def done(result):
                if self._alive():
                    self._export_pending = False
                    self.app.tip('已导出 %d 条剪贴板 + %d 条常用语 → %s'
                                 % (len(clip), phrase_count, os.path.basename(result)))

            def failed(error):
                if self._alive():
                    self._export_pending = False
                    self.app.tip('导出失败：%s' % error)

            future = self.app.application.tasks.submit(
                write_payload, path, payload, cancelled=self._export_cancel.is_set,
                key=self._export_key, on_result=done, on_error=failed)
            if future is None:
                self._export_pending = False
                self.app.tip('后台任务繁忙，请稍后重试')
            else:
                self.app.tip('正在后台导出全部数据…')

        records = clip + [item for group in groups for item in group.get('items') or []]
        sensitive = sum(bool(item.get('sens')) for item in records)
        if sensitive:
            self.app.confirm('其中 %d 条含敏感内容，将以明文导出。确定继续？' % sensitive, start)
        else:
            start()


    def wipe_all(self):
        """一键彻底清理：清空全部数据 + 关闭开机自启 + 删除数据文件。

        目的是让用户"无忧删除程序"—— 清完只剩程序本体，直接删文件夹即可。
        不可撤销，所以先弹二次确认（列出会删掉什么）。
        """
        if runtime.NO_SAVE:
            self.app.tip('自测模式不会删除文件或改动开机自启')
            return

        def do():
            # A confirmation may stay open while test/runtime state changes.
            if runtime.NO_SAVE:
                self.app.tip('自测模式不会删除文件或改动开机自启')
                return
            application = self.app.application
            was_listening = bool(self.app.st.get('listen'))
            self.app.st['listen'] = False
            application.invalidate_clipboard()
            self._export_cancel.set()
            application.tasks.invalidate(self._export_key)
            timer = getattr(self.app, 'save_timer', None)
            if timer:
                self.app.root.after_cancel(timer)
                self.app.save_timer = None
            try:
                # A previously accepted writer must finish before deletion;
                # otherwise that old snapshot could recreate private history.
                application.flush(timeout=5)
            except Exception:
                self.app.st['listen'] = was_listening
                if timer:
                    self.app.save(True)
                self.app.tip('清理已取消：待保存任务尚未完成，请稍后重试')
                return
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
            application.search.clear()
            application.mark_changed()
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
            if not os.path.exists(DATA_FILE):
                application.store.recovery_required = False
                application.store.migration_pending = False
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
            if key == 'listen':
                # The system adapter invalidates captures before a pause and
                # owns catch-up on resume; a second local implementation races.
                self.app.toggle_listen()
                paint()
                return
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

    # ---------- P1-3 更新区块 ----------
    def row_update(self, master):
        """更新区块：当前版本 + 启动检查开关 + 手动「检查更新」+ 就地反馈 + 去下载。

        为什么要常驻在设置页：启动时那一次 tip 是瞬时的（2.5s 后标题栏复原），
        用户当时没看到就找不回了。这里把结果**常驻**显示，随时能找回入口。
        反馈就地显示，绝不用模态对话框打断（用户拍板要求）。
        """
        r0 = tk.Frame(master, bg=T['bg'])
        r0.pack(fill='x', pady=(8, 3))
        tk.Label(r0, text='当前版本', bg=T['bg'], fg=T['fg'], font=FONT_B,
                 anchor='w').pack(side='left')
        tk.Label(r0, text='v%s' % APP_VER, bg=T['bg'], fg=T['fg2'],
                 font=FONT).pack(side='right')

        self.row_switch(master, '启动时检查更新（每小时最多一次）', 'update_check')

        r = tk.Frame(master, bg=T['bg'])
        r.pack(fill='x', pady=3)
        self._upd_status = tk.Label(r, text='', bg=T['bg'], fg=T['fg2'], font=FONT_SM,
                                    anchor='w', justify='left')
        self._upd_status.pack(side='left', fill='x', expand=True)
        # 检查按钮（先 pack 到最右 → 它永远在最右），发现新版时才在它左侧露出「去下载」
        self._upd_btn = tk.Label(r, text=' 检查更新 ', bg=T['card'], fg=T['fg'],
                                 font=FONT_SM, cursor='hand2', padx=6, pady=2)
        self._upd_btn.pack(side='right')
        self._upd_btn.bind('<Button-1>', lambda e: self.do_update_check())
        self._upd_dl = tk.Label(r, text=' 去下载 ', bg=T['acc'], fg='#fff',
                                font=FONT_SM, cursor='hand2', padx=6, pady=2)
        self._upd_dl.bind('<Button-1>', lambda e: self.app.open_releases())
        self._upd_checking = False
        self.paint_update()

    def paint_update(self):
        """按当前状态刷新就地反馈（正在检查 / 已是最新 / 发现新版 + 去下载）。"""
        w = getattr(self, '_upd_status', None)
        if w is None:
            return
        try:
            if not w.winfo_exists():
                return
            if self._upd_checking:
                w.configure(text='正在检查…', fg=T['fg2'])
            elif update.LATEST_NEW and update.LATEST:
                w.configure(text='发现新版本 %s' % update.LATEST, fg=T['acc'])
            elif update.LATEST:
                w.configure(text='已是最新版本', fg=T['fg2'])
            else:
                w.configure(text='未检查', fg=T['fg2'])
            if update.LATEST_NEW and update.LATEST:
                if not self._upd_dl.winfo_ismapped():
                    self._upd_dl.pack(side='right', padx=(0, 6))
            else:
                self._upd_dl.pack_forget()
        except tk.TclError:
            pass

    def do_update_check(self):
        """手动检查更新：后台查，结果回主线程后在本区块就地反馈。"""
        if getattr(self, '_upd_checking', False):
            return
        self._upd_checking = True
        self.paint_update()

        def done(ver, new):
            self._upd_checking = False
            try:
                if self.win.winfo_exists():
                    self.paint_update()
            except tk.TclError:
                pass

        try:
            self.app.start_update_check(manual=True, on_result=done)
        except Exception:
            self._upd_checking = False
            self.paint_update()

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
                     anchor='w', justify='left', wraplength=340).pack(fill='x')
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
        b = tk.Label(r2, text='开启后程序常驻后台，能减少“程序没运行时复制的内容被漏记”；不想改注册表？点此手动放快捷方式',
                     bg=T['bg'], fg=T['fg2'], font=FONT_SM, cursor='hand2', anchor='w', justify='left', wraplength=340)
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
