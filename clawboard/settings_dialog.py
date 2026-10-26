"""Tk settings adapter; persistence/export work is delegated to services."""
import os
import subprocess
import time
import tkinter as tk
import tkinter.font as tkfont
from copy import deepcopy
from threading import Event
from clawboard import config, runtime, update
from clawboard.config import (APP_NAME, APP_VER, BASE_DIR, DATA_FILE, DEFAULT_SETTINGS,
                              FONT, FONT_B, FONT_SM, UI_SCALE_LEVELS)
from clawboard.theme import T, set_theme
from clawboard.win32 import get_autostart, set_autostart
from clawboard.widgets import dark_top, safe_release
from clawboard.exports import write_payload, new_export_path
from clawboard.settings_layout import SettingsLayout


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
        self._scale = self._window_scale(app.root)
        self._fonts = {}
        self._scale_job = None
        dark_top(self.win, '设置')
        self.win.attributes('-topmost', True)
        self.win.protocol('WM_DELETE_WINDOW', self.close)
        self.win.bind('<Destroy>', self._destroyed, add='+')
        self.win.after(60, lambda: (self.win.lift(), self.win.focus_force()))
        self.bar = self.win.winfo_children()[0]
        self.bar.configure(height=self.scaled(36))
        self.bar.winfo_children()[0].configure(font=self.font(FONT_B))
        self._input_commits = []
        self._switches = {}
        self.layout = SettingsLayout(self)
        self._metrics = self._remember_metrics(self.win)
        self.win.bind('<Configure>', self._configured, add='+')
        self._scale_binding = app.root.bind(
            '<<ClawBoardUIScaleChanged>>', lambda _: self._configured(), add='+')
        self.win.bind('<Escape>', lambda e: self.close())
        self._configured()

    def scaled(self, value):
        return max(1, round(value * self._scale))

    def font(self, template):
        key = tuple(template)
        if key not in self._fonts:
            # A Toplevel shares Tk scaling with its parent. Local pixel fonts
            # let settings follow its own monitor without resizing the panel.
            self._fonts[key] = tkfont.Font(self.win, font=(
                key[0], -self.scaled(abs(key[1]) * 96 / 72), *key[2:]))
            self._fonts[key].configure(size=-self.scaled(abs(key[1]) * 96 / 72))
        return self._fonts[key]

    def _window_scale(self, window=None):
        try:
            from clawboard.windows_system import dpi_scale
            return dpi_scale(window or self.win) * config.UI_SCALE
        except (ImportError, AttributeError, tk.TclError):
            return config.DPI_SCALE * config.UI_SCALE

    def _remember_metrics(self, parent):
        metrics = []
        for widget in parent.winfo_children():
            options = {}
            for key in ('padx', 'pady', 'borderwidth', 'highlightthickness',
                        'insertwidth', 'selectborderwidth', 'yscrollincrement'):
                if key in widget.keys():
                    options[key] = float(widget.cget(key)) / self._scale
            if isinstance(widget, (tk.Frame, tk.Canvas, tk.Scrollbar)):
                for key in ('width', 'height'):
                    if key in widget.keys():
                        options[key] = float(widget.cget(key)) / self._scale
            manager = widget.winfo_manager()
            spacing = {}
            if manager in ('pack', 'grid'):
                info = getattr(widget, manager + '_info')()
                for key in ('padx', 'pady', 'ipadx', 'ipady'):
                    if key in info:
                        values = info[key] if isinstance(info[key], (tuple, list)) else self.win.tk.splitlist(str(info[key]))
                        spacing[key] = tuple(float(value) / self._scale
                                             for value in values)
            metrics.append((widget, options, manager, spacing))
            metrics.extend(self._remember_metrics(widget))
        return metrics

    def _configured(self, event=None):
        if self._closed or (event is not None and event.widget is not self.win):
            return
        if self._scale_job:
            self.win.after_cancel(self._scale_job)
        self._scale_job = self.win.after(120, self._sync_scale)

    def _sync_scale(self):
        self._scale_job = None
        if self._closed:
            return
        if os.name == 'nt':
            from clawboard.windows_api import u32
            if u32.GetAsyncKeyState(1) & 0x8000:
                self._configured()
                return
        new_scale = self._window_scale()
        if abs(new_scale - self._scale) < .001:
            return
        ratio, self._scale = new_scale / self._scale, new_scale
        scroll = {key: page.canvas.yview()[0] for key, page in self.layout.pages.items()}
        # Keep controls alive: rebuilding would fire FocusOut and commit an
        # unfinished input merely because the user dragged the window.
        for template, font in self._fonts.items():
            font.configure(size=-self.scaled(abs(template[1]) * 96 / 72))
        for widget, options, manager, spacing in self._metrics:
            widget.configure(**{key: round(value * new_scale) for key, value in options.items()})
            if spacing:
                getattr(widget, manager + '_configure')(**{
                    key: tuple(round(value * new_scale) for value in values)
                    for key, values in spacing.items()})
        self.layout.fit_window(initial=False, ratio=ratio)
        self.win.update_idletasks()
        for key, page in self.layout.pages.items():
            page._on_inner()
            page.canvas.yview_moveto(scroll[key])

    def select_section(self, key):
        self.layout.select(key)

    def button(self, master, command, **kwargs):
        options = dict(bg=T['card'], fg=T['fg'], activebackground=T['card_h'],
                       activeforeground=T['fg'], font=self.font(FONT), relief='flat', bd=0,
                       highlightthickness=1, highlightbackground=T['line'],
                       highlightcolor=T['acc'], takefocus=True, cursor='hand2')
        options.update(kwargs)
        button = tk.Button(master, command=command, **options)
        button.bind('<Return>', lambda e: (button.invoke(), 'break')[1])
        return button

    def row_label(self, master, text):
        label = tk.Label(master, text=text, bg=T['bg'], fg=T['fg'], font=self.font(FONT),
                         anchor='w', justify='left', wraplength=260)
        label.pack(side='left', fill='x', expand=True, padx=(0, 8))
        label.bind('<Configure>', lambda e: label.configure(wraplength=max(60, e.width)))
        return label

    def _commit_inputs(self):
        for widget, commit in getattr(self, '_input_commits', ()):
            if widget.winfo_exists():
                commit()

    def save_and_close(self):
        self._commit_inputs()
        self.app.save(True)
        self.close()

    def save_and_quit(self):
        self._commit_inputs()
        self.app.save(True)
        self.close()
        self.app.quit_app()

    def _alive(self):
        if getattr(self, '_closed', False):
            return False
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def _destroyed(self, event):
        if event.widget is self.win:
            self._cancel_scale_job()
            self._closed = True
            self._export_cancel.set()
            self.app.application.tasks.invalidate(self._export_key)

    def close(self):
        if getattr(self, '_closed', False):
            return
        self._closed = True
        self._cancel_scale_job()
        self._export_cancel.set()
        self.app.application.tasks.invalidate(self._export_key)
        self._commit_inputs()
        safe_release(self.win)
        self.win.destroy()

    def _cancel_scale_job(self):
        job = getattr(self, '_scale_job', None)
        self._scale_job = None
        if job:
            try:
                self.win.after_cancel(job)
            except tk.TclError:
                pass
        binding = getattr(self, '_scale_binding', None)
        self._scale_binding = None
        if binding:
            try:
                self.app.root.unbind('<<ClawBoardUIScaleChanged>>', binding)
            except tk.TclError:
                pass

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
        r = tk.Frame(master, bg=T['bg'])
        r.pack(fill='x', pady=5)

        def paint():
            value = float(self.app.st.get('ui_scale') or 1.0)
            lb.configure(text='%d%%' % int(value * 100))

        def setv():
            levels = list(UI_SCALE_LEVELS)
            current = float(self.app.st.get('ui_scale') or 1.0)
            index = levels.index(current) if current in levels else levels.index(1.0)
            self.app.set_ui_scale(levels[(index + 1) % len(levels)])
            self._configured()
            paint()

        lb = self.button(r, setv, text='', padx=8, pady=4, font=self.font(FONT_SM))
        lb.pack(side='right')
        self.row_label(r, '界面缩放（Ctrl+= / Ctrl+-）')
        paint()

    def row_close_action(self, master):
        r = tk.Frame(master, bg=T['bg'])
        r.pack(fill='x', pady=5)

        def paint():
            value = self.app.st.get('close_action', 'hide')
            lb.configure(text='隐藏到托盘' if value == 'hide' else '直接退出程序')

        def setv(value):
            self.app.st['close_action'] = value
            self.app.save(True)
            paint()
            self.app.tip('关闭按钮现在会%s' % ('隐藏到托盘' if value == 'hide' else '直接退出'))

        def menu():
            m = tk.Menu(self.win, tearoff=0, bg=T['panel'], fg=T['fg'], bd=0,
                        activebackground=T['card_h'], activeforeground=T['fg'], font=self.font(FONT), relief='flat')
            m.add_command(label='隐藏到托盘（继续后台监听）', command=lambda: setv('hide'))
            m.add_command(label='直接退出程序', command=lambda: setv('quit'))
            m.tk_popup(lb.winfo_rootx(), lb.winfo_rooty() + lb.winfo_height())

        lb = self.button(r, menu, text='', padx=8, pady=4, font=self.font(FONT_SM))
        lb.pack(side='right')
        self.row_label(r, '点标题栏关闭按钮时')
        paint()

    def row_switch(self, master, text, key, after=None):
        r = tk.Frame(master, bg=T['bg'])
        r.pack(fill='x', pady=5)
        st = self.app.st

        def paint():
            on = bool(st.get(key))
            lb.configure(text='开' if on else '关',
                         fg=T.get('on_acc', '#fff') if on else T['fg2'],
                         bg=T['acc'] if on else T['card'])

        def toggle():
            if key == 'listen':
                # The system adapter owns capture invalidation and catch-up.
                self.app.toggle_listen()
                paint()
                return
            st[key] = not st.get(key)
            paint()
            self.app.save(True)
            if after:
                after()

        lb = self.button(r, toggle, text='', font=self.font(FONT_B), width=5, pady=3)
        lb.pack(side='right')
        self.row_label(r, text)
        if not hasattr(self, '_switches'):
            self._switches = {}
        self._switches[key] = lb
        paint()
        return lb

    # ---------- P1-3 更新区块 ----------
    def row_update(self, master):
        """更新区块：当前版本 + 启动检查开关 + 手动「检查更新」+ 就地反馈 + 去下载。

        为什么要常驻在设置页：启动时那一次 tip 是瞬时的（2.5s 后标题栏复原），
        用户当时没看到就找不回了。这里把结果**常驻**显示，随时能找回入口。
        反馈就地显示，绝不用模态对话框打断（用户拍板要求）。
        """
        r0 = tk.Frame(master, bg=T['bg'])
        r0.pack(fill='x', pady=(8, 3))
        tk.Label(r0, text='当前版本', bg=T['bg'], fg=T['fg'], font=self.font(FONT_B),
                 anchor='w').pack(side='left')
        tk.Label(r0, text='v%s' % APP_VER, bg=T['bg'], fg=T['fg2'],
                 font=self.font(FONT)).pack(side='right')

        self.row_switch(master, '启动时检查更新（每小时最多一次）', 'update_check')

        r = tk.Frame(master, bg=T['bg'])
        r.pack(fill='x', pady=3)
        self._upd_status = tk.Label(r, text='', bg=T['bg'], fg=T['fg2'], font=self.font(FONT_SM),
                                    anchor='w', justify='left')
        # 检查按钮（先 pack 到最右 → 它永远在最右），发现新版时才在它左侧露出「去下载」
        self._upd_btn = self.button(r, self.do_update_check, text='检查更新',
                                   font=self.font(FONT_SM), padx=6, pady=4)
        self._upd_btn.pack(side='right')
        self._upd_dl = self.button(r, self.app.open_releases, text='去下载',
                                  bg=T['acc'], fg=T.get('on_acc', '#fff'),
                                  font=self.font(FONT_SM), padx=6, pady=4)
        self._upd_status.pack(side='left', fill='x', expand=True)
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
        r.pack(fill='x', pady=5)
        for name, label in (('dark', '暗色'), ('light', '亮色')):
            lb = self.button(r, lambda n=name: self.set_theme(n), text=label,
                             bg=T['card_s'] if self.app.st.get('theme') == name else T['card'],
                             padx=8, pady=4)
            lb.pack(side='right', padx=2)
        self.row_label(r, '主题')

    def set_theme(self, name):
        self.app.st['theme'] = name
        self.app.save(True)
        set_theme(name)
        self.app.rebuild()
        safe_release(self.win)
        self.win.destroy()

    def row_hotkey(self, master):
        r = tk.Frame(master, bg=T['bg'])
        r.pack(fill='x', pady=5)
        current = [label for label, value in self.HKS if value == self.app.st.get('hotkey')]
        lb = self.button(r, lambda: self.hk_menu(lb), text=current[0] if current else '未设置',
                         font=self.font(FONT_SM), padx=8, pady=4)
        lb.pack(side='right')
        self.row_label(r, '全局唤起热键')

    def hk_menu(self, anchor):
        m = tk.Menu(self.win, tearoff=0, bg=T['panel'], fg=T['fg'], bd=0,
                    activebackground=T['card_h'], activeforeground=T['fg'],
                    font=self.font(FONT), relief='flat')
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
        r.pack(fill='x', pady=5)
        value = tk.StringVar(value=str(self.app.st.get(key)))
        entry = tk.Entry(r, textvariable=value, bg=T['card'], fg=T['fg'], insertbackground=T['fg'],
                         relief='flat', font=self.font(FONT), bd=0, width=width, justify='right',
                         highlightthickness=1, highlightbackground=T['line'], highlightcolor=T['acc'])
        entry.pack(side='right', ipady=3)
        self.row_label(r, text)

        def commit(_=None):
            try:
                number = min(hi, max(lo, int(value.get())))
            except (ValueError, TypeError):
                number = int(DEFAULT_SETTINGS[key])
            changed = self.app.st.get(key) != number
            self.app.st[key] = number
            value.set(str(number))
            if changed:
                self.app.save(True)
            return 'break'

        entry.bind('<Return>', commit)
        entry.bind('<FocusOut>', commit)
        if not hasattr(self, '_input_commits'):
            self._input_commits = []
        self._input_commits.append((entry, commit))
        if not hasattr(self, '_inputs'):
            self._inputs = {}
        self._inputs[key] = entry
        return entry

    BG_CHOICES = (('默认（跟随主题）', ''), ('墨黑', '#12141a'), ('深蓝灰', '#1e2027'),
                  ('午夜蓝', '#16202e'), ('墨绿', '#16241f'), ('深紫', '#1d1a2b'),
                  ('浅灰', '#f4f5f8'), ('米白', '#faf7f0'), ('纯白', '#ffffff'))

    def row_bgcolor(self, master):
        r = tk.Frame(master, bg=T['bg'])
        r.pack(fill='x', pady=5)

        def paint():
            current = (self.app.st.get('bg_color') or '').strip().lower()
            lb.configure(text=next((name for name, color in self.BG_CHOICES
                                    if color.lower() == current), '默认'))

        def pick(color):
            self.app.st['bg_color'] = color
            self.app.save(True)
            self.app.rebuild()
            self.app.tip('背景已更换' if color else '已恢复主题默认背景')

        def menu():
            m = tk.Menu(self.win, tearoff=0, bg=T['panel'], fg=T['fg'], bd=0,
                        activebackground=T['card_h'], activeforeground=T['fg'], font=self.font(FONT), relief='flat')
            for name, color in self.BG_CHOICES:
                m.add_command(label=name, command=lambda c=color: pick(c))
            m.tk_popup(lb.winfo_rootx(), lb.winfo_rooty() + lb.winfo_height())

        lb = self.button(r, menu, text='', width=10, font=self.font(FONT_SM), padx=6, pady=4)
        lb.pack(side='right')
        self.row_label(r, '背景色（选底色，其余自动配）')
        paint()

    def row_text(self, master, text, key, hint=''):
        r = tk.Frame(master, bg=T['bg'])
        r.pack(fill='x', pady=5)
        for content, color, font in ((text, T['fg'], FONT), (hint, T['fg2'], FONT_SM)):
            if content:
                label = tk.Label(r, text=content, bg=T['bg'], fg=color, font=self.font(font),
                                 anchor='w', justify='left', wraplength=300)
                label.pack(fill='x', pady=(0, 3))
                label.bind('<Configure>', lambda e, w=label: w.configure(wraplength=max(60, e.width)))
        value = tk.StringVar(value=str(self.app.st.get(key) or ''))
        entry = tk.Entry(r, textvariable=value, bg=T['card'], fg=T['fg'], insertbackground=T['fg'],
                         relief='flat', font=self.font(FONT_SM), bd=0, highlightthickness=1,
                         highlightbackground=T['line'], highlightcolor=T['acc'])
        entry.pack(fill='x', ipady=4, pady=(2, 0))

        def commit(_=None):
            text_value = value.get().strip()
            if self.app.st.get(key) != text_value:
                self.app.st[key] = text_value
                self.app.save(True)
            return 'break'

        entry.bind('<Return>', commit)
        entry.bind('<FocusOut>', commit)
        if not hasattr(self, '_input_commits'):
            self._input_commits = []
        self._input_commits.append((entry, commit))
        if not hasattr(self, '_inputs'):
            self._inputs = {}
        self._inputs[key] = entry
        return entry

    def row_autostart_switch(self, master):
        r = tk.Frame(master, bg=T['bg'])
        r.pack(fill='x', pady=5)

        def paint():
            on, _ = get_autostart()
            lb.configure(text='开' if on else '关', fg=T.get('on_acc', '#fff') if on else T['fg2'],
                         bg=T['acc'] if on else T['card'])

        def toggle():
            if runtime.NO_SAVE:
                self.app.tip('自测模式不改动开机自启')
                return
            on, _ = get_autostart()
            success = set_autostart(not on)
            paint()
            self.app.tip(('开机自启已开启' if not on else '开机自启已关闭')
                         if success else '开机自启设置失败（注册表不可写）')

        lb = self.button(r, toggle, text='', width=5, font=self.font(FONT_B), pady=3)
        lb.pack(side='right')
        self.row_label(r, '开机自启（当前用户）')
        paint()
        self.button(master, self.open_startup, text='打开启动快捷方式文件夹',
                    fg=T['fg2'], font=self.font(FONT_SM), padx=6, pady=4).pack(anchor='w', pady=(0, 6))

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
