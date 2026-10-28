"""Recycle-bin UI: preview first, mutate only through the application adapter."""
import ctypes
from datetime import datetime
import math
import os
import tkinter as tk
from tkinter import messagebox
import tkinter.font as tkfont

from clawboard import config, runtime
from clawboard.config import FONT, FONT_B, FONT_SM
from clawboard.privacy import display_text
from clawboard.theme import T
from clawboard.trash import TrashError
from clawboard.widgets import ScrollFrame


class TrashWindow:
    """A read-only preview never pastes or changes the selected record."""

    PREVIEW_LIMIT = 16384

    def __init__(self, app):
        self.app = app
        self._closed = self._busy = False
        self._rows, self._jobs, self._fonts = [], {}, {}
        self.win = tk.Toplevel(app.root)
        self.win.title('ClawBoard · 回收站')
        self.win.transient(app.root)
        self.win.configure(bg=T['bg'])
        self._scale = self._window_scale(app.root)
        self._build()
        self._fit(initial=True)
        self._metrics = self._remember_metrics(self.win)
        self._scale_binding = app.root.bind(
            '<<ClawBoardUIScaleChanged>>', lambda _: self._schedule('dpi', self._sync_scale), add='+')
        self.win.bind('<Configure>', self._configured, add='+')
        self.win.bind('<Destroy>', self._destroyed, add='+')
        self.win.bind('<Escape>', lambda _: self.close())
        self.win.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh()
        if not runtime.NO_SAVE:
            self.expire()
        self._schedule('dpi', self._sync_scale)

    def _px(self, value):
        return max(1, round(value * self._scale))

    def _font(self, template):
        key = tuple(template)
        if key not in self._fonts:
            font = tkfont.Font(self.win, font=template)
            font.configure(size=-self._px(abs(template[1]) * 96 / 72))
            self._fonts[key] = font
        return self._fonts[key]

    def _button(self, parent, text, command, primary=False):
        button = tk.Button(parent, text=text, command=command, font=self._font(FONT),
            bg=T['acc'] if primary else T['card'],
            fg=T.get('on_acc', '#fff') if primary else T['fg'],
            activebackground=T['card_h'], activeforeground=T['fg'], relief='flat', bd=0,
            highlightthickness=1, highlightbackground=T['line'], highlightcolor=T['acc'],
            padx=self._px(10), pady=self._px(6), takefocus=True)
        button.bind('<Return>', lambda _: (button.invoke(), 'break')[1])
        return button

    def _label(self, parent, text='', bold=False):
        label = tk.Label(parent, text=text, bg=T['bg'], fg=T['fg'] if bold else T['fg2'],
            font=self._font(FONT_B if bold else FONT_SM), anchor='w', justify='left',
            wraplength=self._px(400))
        label.pack(fill='x', pady=self._px(4))
        label.bind('<Configure>', lambda e: label.configure(wraplength=max(1, e.width)))
        return label

    def _build(self):
        footer = tk.Frame(self.win, bg=T['bg'])
        footer.pack(side='top', fill='x', padx=self._px(14), pady=self._px(10))
        self.status = self._label(footer, '选择一条内容后可预览或恢复。')
        actions = tk.Frame(footer, bg=T['bg'])
        actions.pack(fill='x')
        self.close_button = self._button(actions, '关闭', self.close)
        self.close_button.pack(side='right')
        self.restore_button = self._button(actions, '恢复所选', self.restore_selected, primary=True)
        self.restore_button.pack(side='left')
        danger = tk.Frame(footer, bg=T['bg'])
        danger.pack(fill='x', pady=(self._px(6), 0))
        self.purge_button = self._button(danger, '永久删除所选…', self.purge_selected)
        self.purge_button.pack(side='left')
        self.clear_button = self._button(danger, '清空回收站…', self.purge_all)
        self.clear_button.pack(side='right')
        self.body = ScrollFrame(self.win)
        self.body.canvas.configure(width=1, height=1)
        self.body.pack(fill='both', expand=True, padx=self._px(16), pady=self._px(10))
        content = self.body.inner
        self._label(content, '误删回收站', bold=True)
        self._label(content, '删除内容最多保留30天，到期在下次维护时清理。最多5000条，满时拒绝新的移入，不提前清除未到期内容。')
        self._label(content, '恢复到原历史或常用语分组；原分组不存在时会重新建立。回收站仍是本机明文数据。')
        toolbar = tk.Frame(content, bg=T['bg'])
        toolbar.pack(fill='x', pady=self._px(5))
        self.refresh_button = self._button(toolbar, '刷新', self.refresh)
        self.refresh_button.pack(side='right')
        self.count = self._label(toolbar)
        self.count.pack_configure(side='left', expand=True)
        list_frame = tk.Frame(content, bg=T['bg'])
        list_frame.pack(fill='x', pady=self._px(5))
        self.listbox = tk.Listbox(list_frame, width=1, height=7, font=self._font(FONT),
            bg=T['card'], fg=T['fg'], selectbackground=T['acc'],
            selectforeground=T.get('on_acc', '#fff'), relief='flat', bd=0,
            highlightthickness=1, highlightcolor=T['acc'], highlightbackground=T['line'],
            exportselection=False, selectmode='extended', activestyle='dotbox')
        scrollbar = tk.Scrollbar(list_frame, orient='vertical', command=self.listbox.yview)
        scrollbar.pack(side='right', fill='y')
        self.listbox.pack(fill='x', expand=True)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.bind('<<ListboxSelect>>', self._selection_changed)
        # Enter and double-click reveal only; neither invokes restore nor paste.
        self.listbox.bind('<Return>', self._focus_preview)
        self.listbox.bind('<Double-Button-1>', self._focus_preview)
        self._label(content, '所选内容预览', bold=True)
        preview_frame = tk.Frame(content, bg=T['bg'])
        preview_frame.pack(fill='x', pady=self._px(5))
        self.preview = tk.Text(preview_frame, width=1, height=8, wrap='word',
            font=self._font(FONT), bg=T['card'], fg=T['fg'], relief='flat', bd=0,
            highlightthickness=1, highlightcolor=T['acc'], highlightbackground=T['line'],
            state='disabled', takefocus=True)
        preview_scroll = tk.Scrollbar(preview_frame, orient='vertical', command=self.preview.yview)
        preview_scroll.pack(side='right', fill='y')
        self.preview.pack(fill='x', expand=True)
        self.preview.configure(yscrollcommand=preview_scroll.set)
        self._label(content, '永久删除无法撤销；另存的完整备份包仍会保留。')
        self.body.bind_wheel_tree()
        self._bind_focus_reveal(content)

    def _alive(self):
        if self._closed:
            return False
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def _status(self, text, error=False):
        if self._alive():
            self.status.configure(text=text, fg=T['danger'] if error else T['fg2'])

    def _guard(self):
        if not self._alive() or self._busy:
            return False
        if runtime.NO_SAVE:
            self._status('自测模式，不改动资料')
            return False
        return True

    def _selection_ids(self):
        return [self._rows[int(index)]['id'] for index in self.listbox.curselection()
                if 0 <= int(index) < len(self._rows)]

    def _display_body(self, item, limit):
        raw = item.get('text')
        raw = raw if isinstance(raw, str) else ''
        # A bounded look-ahead lets masking finish tokens crossing the preview
        # boundary, without processing every long record while listing 5000 rows.
        visible = display_text(raw[:limit + 512], item.get('sens') or None,
            masked=bool(self.app.st.get('mask_sensitive', True)), reveal=bool(item.get('mask_off')))
        return visible[:limit], len(raw) > limit

    def _position(self, entry):
        group = entry.get('group')
        if group is None:
            return '剪贴板历史'
        name = group.get('name', '') if isinstance(group, dict) else ''
        name = display_text(str(name)[:256], masked=bool(self.app.st.get('mask_sensitive', True)))
        return '常用语 · ' + (name[:80] or '原分组')

    @staticmethod
    def _when(value):
        try:
            return datetime.fromtimestamp(float(value) / 1000.0).strftime('%Y-%m-%d %H:%M')
        except (TypeError, ValueError, OverflowError, OSError):
            return '时间未知'

    def refresh(self):
        if not self._alive():
            return
        selected = set(self._selection_ids())
        try:
            rows = self.app.application.trash.entries()
        except TrashError as error:
            self._status(str(error), error=True)
            return
        except (OSError, ValueError):
            self._status('无法读取回收站，请检查资料保存状态后重试。', error=True)
            return
        self._rows = list(rows)
        self.listbox.delete(0, 'end')
        for index, entry in enumerate(self._rows):
            text, truncated = self._display_body(entry.get('item') or {}, 120)
            text = text.replace('\r', ' ').replace('\n', '  ') or '（空内容）'
            label = '%s  ·  %s  —  %s%s' % (self._when(entry.get('deleted_at')),
                self._position(entry), text, '…' if truncated else '')
            self.listbox.insert('end', label)
            if entry['id'] in selected:
                self.listbox.selection_set(index)
        if self._rows and not self.listbox.curselection():
            self.listbox.selection_set(0)
        self.count.configure(text='回收站：%d 条' % len(self._rows))
        self._selection_changed()

    def _write_preview(self, text):
        self.preview.configure(state='normal')
        self.preview.delete('1.0', 'end')
        self.preview.insert('1.0', text)
        self.preview.configure(state='disabled')

    def _selection_changed(self, _event=None):
        ids = self._selection_ids()
        entry = next((row for row in self._rows if row['id'] in ids), None)
        if entry is None:
            self._write_preview('回收站为空。日常删除后的内容会出现在这里。')
        else:
            item = entry.get('item') or {}
            text, truncated = self._display_body(item, self.PREVIEW_LIMIT)
            prefix = '删除于：%s\n原位置：%s\n\n' % (
                self._when(entry.get('deleted_at')), self._position(entry))
            suffix = '\n\n（仅显示前%d个字符；恢复会保留完整内容）' % self.PREVIEW_LIMIT if truncated else ''
            if item.get('content_type') == 'image':
                suffix += '\n\n图片恢复后可在主面板查看。'
            self._write_preview(prefix + text + suffix)
        self._paint_actions()

    def _paint_actions(self):
        selected = bool(self._selection_ids()) and not self._busy
        for button in (self.restore_button, self.purge_button):
            button.configure(state='normal' if selected else 'disabled')
        self.clear_button.configure(state='normal' if self._rows and not self._busy else 'disabled')

    def _focus_preview(self, _event=None):
        self._selection_changed()
        self.preview.focus_set()
        return 'break'

    def _perform(self, operation, success, *, empty=None):
        if not self._guard():
            return
        self._busy = True
        self._paint_actions()
        try:
            result = operation()
        except TrashError as error:
            self._status(str(error), error=True)
        except (OSError, ValueError):
            self._status('操作未能完成，请检查资料保存状态或刷新后重试。', error=True)
        else:
            self.refresh()
            if empty and isinstance(result, list) and not result:
                self._status(empty, error=True)
            else:
                self._status(success)
        finally:
            self._busy = False
            if self._alive():
                self._paint_actions()

    def restore_selected(self):
        if not self._guard():
            return
        ids = self._selection_ids()
        if ids:
            self._perform(lambda: self.app.recycle_restore(ids), '已恢复所选内容。',
                          empty='所选内容已改变，请刷新后重新选择。')

    def purge_selected(self):
        if not self._guard():
            return
        ids = self._selection_ids()
        if ids and messagebox.askyesno('永久删除', '永久删除所选的%d条内容？此操作不可撤销。' % len(ids),
                                      parent=self.win, default='no'):
            self._perform(lambda: self.app.recycle_purge(ids), '已永久删除所选内容。')

    def purge_all(self):
        if not self._guard():
            return
        # Freeze the reviewed IDs; a nested confirmation must not erase newly
        # deleted content that appeared after the user saw this list.
        ids = [entry['id'] for entry in self._rows]
        if ids and messagebox.askyesno('清空回收站', '永久删除回收站当前的%d条内容？此操作不可撤销。' % len(ids),
                                      parent=self.win, default='no'):
            self._perform(lambda: self.app.recycle_purge(ids), '已清空本次确认的回收站内容。')

    def expire(self):
        self._perform(self.app.recycle_expire, '已检查保留期限。')

    def _bind_focus_reveal(self, parent):
        for widget in parent.winfo_children():
            widget.bind('<FocusIn>', self._reveal_focused, add='+')
            self._bind_focus_reveal(widget)

    def _reveal_focused(self, event):
        canvas = self.body.canvas
        canvas.update_idletasks()
        extent = canvas.bbox('all')
        if not extent:
            return
        top = canvas.canvasy(0)
        y = event.widget.winfo_rooty() - canvas.winfo_rooty() + top
        bottom = y + event.widget.winfo_height()
        desired = y - self._px(6) if y < top else bottom - canvas.winfo_height() + self._px(6)
        if y < top or bottom > top + canvas.winfo_height():
            step = max(1, int(canvas.cget('yscrollincrement')))
            desired = (math.floor(desired / step) if desired < top else math.ceil(desired / step)) * step
            canvas.yview_moveto(max(0, desired) / max(1, extent[3]))

    def _window_scale(self, window=None):
        try:
            from clawboard.windows_system import dpi_scale
            return dpi_scale(window or self.win) * config.UI_SCALE
        except (ImportError, AttributeError, tk.TclError):
            return config.DPI_SCALE * config.UI_SCALE

    def _area(self, initial=False):
        target = self.app.root if initial else self.win
        try:
            from clawboard.windows_api import MONITORINFO, MONITOR_DEFAULTTONEAREST, u32
            from clawboard.windows_geometry import top_hwnd
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(info)
            monitor = u32.MonitorFromWindow(top_hwnd(target), MONITOR_DEFAULTTONEAREST)
            if u32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                r = info.rcWork
                return r.left, r.top, r.right, r.bottom
        except (ImportError, AttributeError, OSError):
            pass
        return 0, 0, target.winfo_screenwidth(), target.winfo_screenheight()

    def _fit(self, initial=False, ratio=1):
        self.win.update_idletasks()
        left, top, right, bottom = self._area(initial)
        margin = self._px(8)
        edge = max(0, self.win.winfo_rootx() - self.win.winfo_x())
        extra_w = edge * 2
        extra_h = max(0, self.win.winfo_rooty() - self.win.winfo_y()) + edge
        aw, ah = max(1, right - left - margin * 2 - extra_w), max(1, bottom - top - margin * 2 - extra_h)
        minimum_w, minimum_h = min(aw, self._px(320)), min(ah, self._px(360))
        width = min(aw, max(minimum_w, self._px(620) if initial else round(self.win.winfo_width() * ratio)))
        height = min(ah, max(minimum_h, self._px(700) if initial else round(self.win.winfo_height() * ratio)))
        x = self.app.root.winfo_rootx() + self._px(18) if initial else self.win.winfo_x()
        y = self.app.root.winfo_rooty() + self._px(18) if initial else self.win.winfo_y()
        x = max(left + margin, min(x, right - width - extra_w - margin))
        y = max(top + margin, min(y, bottom - height - extra_h - margin))
        self.win.minsize(1, 1)
        self.win.geometry('%dx%d%+d%+d' % (width, height, x, y))
        self.win.minsize(minimum_w, minimum_h)

    def _remember_metrics(self, parent):
        result = []
        for widget in parent.winfo_children():
            options = {}
            for key in ('padx', 'pady', 'highlightthickness', 'yscrollincrement'):
                if key in widget.keys():
                    options[key] = float(widget.cget(key)) / self._scale
            if isinstance(widget, tk.Canvas) and 'width' in widget.keys():
                options['width'] = float(widget.cget('width')) / self._scale
            spacing = {}
            if widget.winfo_manager() == 'pack':
                for key in ('padx', 'pady', 'ipadx', 'ipady'):
                    value = widget.pack_info().get(key, 0)
                    values = value if isinstance(value, (tuple, list)) else self.win.tk.splitlist(str(value))
                    spacing[key] = tuple(float(part) / self._scale for part in values)
            result.append((widget, options, spacing))
            result.extend(self._remember_metrics(widget))
        return result

    def _schedule(self, key, callback, delay=120):
        previous = self._jobs.pop(key, None)
        if previous:
            self.win.after_cancel(previous)
        if not self._closed:
            def run():
                self._jobs.pop(key, None)
                if self._alive():
                    callback()
            self._jobs[key] = self.win.after(delay, run)

    def _configured(self, event):
        if event.widget is self.win and not self._closed:
            self._schedule('dpi', self._sync_scale)

    def _sync_scale(self):
        if os.name == 'nt':
            from clawboard.windows_api import u32
            if u32.GetAsyncKeyState(1) & 0x8000:
                self._schedule('dpi', self._sync_scale)
                return
        new_scale = self._window_scale()
        if abs(new_scale - self._scale) < .001:
            return
        ratio, self._scale = new_scale / self._scale, new_scale
        scroll = self.body.canvas.yview()[0]
        for template, font in self._fonts.items():
            font.configure(size=-self._px(abs(template[1]) * 96 / 72))
        for widget, options, spacing in self._metrics:
            widget.configure(**{key: round(value * new_scale) for key, value in options.items()})
            if spacing:
                widget.pack_configure(**{key: tuple(round(value * new_scale) for value in values)
                                         for key, values in spacing.items()})
        self._fit(ratio=ratio)
        self.win.update_idletasks()
        self.body._on_inner()
        self.body.canvas.yview_moveto(scroll)

    def _dispose(self):
        if self._closed:
            return
        self._closed = True
        for job in self._jobs.values():
            try:
                self.win.after_cancel(job)
            except tk.TclError:
                pass
        self._jobs.clear()
        try:
            self.app.root.unbind('<<ClawBoardUIScaleChanged>>', self._scale_binding)
        except tk.TclError:
            pass
        self._scale_binding = None

    def _destroyed(self, event):
        if event.widget is self.win:
            self._dispose()

    def close(self):
        if self._closed:
            return
        self._dispose()
        self.win.destroy()
