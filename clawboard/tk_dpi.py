# -*- coding: utf-8 -*-
"""主线程跨屏 DPI 适配；只在稳定落屏后重建主面板并恢复交互状态。"""
import re

from clawboard import config, runtime
from clawboard.windows_system import dpi_scale
from clawboard.windows_api import u32


class DpiMixin:
    def sync_window_dpi(self):
        # withdraw 后 Tk 的目标几何和原生 HWND DPI 可能暂不一致，重新映射后再适配。
        if self.hidden:
            self._dpi_pending = None
            return False
        scale = dpi_scale(self.root)
        if abs(scale - self._dpi_scale) < 0.001:
            self._dpi_pending = None
            self._dpi_ready = True
            return False
        # 连续两轮看到同一 DPI 且鼠标已放开，避免边拖边销毁标题栏或输入控件。
        if self._dpi_pending != scale:
            self._dpi_pending = scale
            return False
        if (u32.GetAsyncKeyState(1) & 0x8000 or self.root.grab_current() is not None
                or self._edge_hidden):
            return False
        old = self._dpi_scale
        ratio = scale / old if self._dpi_ready else 1.0
        w, h = self.root.winfo_width(), self.root.winfo_height()
        x, y = self.root.winfo_x(), self.root.winfo_y()
        state = self._dpi_view_state()
        self._dpi_scale = config.DPI_SCALE = scale
        self._dpi_ready = True
        self._dpi_pending = None
        runtime.BASE_SCALING = (96 / 72) * scale
        self.root.tk.call('tk', 'scaling', runtime.BASE_SCALING * config.UI_SCALE)
        self.root.minsize(1, 1)
        if self.collapsed:
            nw, nh = config.scaled(210), config.scaled(config.BAR_H)
            # 折叠期间也调整展开尺寸；坐标仍由展开时的 fit_geometry 校验。
            match = re.match(r'^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$', self._restore or '')
            if match:
                rw, rh, rx, ry = map(int, match.groups())
                self._restore = '%dx%d+%d+%d' % (round(rw * ratio), round(rh * ratio), rx, ry)
            minimum = (config.scaled(160), nh)
        else:
            minimum = self.min_size()
            nw, nh = max(minimum[0], round(w * ratio)), max(minimum[1], round(h * ratio))
        # 保持中心点，防止单侧放大使窗口再次跨回另一屏，形成 DPI/geometry 来回震荡。
        self.root.geometry('%dx%d+%d+%d' % (nw, nh, x + (w - nw) // 2, y + (h - nh) // 2))
        self._dpi_restore_view(state)
        self.root.minsize(*minimum)
        return True

    def _dpi_view_state(self):
        view, entry = self.vlist, self.search_entry
        row = max(1, config.scaled(config.ITEM_H))
        selected = (entry.index('sel.first'), entry.index('sel.last')) if entry.selection_present() else None
        previous = self._dpi_deferred_view
        key = self._dpi_view_key()
        if previous and previous['key'] != key:
            previous = None
        return dict(top=previous['top'] if previous else view.canvas.canvasy(0) / row,
                    multi=previous['multi'] if previous else set(view.multi), number=view.show_num,
                    cursor=entry.index('insert'), selected=selected, xview=entry.xview()[0],
                    focus=self.root.focus_get() == entry, key=key)

    def _dpi_view_key(self):
        return self.search.get().strip(), self.tab, self.data.get('gi')

    def _dpi_restore_view(self, state):
        self.close_preview()
        self.vlist.tip.hide()
        self.build_ui()
        self.render()
        self.root.update_idletasks()
        view, entry = self.vlist, self.search_entry
        view.show_num = state['number']
        self._dpi_deferred_view = state
        if not self._filter_pending:
            self.restore_dpi_view()
        else:
            view.multi = set(state['multi'])
        entry.icursor(state['cursor'])
        if state['selected']:
            entry.selection_range(*state['selected'])
        entry.xview_moveto(state['xview'])
        if state['focus']:
            entry.focus_set()

    def restore_dpi_view(self):
        state = self._dpi_deferred_view
        if state is None:
            return
        self._dpi_deferred_view = None
        if state['key'] != self._dpi_view_key():
            return
        view = self.vlist
        view.multi = state['multi'] & {item.get('id') for item in view.items}
        view._pending_top = state['top'] * config.scaled(config.ITEM_H)
        view.update_view()
