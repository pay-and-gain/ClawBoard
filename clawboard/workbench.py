"""Optional, read-only Tk workbench sharing the quick panel's domain policies."""
from copy import deepcopy
import ctypes
import os
import tkinter as tk
from threading import Event

from clawboard import config
from clawboard.config import FONT, FONT_B, FONT_SM
from clawboard.theme import T, is_dark
from clawboard.workbench_model import WorkbenchModel, collect_entries, full_preview, metadata


class WorkbenchWindow:
    """Search/inspect current content without changing capture, storage or paste.

    `on_locate(entry)` is the only bridge back to the quick panel. The shell can
    clear its own filters and select the current stable ID deliberately; opening,
    refreshing and closing this window never alter the panel's search or focus
    target. All workers return plain Python values through the existing tasks.
    """
    FILTERS = (('全部类型', 'all'), ('文本', 'text'), ('链接', 'url'),
               ('图片', 'image'), ('文件', 'filelist'))

    def __init__(self, app, on_locate=None, state=None):
        self.app = app
        self.on_locate = on_locate
        self.model = WorkbenchModel()
        self.win = tk.Toplevel(app.root)
        self.win.title('ClawBoard · 工作台')
        self.win.transient(app.root)
        self._closed = False
        self._rows = []
        self._selected = None
        self._generation = 0
        self._jobs = {}
        self._task_keys = (('workbench-search', id(self)), ('workbench-image', id(self)))
        self._tasks = getattr(getattr(app, 'application', None), 'tasks', None)
        self._scale = self._window_scale()
        self._signature = None
        self._preview_requested = False
        self._photo = None
        self._image_key = None
        self._filter_cancel = Event()
        prior = state or {}
        self.query = tk.StringVar(master=self.win, value=prior.get('query', ''))
        self.mode = prior.get('mode') if prior.get('mode') in ('clip', 'phrase') else 'clip'
        self.favorites = bool(prior.get('favorites', False))
        self.content_type = prior.get('content_type', 'all')
        if self.content_type not in dict((key, label) for label, key in self.FILTERS):
            self.content_type = 'all'
        self._selected = tuple(prior['selected']) if prior.get('selected') else None
        self.expanded_meta = False
        self._build()
        self.query.trace_add('write', lambda *_: self._schedule('query', 140, self.refresh))
        self.win.bind('<Escape>', lambda event: self._close_event())
        self.win.bind('<Control-f>', lambda event: self._focus_search())
        self.win.bind('<Configure>', self._configured, add='+')
        self.win.bind('<Destroy>', self._destroyed, add='+')
        self.win.protocol('WM_DELETE_WINDOW', self.close)
        self._initial_geometry()
        self.refresh()
        self._schedule('poll', 700, self._poll)

    def _px(self, logical):
        return max(1, round(logical * self._scale))

    def _font(self, font):
        # Negative pixel sizes avoid changing every Toplevel's Tk scaling when
        # this optional window moves to a monitor different from the panel.
        return (font[0], -self._px(abs(font[1]) * 96 / 72), *font[2:])

    def _window_scale(self):
        try:
            from clawboard.windows_system import dpi_scale
            return dpi_scale(self.win) * config.UI_SCALE
        except (ImportError, AttributeError, tk.TclError):
            return config.DPI_SCALE * config.UI_SCALE

    def _area(self):
        if os.name == 'nt':
            try:
                from clawboard.windows_api import MONITORINFO, MONITOR_DEFAULTTONEAREST, u32
                from clawboard.windows_geometry import top_hwnd
                monitor = u32.MonitorFromWindow(top_hwnd(self.win), MONITOR_DEFAULTTONEAREST)
                info = MONITORINFO()
                info.cbSize = ctypes.sizeof(info)
                if monitor and u32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                    r = info.rcWork
                    return r.left, r.top, r.right, r.bottom
            except (ImportError, AttributeError, OSError):
                pass
        return 0, 0, self.win.winfo_screenwidth(), self.win.winfo_screenheight()

    def _initial_geometry(self):
        self.win.update_idletasks()
        left, top, right, bottom = self._area()
        width = min(self._px(920), right - left - 24)
        height = min(self._px(600), bottom - top - 32)
        x = max(left + 8, min(self.app.root.winfo_rootx() + self._px(18), right - width - 8))
        y = max(top + 8, min(self.app.root.winfo_rooty() + self._px(18), bottom - height - 8))
        self.win.geometry('%dx%d+%d+%d' % (width, height, x, y))
        self.win.minsize(min(self._px(320), right - left - 24),
                         min(self._px(360), bottom - top - 32))

    def _button(self, master, text, command, *, primary=False):
        primary_fg = T['bg'] if is_dark(T['bg']) else '#ffffff'
        button = tk.Button(master, text=text, command=command, font=self._font(FONT_SM),
                           bg=T['acc'] if primary else T['card'],
                           fg=primary_fg if primary else T['fg'], relief='flat', bd=0,
                           activebackground=T['acc2'] if primary else T['card_h'],
                           activeforeground=primary_fg if primary else T['fg'],
                           highlightthickness=1, highlightbackground=T['line'],
                           highlightcolor=T['acc'], takefocus=True, cursor='hand2',
                           padx=self._px(10), pady=self._px(6))
        button.bind('<Return>', lambda event: (button.invoke(), 'break')[1])
        button.bind('<space>', lambda event: (button.invoke(), 'break')[1])
        return button

    def _build(self):
        self.win.configure(bg=T['bg'])
        self.header = tk.Frame(self.win, bg=T['bg'])
        self.header.pack(fill='x', padx=self._px(16), pady=(self._px(12), self._px(8)))
        tk.Label(self.header, text='内容工作台', font=self._font(FONT_B),
                 bg=T['bg'], fg=T['fg']).pack(side='left')
        tk.Label(self.header, text='查看与整理入口', font=self._font(FONT_SM),
                 bg=T['bg'], fg=T['fg2']).pack(side='right')

        self.footer = tk.Frame(self.win, bg=T['panel'])
        self.footer.pack(side='top', fill='x')
        self.close_button = self._button(self.footer, '关闭', self.close)
        self.close_button.pack(side='right', padx=self._px(8), pady=self._px(8))
        self.locate_button = self._button(self.footer, '在快速面板定位', self.locate, primary=True)
        self.locate_button.pack(side='right', pady=self._px(8))
        self.preview_button = self._button(self.footer, '预览', self._toggle_preview)
        self.preview_button.pack(side='left', padx=self._px(8), pady=self._px(8))
        self.status = tk.Label(self.win, text='', anchor='w', bg=T['bg'], fg=T['fg2'],
                               font=self._font(FONT_SM))
        self.status.pack(side='bottom', fill='x', padx=self._px(16), pady=self._px(5))

        search_bar = tk.Frame(self.win, bg=T['bg'])
        search_bar.pack(fill='x', padx=self._px(16), pady=(0, self._px(8)))
        self.refresh_button = self._button(search_bar, '刷新', self.refresh)
        self.refresh_button.pack(side='right', padx=(self._px(8), 0))
        self.type_button = self._button(search_bar, '全部类型 ▾', self._type_menu)
        self.type_button.pack(side='right', padx=(self._px(8), 0))
        self.search_entry = tk.Entry(search_bar, textvariable=self.query, relief='flat',
                                     font=self._font(FONT), bg=T['card'], fg=T['fg'],
                                     insertbackground=T['fg'], highlightthickness=1,
                                     highlightbackground=T['line'], highlightcolor=T['acc'])
        self.search_entry.pack(fill='both', expand=True, ipady=self._px(5))

        self.compact_nav = tk.Frame(self.win, bg=T['bg'])
        self.compact_nav.pack(fill='x', padx=self._px(16), pady=(0, self._px(8)))
        self._nav_buttons = []
        for text, mode, favorite in (('历史', 'clip', False), ('收藏', 'clip', True),
                                     ('常用语', 'phrase', False)):
            button = self._button(self.compact_nav, text,
                                  lambda m=mode, f=favorite: self.set_view(m, f))
            button.pack(side='left', padx=(0, self._px(6)))
            self._nav_buttons.append((button, mode, favorite))

        self.body = tk.Frame(self.win, bg=T['bg'])
        self.body.pack(fill='both', expand=True, padx=self._px(12), pady=(0, self._px(4)))
        self.body.grid_rowconfigure(0, weight=1)
        self.sidebar = tk.Frame(self.body, bg=T['panel'], width=self._px(124))
        self.sidebar.grid(row=0, column=0, sticky='nsew', padx=(0, self._px(10)))
        self.sidebar.grid_propagate(False)
        tk.Label(self.sidebar, text='我的内容', font=self._font(FONT_SM),
                 bg=T['panel'], fg=T['fg2']).pack(anchor='w', padx=self._px(12), pady=self._px(14))
        for text, mode, favorite in (('全部记录', 'clip', False), ('收藏', 'clip', True),
                                     ('常用语', 'phrase', False)):
            button = self._button(self.sidebar, text, lambda m=mode, f=favorite: self.set_view(m, f))
            button.pack(fill='x', padx=self._px(8), pady=self._px(3))
            self._nav_buttons.append((button, mode, favorite))
        tk.Label(self.sidebar, text='只读查看\n定位后在面板操作', justify='left',
                 font=self._font(FONT_SM), bg=T['panel'], fg=T['fg2']).pack(
                     side='bottom', anchor='w', padx=self._px(12), pady=self._px(14))

        self.content = tk.Frame(self.body, bg=T['bg'])
        self.content.grid(row=0, column=1, sticky='nsew')
        self.body.grid_columnconfigure(1, weight=1)
        self.content.grid_rowconfigure(0, weight=1)
        self.list_frame = tk.Frame(self.content, bg=T['card'])
        self.list_frame.grid_rowconfigure(0, weight=1)
        self.list_frame.grid_columnconfigure(0, weight=1)
        self.listbox = tk.Listbox(self.list_frame, font=self._font(FONT), bg=T['card'], fg=T['fg'],
                                  selectbackground=T['card_s'], selectforeground=T['fg'],
                                  activestyle='dotbox', exportselection=False, relief='flat', bd=0,
                                  highlightthickness=1, highlightbackground=T['line'],
                                  highlightcolor=T['acc'], selectmode='browse')
        self.listbox.grid(row=0, column=0, sticky='nsew')
        scroll = tk.Scrollbar(self.list_frame, orient='vertical', command=self.listbox.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.listbox.configure(yscrollcommand=scroll.set)
        self.listbox.bind('<<ListboxSelect>>', self._selection_changed)
        self.listbox.bind('<Return>', lambda event: (self._open_preview(), 'break')[1])

        self.detail = tk.Frame(self.content, bg=T['card'], padx=self._px(14), pady=self._px(12))
        self.detail.grid_columnconfigure(0, weight=1)
        self.detail.grid_rowconfigure(3, weight=1)
        self.detail_title = tk.Label(self.detail, text='内容预览', anchor='w', bg=T['card'],
                                     fg=T['fg'], font=self._font(FONT_B))
        self.detail_title.grid(row=0, column=0, sticky='ew')
        self.image_label = tk.Label(self.detail, text='', bg=T['card'], fg=T['fg2'],
                                    font=self._font(FONT_SM))
        self.image_label.grid(row=1, column=0, sticky='n', pady=self._px(8))
        self.meta_button = self._button(self.detail, '详细信息 ▸', self._toggle_metadata)
        self.meta_button.grid(row=2, column=0, sticky='w', pady=(0, self._px(8)))
        text_box = tk.Frame(self.detail, bg=T['card'])
        text_box.grid(row=3, column=0, sticky='nsew')
        text_box.grid_rowconfigure(0, weight=1)
        text_box.grid_columnconfigure(0, weight=1)
        self.preview = tk.Text(text_box, wrap='word', font=self._font(FONT), bg=T['card'], fg=T['fg'],
                               relief='flat', bd=0, width=1, height=1, padx=self._px(2),
                               pady=self._px(2), highlightthickness=1,
                               highlightbackground=T['line'], highlightcolor=T['acc'],
                               state='disabled', takefocus=True)
        self.preview.grid(row=0, column=0, sticky='nsew')
        text_scroll = tk.Scrollbar(text_box, orient='vertical', command=self.preview.yview)
        text_scroll.grid(row=0, column=1, sticky='ns')
        self.preview.configure(yscrollcommand=text_scroll.set)
        self.meta = tk.Label(self.detail, text='', anchor='w', justify='left', bg=T['card'], fg=T['fg2'],
                             font=self._font(FONT_SM), wraplength=self._px(320))
        self.meta.grid(row=4, column=0, sticky='ew', pady=(self._px(8), 0))
        self._layout()

    def _schedule(self, name, delay, callback):
        previous = self._jobs.pop(name, None)
        if previous:
            try:
                self.win.after_cancel(previous)
            except tk.TclError:
                pass
        if not self._closed:
            self._jobs[name] = self.win.after(delay, lambda: self._scheduled(name, callback))

    def _scheduled(self, name, callback):
        self._jobs.pop(name, None)
        if not self._closed:
            callback()

    def _configured(self, event):
        if event.widget is self.win and not self._closed:
            self._schedule('layout', 100, self._sync_layout)

    def _sync_layout(self):
        new_scale = self._window_scale()
        if abs(new_scale - self._scale) > .001:
            self.refresh_style()
        else:
            self._layout()

    def _layout(self):
        width = max(self.win.winfo_width(), self._px(320))
        sidebar = width >= self._px(800)
        wide = width >= self._px(680)
        if sidebar:
            self.sidebar.grid()
            self.compact_nav.pack_forget()
        else:
            self.sidebar.grid_remove()
            if not self.compact_nav.winfo_manager():
                self.compact_nav.pack(fill='x', padx=self._px(16), pady=(0, self._px(8)), before=self.body)
        self.list_frame.grid_remove()
        self.detail.grid_remove()
        self.content.grid_columnconfigure(0, weight=3)
        self.content.grid_columnconfigure(1, weight=0)
        if wide:
            self.list_frame.grid(row=0, column=0, sticky='nsew', padx=(0, self._px(10)))
            self.detail.grid(row=0, column=1, sticky='nsew')
            self.content.grid_columnconfigure(1, weight=4)
            self.preview_button.pack_forget()
        else:
            active = self.detail if self._preview_requested else self.list_frame
            active.grid(row=0, column=0, sticky='nsew', padx=0)
            if not self.preview_button.winfo_manager():
                self.preview_button.pack(side='left', padx=self._px(8), pady=self._px(8))
            self.preview_button.configure(text='返回列表' if self._preview_requested else '预览')
        self.meta.configure(wraplength=max(self._px(120), self.detail.winfo_width() - self._px(28)))
        self._schedule('image-fit', 120, self._fit_image)

    def _state_signature(self):
        revision = getattr(getattr(self.app, 'application', None), 'data_revision', None)
        flags = tuple((key, self.app.st.get(key)) for key in (
            'mask_sensitive', 'show_source', 'show_size', 'show_time'))
        return revision, flags

    def _poll(self):
        if self._signature != self._state_signature():
            self.refresh()
        self._schedule('poll', 700, self._poll)

    def set_view(self, mode, favorites=False):
        self.mode, self.favorites = mode, favorites
        self.refresh()

    def set_type(self, kind):
        self.content_type = kind
        self.refresh()

    def _type_menu(self):
        menu = tk.Menu(self.win, tearoff=False, bg=T['panel'], fg=T['fg'],
                       activebackground=T['card_h'], activeforeground=T['fg'], font=self._font(FONT))
        for label, kind in self.FILTERS:
            menu.add_command(label=label, command=lambda key=kind: self.set_type(key))
        menu.tk_popup(self.type_button.winfo_rootx(),
                      self.type_button.winfo_rooty() + self.type_button.winfo_height())

    def refresh(self):
        if self._closed:
            return
        self._generation += 1
        generation = self._generation
        self._filter_cancel.set()
        self._filter_cancel = cancel = Event()
        self._signature = self._state_signature()
        entries = deepcopy(collect_entries(self.app.data, self.mode))
        settings = dict(self.app.st)
        query, kind, favorites = self.query.get(), self.content_type, self.favorites
        for button, mode, favorite in self._nav_buttons:
            on = mode == self.mode and favorite == self.favorites
            button.configure(bg=T['card_s'] if on else T['card'], fg=T['acc'] if on else T['fg'])
        self.type_button.configure(text=next(label for label, key in self.FILTERS if key == kind) + ' ▾')
        self.status.configure(text='正在更新内容…')
        self.locate_button.configure(state='disabled')

        def accept(result):
            if not self._closed and generation == self._generation:
                self._accept_rows(result)

        def failed(error):
            if not self._closed and generation == self._generation:
                self._rows = []
                self.listbox.delete(0, 'end')
                self._write_preview('')
                self.status.configure(text='搜索未完成，请刷新重试（%s）' % type(error).__name__)

        if self._tasks is None:
            try:
                accept(self.model.prepare(entries, query, settings, kind, favorites,
                                          cancelled=cancel.is_set))
            except Exception as error:
                failed(error)
            return
        future = self._tasks.submit(self.model.prepare, entries, query, settings, kind, favorites,
                                    cancelled=cancel.is_set, key=self._task_keys[0],
                                    on_result=accept, on_error=failed)
        if future is None:
            if getattr(self._tasks, 'closed', False):
                self.status.configure(text='应用正在退出')
            else:
                self._schedule('query', 180, self.refresh)

    def _accept_rows(self, result):
        self._rows, errors = result
        self.listbox.delete(0, 'end')
        if self._rows:
            self.listbox.insert('end', *(label for entry, label in self._rows))
            index = next((i for i, (entry, label) in enumerate(self._rows)
                          if entry.key == self._selected), 0)
            self.listbox.selection_set(index)
            self.listbox.activate(index)
            self.listbox.see(index)
            self._selected = self._rows[index][0].key
        else:
            self._selected = None
        self.search_entry.configure(highlightbackground=T['danger'] if errors else T['line'])
        self.status.configure(text=('搜索语法：' + errors[0]) if errors else
                              ('%d 条内容 · 选择查看，定位后使用快速面板操作' % len(self._rows)))
        self._render_detail()
        self.locate_button.configure(state='normal' if self._rows else 'disabled')

    def _selection_changed(self, event=None):
        choice = self.listbox.curselection()
        if choice and choice[0] < len(self._rows):
            self._selected = self._rows[choice[0]][0].key
            self._render_detail()

    def selected_entry(self):
        return next((entry for entry, _ in self._rows if entry.key == self._selected), None)

    def _write_preview(self, text):
        self.preview.configure(state='normal')
        self.preview.delete('1.0', 'end')
        self.preview.insert('1.0', text)
        self.preview.configure(state='disabled')

    def _render_detail(self):
        entry = self.selected_entry()
        self._photo, self._image_key = None, None
        self.image_label.configure(image='', text='')
        if entry is None:
            self._write_preview('没有匹配内容。可以调整关键词或清除类型筛选。')
            self.meta.configure(text='')
            return
        self._write_preview(full_preview(entry, self.app.st))
        self.meta.configure(text=metadata(entry, self.app.st, expanded=self.expanded_meta))
        self.meta_button.configure(text='收起详细信息 ▾' if self.expanded_meta else '详细信息 ▸')
        name = entry.record.get('image_path')
        cache = getattr(self.app, '_thumbnail_cache', None)
        if not name or cache is None:
            return
        width, height = self._image_dimensions()
        key = self._selected, name, width, height
        self._image_key = key
        self.image_label.configure(text='正在准备图片预览…')

        def ready(png):
            if not self._closed and self._image_key == key:
                try:
                    self._photo = tk.PhotoImage(master=self.win, data=png)
                    self.image_label.configure(image=self._photo, text='')
                except tk.TclError:
                    self.image_label.configure(text='图片无法预览')

        def failed(error):
            if not self._closed and self._image_key == key:
                self.image_label.configure(text='图片暂时无法预览')

        if self._tasks is None:
            try:
                ready(cache.get(name, width, height))
            except Exception as error:
                failed(error)
        elif self._tasks.submit(cache.get, name, width, height, key=self._task_keys[1],
                                on_result=ready, on_error=failed) is None:
            self.image_label.configure(text='图片预览繁忙，请重新选择')

    def _image_dimensions(self):
        return (max(self._px(60), min(self._px(400), self.detail.winfo_width() - self._px(32))),
                max(self._px(40), min(self._px(220), self.detail.winfo_height() - self._px(140))))

    def _fit_image(self):
        entry = self.selected_entry()
        if entry is not None and entry.record.get('image_path') and self.detail.winfo_ismapped():
            dimensions = self._image_dimensions()
            if not self._image_key or dimensions != self._image_key[-2:]:
                self._render_detail()

    def _toggle_metadata(self):
        self.expanded_meta = not self.expanded_meta
        self._render_detail()

    def _toggle_preview(self):
        self._preview_requested = not self._preview_requested
        self._layout()
        if self._preview_requested:
            self.preview.focus_set()

    def _open_preview(self):
        self._preview_requested = True
        self._layout()
        self.preview.focus_set()

    def locate(self):
        entry = self.selected_entry()
        if entry is None:
            return
        # Resolve by stable ID again: a copied snapshot may outlive a deletion
        # or group rename while the optional workbench remains open.
        current = next((candidate for candidate in collect_entries(self.app.data, entry.kind)
                        if candidate.key == entry.key), None)
        if current is None:
            self.status.configure(text='这条内容已不在当前资料中，已更新列表')
            self.refresh()
            return
        callback = self.on_locate
        if callback:
            callback(current)
        else:
            handler = getattr(self.app, 'locate_workbench_item', None)
            if handler is None:
                self.status.configure(text='快速面板定位入口尚未连接')
                return
            handler(current.kind, current.record.get('id'), current.group_index)
        self.close()

    def snapshot(self):
        return dict(query=self.query.get(), mode=self.mode, favorites=self.favorites,
                    content_type=self.content_type, selected=self._selected)

    def refresh_style(self):
        if self._closed:
            return
        old_scale, self._scale = self._scale, self._window_scale()
        ratio = self._scale / max(.1, old_scale)
        x, y = self.win.winfo_x(), self.win.winfo_y()
        width, height = self.win.winfo_width(), self.win.winfo_height()
        focused = self.win.focus_get() is self.search_entry
        cursor = self.search_entry.index('insert')
        for widget in self.win.winfo_children():
            widget.destroy()
        self._build()
        if abs(ratio - 1) > .001:
            left, top, right, bottom = self._area()
            new_width = min(round(width * ratio), right - left - 24)
            new_height = min(round(height * ratio), bottom - top - 32)
            x = max(left + 8, min(x + (width - new_width) // 2, right - new_width - 8))
            y = max(top + 8, min(y + (height - new_height) // 2, bottom - new_height - 8))
            self.win.minsize(1, 1)
            self.win.geometry('%dx%d+%d+%d' % (new_width, new_height, x, y))
            self.win.minsize(min(self._px(320), right - left - 24),
                             min(self._px(360), bottom - top - 32))
        self.refresh()
        if focused:
            self.search_entry.icursor(cursor)
            self.search_entry.focus_set()

    rebuild = refresh_style

    def _focus_search(self):
        self.search_entry.focus_set()
        self.search_entry.selection_range(0, 'end')
        return 'break'

    def _close_event(self):
        self.close()
        return 'break'

    def _destroyed(self, event):
        if event.widget is self.win:
            self._dispose()

    def _dispose(self):
        if self._closed:
            return
        self.view_state = self.snapshot()
        self._closed = True
        self._generation += 1
        self._filter_cancel.set()
        if self._tasks:
            for key in self._task_keys:
                self._tasks.invalidate(key)
        for job in self._jobs.values():
            try:
                self.win.after_cancel(job)
            except tk.TclError:
                pass
        self._jobs.clear()
        self._photo = None

    def close(self):
        if self._closed:
            return
        self._dispose()
        self.win.destroy()
