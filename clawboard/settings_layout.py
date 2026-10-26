"""Grouped settings layout; existing settings adapters still own each action."""
import ctypes
import math
import tkinter as tk

from clawboard.config import DATA_FILE, FONT, FONT_B, FONT_SM
from clawboard.theme import T
from clawboard.widgets import ScrollFrame


SECTIONS = (
    ('general', '通用', '日常复制与窗口行为'),
    ('appearance', '外观', '让内容清楚，保留你熟悉的操作'),
    ('keys', '快捷键', '快速唤起与常用语展开'),
    ('privacy', '隐私', '选择哪些内容可以记录和显示'),
    ('data', '数据', '容量、导出与数据位置'),
)

# Keep this explicit so moving a control cannot silently drop a setting.
SECTION_SETTINGS = {
    'general': ('listen', 'autopaste', 'trim_paste', 'edge_hide', 'close_action',
                'collapse_to_corner', 'show_toast', 'sound_copy', 'sound_paste', 'update_check'),
    'appearance': ('theme', 'bg_color', 'ui_scale', 'show_time', 'show_source',
                   'show_size', 'rounded', 'frosted', 'show_preview'),
    'keys': ('hotkey', 'trigger_enabled'),
    'privacy': ('mask_sensitive', 'skip_sensitive', 'record_title', 'min_len',
                'max_len', 'smart_private', 'ignore_apps', 'ignore_titles'),
    'data': ('max_items', 'keep_on_clear'),
}


class SettingsLayout:
    """One navigation column and one scrollable page, with fixed footer."""

    def __init__(self, dialog):
        self.dialog = dialog
        self.win = dialog.win
        self.pages, self.navigation = {}, {}
        self.footer = tk.Frame(self.win, bg=T['bg'])
        self.footer.pack(side='bottom', fill='x', padx=self.dialog.scaled(16), pady=self.dialog.scaled(12))
        self.close_button = dialog.button(self.footer, dialog.save_and_close,
                                         text='关闭', bg=T['acc'],
                                         fg=T.get('on_acc', '#fff'), padx=16, pady=5)
        self.close_button.pack(side='right')
        self.quit_button = dialog.button(self.footer, dialog.save_and_quit,
                                        text='退出程序', fg=T['danger'], padx=8, pady=5)
        self.quit_button.pack(side='left')
        tk.Label(self.footer, text='设置自动保存', bg=T['bg'], fg=T['fg2'],
                 font=self.dialog.font(FONT_SM)).pack(side='left', padx=self.dialog.scaled(12))

        self.shell = tk.Frame(self.win, bg=T['bg'])
        self.shell.pack(fill='both', expand=True, padx=self.dialog.scaled(12), pady=(self.dialog.scaled(12), 0))
        self.nav = tk.Frame(self.shell, bg=T['panel'])
        self.nav.pack(side='left', fill='y', padx=(0, self.dialog.scaled(14)))
        self.content = tk.Frame(self.shell, bg=T['bg'])
        self.content.pack(side='left', fill='both', expand=True)
        self.heading = tk.Label(self.content, bg=T['bg'], fg=T['fg'], font=self.dialog.font(FONT_B), anchor='w')
        self.heading.pack(fill='x', pady=(0, self.dialog.scaled(5)))
        self.description = tk.Label(self.content, bg=T['bg'], fg=T['fg2'], font=self.dialog.font(FONT_SM),
                                    anchor='w', justify='left', wraplength=300)
        self.description.pack(fill='x', pady=(0, self.dialog.scaled(10)))
        self.description.bind('<Configure>', lambda e: self.description.configure(wraplength=max(80, e.width)))
        self.stack = tk.Frame(self.content, bg=T['bg'])
        self.stack.pack(fill='both', expand=True)
        self.stack.rowconfigure(0, weight=1)
        self.stack.columnconfigure(0, weight=1)
        for key, name, _ in SECTIONS:
            button = dialog.button(self.nav, lambda k=key: self.select(k), text=name,
                                   anchor='w', width=8, padx=self.dialog.scaled(10), pady=self.dialog.scaled(9),
                                   bg=T['panel'])
            button.pack(fill='x', padx=self.dialog.scaled(5), pady=self.dialog.scaled(3))
            self.navigation[key] = button
            page = ScrollFrame(self.stack)
            page.grid(row=0, column=0, sticky='nsew')
            self.pages[key] = page
        self._build_pages()
        for page in self.pages.values():
            page.bind_wheel_tree()
            self._bind_focus_reveal(page.inner)
        self.select('general')
        self._bind_header_drag()
        self._make_grip()
        self.fit_window()

    def _build_pages(self):
        d, app = self.dialog, self.dialog.app
        body = self.pages['general'].inner
        d.row_switch(body, '监听剪贴板', 'listen')
        d.row_switch(body, '单击后自动粘贴到上一窗口', 'autopaste')
        d.row_switch(body, '粘贴时去掉首尾空白', 'trim_paste')
        d.row_switch(body, '靠边自动隐藏', 'edge_hide')
        d.row_close_action(body)
        d.row_switch(body, '折叠时贴到屏幕右下角', 'collapse_to_corner')
        d.row_switch(body, '复制后显示内容提示', 'show_toast')
        d.row_switch(body, '记录新内容时播放复制音', 'sound_copy')
        d.row_switch(body, '成功粘贴后播放提示音', 'sound_paste')
        d.row_autostart_switch(body)
        d.row_update(body)

        body = self.pages['appearance'].inner
        d.row_theme(body)
        d.row_bgcolor(body)
        d.row_ui_scale(body)
        d.row_switch(body, '列表中显示时间', 'show_time', after=app.render)
        d.row_switch(body, '列表中显示来源', 'show_source', after=app.render)
        d.row_switch(body, '列表中显示大小（字节数 / 图片尺寸）', 'show_size', after=app.render)
        d.row_switch(body, '窗口圆角', 'rounded', after=app.apply_effects)
        d.row_switch(body, '毛玻璃背景', 'frosted', after=app.apply_effects)
        d.row_switch(body, '键盘浏览时预览完整内容', 'show_preview')

        body = self.pages['keys'].inner
        d.row_hotkey(body)
        d.row_switch(body, '触发词快速粘贴', 'trigger_enabled', after=app.apply_trigger_setting)
        self.note(body, '在常用语里设置触发词，例如 dz → 地址。仅独立标准 US 键盘布局展开；中文输入法仍可正常复制和粘贴。')
        self.note(body, '面板内：Ctrl+F 搜索；↑ / ↓ 选择；Enter 粘贴；Ctrl+Shift+Enter 纯文本粘贴；Esc 隐藏。')

        body = self.pages['privacy'].inner
        d.row_switch(body, '敏感内容打码显示', 'mask_sensitive', after=app.render)
        d.row_switch(body, '敏感内容不入库', 'skip_sensitive')
        d.row_switch(body, '记录来源窗口标题', 'record_title')
        d.row_int(body, '捕获长度下限（0=不限）', 'min_len', lo=0, hi=1000)
        d.row_int(body, '捕获长度上限（0=不限）', 'max_len', lo=0, hi=200000, width=9)
        d.row_switch(body, '遵守“别记录我”剪贴板标记', 'smart_private')
        d.row_text(body, '忽略这些程序（逗号分隔，支持 * ?）', 'ignore_apps',
                   '例：keepass, *bitwarden*。启动补记无法确认原来源，请同时使用密码管理器的私密标记。')
        d.row_text(body, '忽略标题匹配的窗口（正则，分号分隔）', 'ignore_titles',
                   '例：密码; Password; ^私密')
        self.note(body, '显示打码不等于磁盘加密。历史 JSON 和图片仍存放在本机数据目录。')

        body = self.pages['data'].inner
        d.row_int(body, '历史最大条数（10–5000）', 'max_items')
        d.row_switch(body, '清空历史时保留收藏项', 'keep_on_clear')
        self.note(body, '当前数据文件')
        self.note(body, DATA_FILE)
        self.export_button = d.button(body, d.export_all, text='导出全部内容（JSON）',
                                      padx=10, pady=6)
        self.export_button.pack(anchor='w', pady=(self.dialog.scaled(8), self.dialog.scaled(4)))
        self.note(body, '导出包含历史和常用语的记录字段，不包含设置、图片本体或所引用文件的正文。当前没有导入或一键恢复入口。')
        danger = tk.Frame(body, bg=T['bg'], highlightthickness=1, highlightbackground=T['line'])
        danger.pack(fill='x', pady=(self.dialog.scaled(20), self.dialog.scaled(8)))
        tk.Label(danger, text='危险操作', bg=T['bg'], fg=T['danger'], font=self.dialog.font(FONT_B),
                 anchor='w').pack(fill='x', padx=self.dialog.scaled(10), pady=(self.dialog.scaled(10), self.dialog.scaled(3)))
        self.note(danger, '彻底清理会删除本机数据及备份，并关闭开机自启。该操作无法撤销。')
        self.wipe_button = d.button(danger, d.wipe_all, text='彻底清理所有数据',
                                    fg=T['danger'], padx=10, pady=6)
        self.wipe_button.pack(anchor='w', padx=self.dialog.scaled(10), pady=(self.dialog.scaled(4), self.dialog.scaled(10)))

    def note(self, master, text):
        label = tk.Label(master, text=text, bg=T['bg'], fg=T['fg2'], font=self.dialog.font(FONT_SM),
                         anchor='w', justify='left', wraplength=300)
        label.pack(fill='x', padx=self.dialog.scaled(3), pady=self.dialog.scaled(5))
        label.bind('<Configure>', lambda e: label.configure(wraplength=max(60, e.width)))
        return label

    def select(self, key):
        if key not in self.pages:
            return
        for name, page in self.pages.items():
            if name == key:
                page.grid()
            else:
                page.grid_remove()
            self.navigation[name].configure(bg=T['card_s'] if name == key else T['panel'],
                                             fg=T['acc'] if name == key else T['fg2'])
        self.dialog.section = key
        self.dialog.sc = self.pages[key]
        _, title, description = next(row for row in SECTIONS if row[0] == key)
        self.heading.configure(text=title)
        self.description.configure(text=description)
        self.win.after_idle(self.dialog.sc._on_inner)

    def _bind_focus_reveal(self, widget):
        for child in widget.winfo_children():
            child.bind('<FocusIn>', self._reveal_focused, add='+')
            self._bind_focus_reveal(child)

    def _reveal_focused(self, event):
        canvas = self.dialog.sc.canvas
        canvas.update_idletasks()
        extent = canvas.bbox('all')
        if not extent:
            return
        top = canvas.canvasy(0)
        y = event.widget.winfo_rooty() - canvas.winfo_rooty() + top
        bottom = y + event.widget.winfo_height()
        height = canvas.winfo_height()
        desired = top
        if y < top:
            desired = y - self.dialog.scaled(8)
        elif bottom > top + height:
            desired = bottom - height + self.dialog.scaled(8)
        if desired != top:
            # ScrollFrame uses whole 24px units. Round toward visibility rather
            # than let a small positive request round back to the old position.
            step = max(1, int(canvas.cget('yscrollincrement')))
            desired = (math.floor(desired / step) if desired < top else math.ceil(desired / step)) * step
            canvas.yview_moveto(max(0, desired) / max(1, extent[3]))

    def _bind_header_drag(self):
        def start(event):
            self._drag = (event.x_root - self.win.winfo_x(), event.y_root - self.win.winfo_y())

        def move(event):
            if hasattr(self, '_drag'):
                x, y = event.x_root - self._drag[0], event.y_root - self._drag[1]
                self.win.geometry('%+d%+d' % (x, y))

        for widget in (self.dialog.bar, *self.dialog.bar.winfo_children()):
            widget.bind('<ButtonPress-1>', start)
            widget.bind('<B1-Motion>', move)

    def _make_grip(self):
        grip = tk.Label(self.win, text='⌟', bg=T['bg'], fg=T['fg2'], font=self.dialog.font(FONT_SM), cursor='sizing')
        grip.place(relx=1, rely=1, x=-2, y=-2, anchor='se')

        def start(event):
            self._resize = (event.x_root, event.y_root, self.win.winfo_width(), self.win.winfo_height())

        def resize(event):
            if hasattr(self, '_resize'):
                x, y, width, height = self._resize
                minimum_w, minimum_h = self.win.minsize()
                self.win.geometry('%dx%d' % (max(minimum_w, width + event.x_root - x),
                                            max(minimum_h, height + event.y_root - y)))
        grip.bind('<ButtonPress-1>', start)
        grip.bind('<B1-Motion>', resize)

    def fit_window(self, initial=True, ratio=1.0):
        self.win.update_idletasks()
        parent = self.dialog.app.root
        px, py, pw, ph = parent.winfo_rootx(), parent.winfo_rooty(), parent.winfo_width(), parent.winfo_height()
        area = (0, 0, parent.winfo_screenwidth(), parent.winfo_screenheight())
        try:
            from clawboard.windows_api import u32, MONITORINFO, MONITOR_DEFAULTTONEAREST
            from clawboard.windows_geometry import top_hwnd
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(info)
            monitor = u32.MonitorFromWindow(top_hwnd(parent if initial else self.win), MONITOR_DEFAULTTONEAREST)
            if u32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                r = info.rcWork
                area = (r.left, r.top, r.right, r.bottom)
        except (ImportError, AttributeError, OSError):
            pass
        left, top, right, bottom = area
        margin = self.dialog.scaled(8)
        aw, ah = max(1, right - left - margin * 2), max(1, bottom - top - margin * 2)
        width = min(aw, max(self.dialog.scaled(620), self.nav.winfo_reqwidth() + self.dialog.scaled(270), self.footer.winfo_reqwidth() + self.dialog.scaled(40)))
        height = min(ah, max(self.dialog.scaled(540), self.nav.winfo_reqheight() + self.footer.winfo_reqheight() + self.dialog.scaled(90)))
        x = max(left + margin, min(px + (pw - width) // 2, right - width - margin))
        y = max(top + margin, min(py + (ph - height) // 2, bottom - height - margin))
        if not initial:
            width = min(aw, max(1, round(self.win.winfo_width() * ratio)))
            height = min(ah, max(1, round(self.win.winfo_height() * ratio)))
            x = max(left + margin, min(self.win.winfo_x(), right - width - margin))
            y = max(top + margin, min(self.win.winfo_y(), bottom - height - margin))
        self.win.minsize(1, 1)
        self.win.geometry('%dx%d%+d%+d' % (width, height, x, y))
        self.win.minsize(min(width, max(self.dialog.scaled(440), self.nav.winfo_reqwidth() + self.dialog.scaled(220),
                                      self.footer.winfo_reqwidth() + self.dialog.scaled(40))),
                         min(height, max(self.dialog.scaled(350), self.nav.winfo_reqheight() + self.footer.winfo_reqheight() + self.dialog.scaled(50))))
