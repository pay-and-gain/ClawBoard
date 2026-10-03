# -*- coding: utf-8 -*-
"""GeometryMixin：窗口几何 / 靠边自动隐藏 / 折叠展开 / 显示隐藏 / 重置位置。

min_size / apply_geometry / _saved_pos / _expanded_geometry / fit_geometry /
primary_monitor / clamp_to_screen / start_move / do_move / start_resize / do_resize /
toggle_pin / edge_update / _edge_hide / _edge_show / corner_pos / toggle_collapse /
hide / reset_position / ensure_onscreen / toggle_show / focus_search / rebuild。
"""
import re
import ctypes
from ctypes import wintypes

from clawboard.config import BAR_H, MIN_W, MIN_H, RESIZE_ZONE
from clawboard.theme import T, apply_theme
from clawboard.win32 import u32, monitors, dpi_scale, visible_ratio


class GeometryMixin:
    # ---------- 几何 ----------
    def min_size(self):
        """面板最小**物理**尺寸：按 DPI 换算，保证在 125%/150% 缩放的屏幕上
        也不会小到"正文装不下几个字"（否则就是用户看到的那种"里面没有内容"）"""
        k = dpi_scale(self.root)
        return int(MIN_W * k), int(MIN_H * k)

    def apply_geometry(self):
        """恢复位置。必须完整落在某一个显示器内：跨屏缝隙会让面板看起来开着却点不到"""
        if self.st.get('collapsed'):
            # 上次是折叠着退出的：按折叠态恢复，别把尺寸硬拉到最小尺寸
            self.collapsed = True
            # 折叠态启动时 _restore 还没被赋过值，先把"展开后该回到哪"算好存起来。
            # 漏了这一步的话，第一次点「—」展开会 AttributeError（真实 crash.log 见过）
            self._restore = self._expanded_geometry()
            w, h, x, y = self.fit_geometry(210, BAR_H, *(self._saved_pos()))
            self.root.geometry('%dx%d+%d+%d' % (w, h, x, y))
            self.root.minsize(160, BAR_H)
            self.body.pack_forget()
            return
        mw, mh = self.min_size()
        g = self.data.get('geom')
        if g:
            m = re.match(r'^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$', g)
            if m:
                w, h, x, y = (int(v) for v in m.groups())
                # 存档里的小尺寸自动纠正：曾经被拖成 192x293，恢复出来就看不清内容了
                w, h = max(mw, w), max(mh, h)
                w, h, x, y = self.fit_geometry(w, h, x, y)
                self.root.geometry('%dx%d+%d+%d' % (w, h, x, y))
                return
        w, h, x, y = self.fit_geometry(340, 480, 10 ** 6, 10 ** 6)
        self.root.geometry('%dx%d+%d+%d' % (w, h, x, y))

    def _saved_pos(self):
        """从存档 geom 里取出上次的坐标，折叠态恢复时沿用"""
        g = self.data.get('geom') or ''
        m = re.match(r'^\d+x\d+\+(-?\d+)\+(-?\d+)$', g)
        if m:
            return int(m.group(1)), int(m.group(2))
        return 10 ** 6, 10 ** 6

    def _expanded_geometry(self):
        """算出一个可用的展开态几何字符串。

        两处会用到，都得容错：
        1. 折叠态启动后的第一次展开（`_restore` 还是 None）
        2. `_restore` 解析失败时兜底
        `data['geom']` 在折叠期间不会被覆盖（见 save()），所以这里拿到的就是
        上次展开时的尺寸与位置；没有存档则回退到 340x480。
        """
        mw, mh = self.min_size()
        m = re.match(r'^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$', self.data.get('geom') or '')
        if m:
            w, h, x, y = (int(v) for v in m.groups())
        else:
            w, h, x, y = 340, 480, 10 ** 6, 10 ** 6
        w, h = max(mw, w), max(mh, h)
        w, h, x, y = self.fit_geometry(w, h, x, y)
        return '%dx%d+%d+%d' % (w, h, x, y)

    def fit_geometry(self, w, h, x, y):
        """保证窗口完整落在某个显示器内；做不到就放到主屏右下角并按需缩小"""
        for (l, t, r, b) in monitors():
            if x >= l and y >= t and x + w <= r and y + h <= b:
                return w, h, x, y
        l, t, r, b = self.primary_monitor()
        w = min(w, max(260, r - l - 24))
        h = min(h, max(200, b - t - 24))
        return w, h, r - w - 14, b - h - 62

    @staticmethod
    def primary_monitor():
        for m in monitors():
            if m[0] <= 0 <= m[2] and m[1] <= 0 <= m[3]:
                return m
        return monitors()[0]

    def clamp_to_screen(self):
        """拖动时保证至少 80x40 露在屏幕内，防止拖出去找不回来"""
        w, h = self.root.winfo_width(), self.root.winfo_height()
        x, y = self.root.winfo_x(), self.root.winfo_y()
        best, bi = -1, 0
        for i, (l, t, r, b) in enumerate(monitors()):
            iw = min(x + w, r) - max(x, l)
            ih = min(y + h, b) - max(y, t)
            if iw > 0 and ih > 0 and iw * ih > best:
                best, bi = iw * ih, i
        l, t, r, b = monitors()[bi]
        w = min(w, max(260, r - l - 24))
        h = min(h, max(200, b - t - 24))
        # 完整推进该显示器内部，绝不跨屏
        nx = min(max(x, l), r - w)
        ny = min(max(y, t), b - h)
        if (nx, ny) != (x, y) or (w, h) != (self.root.winfo_width(), self.root.winfo_height()):
            self.root.geometry('%dx%d+%d+%d' % (w, h, nx, ny))

    def start_move(self, e):
        self._mx, self._my = e.x_root, e.y_root

    def do_move(self, e):
        # 边缘拉伸进行中时让位：否则拖标题栏上沿会同时"移动+拉伸"打架
        if self._rz_dir:
            return
        self.root.geometry('+%d+%d' % (self.root.winfo_x() + e.x_root - self._mx,
                                       self.root.winfo_y() + e.y_root - self._my))
        self.clamp_to_screen()
        self._mx, self._my = e.x_root, e.y_root

    def start_resize(self, e):
        self._rx, self._ry = e.x_root, e.y_root
        self._rw, self._rh = self.root.winfo_width(), self.root.winfo_height()

    def do_resize(self, e):
        # 下限必须用 min_size()（DPI 换算后的真实下限）。原来硬编码 max(240,160)
        # 比 min_size 小一大截，两套下限打架：grip 能把窗口拉到比最小尺寸还小，
        # 高度不足时工具条被 vlist 的 expand 挤出窗口 —— "下方按钮被遮挡"的元凶之一
        mw, mh = self.min_size()
        w = max(mw, self._rw + (e.x_root - self._rx))
        h = max(mh, self._rh + (e.y_root - self._ry))
        self.root.geometry('%dx%d' % (w, h))
        self.vlist.update_view()

    # ---------- 窗口边缘"随意拉伸"（四边 + 四角） ----------
    # 无边框窗口没有系统边框可抓，自己在窗口四周留一条热区：
    # 鼠标靠近边缘 → 光标变拉伸样式；按下拖动 → 按方向 resize（左/上边同时移动窗口）。
    # 折叠态禁用（标题条 210x34 拉伸会破坏折叠布局）。

    _CURSOR_OF = {'n': 'top_side', 's': 'bottom_side', 'e': 'right_side',
                  'w': 'left_side', 'ne': 'top_right_corner', 'nw': 'top_left_corner',
                  'se': 'bottom_right_corner', 'sw': 'bottom_left_corner'}

    def _resize_dir(self, e):
        """鼠标落在窗口边缘 RESIZE_ZONE 内时返回方向（'n'/'se'/…），否则 None"""
        if self.collapsed or self.hidden:
            return None
        try:
            x = e.x_root - self.root.winfo_rootx()
            y = e.y_root - self.root.winfo_rooty()
        except Exception:
            return None
        w, h = self.root.winfo_width(), self.root.winfo_height()
        if w <= 1 or h <= 1:          # 未布局/折叠态的假尺寸，不判定
            return None
        z = RESIZE_ZONE
        left, right = x <= z, x >= w - z
        top, bottom = y <= z, y >= h - z
        d = ''
        if top:
            d += 'n'
        elif bottom:
            d += 's'
        if left:
            d += 'w'
        elif right:
            d += 'e'
        return d or None

    def on_zone_motion(self, e):
        """悬停边缘 → 切换拉伸光标（只在方向变化时 configure，避免每帧开销）"""
        d = self._resize_dir(e)
        if d == self._hover_dir:
            return
        self._hover_dir = d
        self.root.configure(cursor=self._CURSOR_OF.get(d, ''))

    def on_zone_press(self, e):
        d = self._resize_dir(e)
        if not d:
            return
        self._rz_dir = d
        self._rz = (e.x_root, e.y_root,
                    self.root.winfo_width(), self.root.winfo_height(),
                    self.root.winfo_x(), self.root.winfo_y())

    def on_zone_drag(self, e):
        d = self._rz_dir
        if not d:
            return
        x0, y0, w0, h0, wx0, wy0 = self._rz
        dx, dy = e.x_root - x0, e.y_root - y0
        mw, mh = self.min_size()
        w, h, x, y = w0, h0, wx0, wy0
        if 'e' in d:
            w = max(mw, w0 + dx)
        if 's' in d:
            h = max(mh, h0 + dy)
        if 'w' in d:                      # 拖左边：宽度变的同时窗口跟着走
            w = max(mw, w0 - dx)
            x = wx0 + (w0 - w)
        if 'n' in d:
            h = max(mh, h0 - dy)
            y = wy0 + (h0 - h)
        self.root.geometry('%dx%d+%d+%d' % (w, h, x, y))
        self.clamp_to_screen()
        self.vlist.update_view()

    def on_zone_release(self, e):
        if self._rz_dir:
            self._rz_dir = None
            self.save(True)               # 拉完把新尺寸存档（折叠态不会走到这）

    def bind_edge_resize(self):
        """在 root 上挂边缘拉伸的四件套。root 处于 bindtag 末位，
        子控件的事件处理不受影响；do_move 里用 _rz_dir 让位避免拖动/拉伸打架。"""
        r = self.root
        r.bind('<Motion>', self.on_zone_motion)
        r.bind('<ButtonPress-1>', self.on_zone_press)
        r.bind('<B1-Motion>', self.on_zone_drag)
        r.bind('<ButtonRelease-1>', self.on_zone_release)

    def toggle_pin(self):
        cur = bool(self.root.attributes('-topmost'))
        self.root.attributes('-topmost', not cur)
        self.tip('已取消置顶' if cur else '窗口已置顶')

    # ---------- 靠边自动隐藏（像输入法一样贴边收纳） ----------
    def edge_update(self):
        """贴住屏幕左/右/上边缘且鼠标离开 → 收起只留 6px；鼠标碰边缘 → 滑出"""
        st = self.st
        if not st.get('edge_hide') or self.hidden or self.collapsed:
            if self._edge_hidden:
                self._edge_show()
            return
        try:
            pt = wintypes.POINT()
            if not u32.GetCursorPos(ctypes.byref(pt)):
                return
            mx, my = pt.x, pt.y
        except Exception:
            return
        if self._edge_hidden:
            gap = 10
            sw = self.root.winfo_screenwidth()
            side = self._edge_side
            near = ((side == 'left' and mx <= gap) or
                    (side == 'right' and mx >= sw - gap) or
                    (side == 'top' and my <= gap))
            if near:
                self._edge_show()
            return
        wx, wy = self.root.winfo_x(), self.root.winfo_y()
        ww, wh = self.root.winfo_width(), self.root.winfo_height()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        side = None
        if wx <= 4:
            side = 'left'
        elif wx + ww >= sw - 4:
            side = 'right'
        elif wy <= 4:
            side = 'top'
        if side is None:
            self._edge_tick = 0
            return
        inside = (wx - 2 <= mx <= wx + ww + 2) and (wy - 2 <= my <= wy + wh + 2)
        if inside:
            self._edge_tick = 0
            return
        self._edge_tick += 1
        if self._edge_tick >= max(2, int(st.get('edge_delay', 8))):
            self._edge_hide(side)

    def _edge_hide(self, side):
        wx, wy = self.root.winfo_x(), self.root.winfo_y()
        ww, wh = self.root.winfo_width(), self.root.winfo_height()
        sw = self.root.winfo_screenwidth()
        self._edge_side = side
        self._edge_pos = (wx, wy)      # 收起前记住原位，滑出时原样还原
        if side == 'left':
            nx, ny = -(ww - 6), wy
        elif side == 'right':
            nx, ny = sw - 6, wy
        else:
            nx, ny = wx, -(wh - 6)
        self.root.geometry('+%d+%d' % (nx, ny))
        self._edge_hidden = True

    def _edge_show(self):
        if self._edge_pos:
            self.root.geometry('+%d+%d' % self._edge_pos)
        self._edge_hidden = False
        self._edge_tick = 0

    def corner_pos(self, w, h):
        """所在屏幕的右下角坐标（底部留出任务栏的高度）。
        折叠成一条标题栏后还留在原处很突兀，贴到右下角更像是"收起来了"。"""
        cx = self.root.winfo_x() + self.root.winfo_width() // 2
        cy = self.root.winfo_y() + self.root.winfo_height() // 2
        scr = None
        for box in monitors():
            l, t, r, b = box
            if l <= cx <= r and t <= cy <= b:
                scr = box
                break
        l, t, r, b = scr or self.primary_monitor()
        return max(l + 2, r - w - 14), max(t + 2, b - h - 62)

    def toggle_collapse(self):
        self.collapsed = not self.collapsed
        # 折叠状态要跟着存盘：不然折叠着退出后，存档里剩下折叠尺寸，
        # 重启就成了"窗口是折叠大小、程序却以为自己展开着"
        self.st['collapsed'] = self.collapsed
        self.save(True)
        if self.collapsed:
            self._restore = self.root.geometry()
            self.body.pack_forget()
            self.root.minsize(160, BAR_H)   # 先放开最小尺寸，否则折叠不成一条标题栏
            if self.st.get('collapse_to_corner', True):
                x, y = self.corner_pos(210, BAR_H)     # 贴到右下角
            else:
                x, y = self.root.winfo_x(), self.root.winfo_y()
            self.root.geometry('210x%d+%d+%d' % (BAR_H, x, y))
        else:
            mw, mh = self.min_size()
            self.root.minsize(mw, mh)
            m = re.match(r'^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$', self._restore or '')
            if m:
                w, h, x, y = (int(v) for v in m.groups())
                w, h = max(mw, w), max(mh, h)
                w, h, x, y = self.fit_geometry(w, h, x, y)
                self.root.geometry('%dx%d+%d+%d' % (w, h, x, y))
            else:
                # _restore 可能是 None（折叠态启动后第一次展开）或格式意外，
                # 都不该让展开失败 —— 用存档里的展开几何兜底
                self.root.geometry(self._expanded_geometry())
            self.body.pack(fill='both', expand=True)
            self.render()

    def hide(self):
        """关闭按钮 / Esc：默认隐藏到托盘并气泡告知，也可在设置里改成直接退出"""
        self.save()
        self.set_num_hint(False)     # 面板藏起来时，Ctrl 的 KeyRelease 可能收不到
        if self.st.get('close_action') == 'quit':
            self.quit_app()
            return
        self.root.withdraw()
        self.hidden = True
        if not self._told_tray:
            self._told_tray = True
            self.hw.balloon('ClawBoard 还在后台运行',
                            '面板已隐藏。点托盘图标或按 %s 叫回来；'
                            '要彻底退出：右键托盘图标 → 退出'
                            % (self.st.get('hotkey', 'ctrl+shift+v').upper()))

    def reset_position(self):
        """应急：把面板拉回主屏右下角（托盘菜单与热键唤起都会自动兜底）"""
        w, h = 340, 480
        _, _, r, b = self.primary_monitor()
        self.root.geometry('%dx%d+%d+%d' % (w, h, r - w - 14, b - h - 62))
        self.root.deiconify()
        self.root.attributes('-topmost', True)
        self.root.lift()
        self.hidden = False
        self._edge_hidden = False
        self._edge_tick = 0
        self.render()
        self.tip('面板位置已重置')

    def ensure_onscreen(self):
        """窗口跑出屏幕时自动拉回，避免"点了没反应" """
        m = re.match(r'^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$', self.root.geometry())
        if m:
            w, h, x, y = (int(v) for v in m.groups())
            if visible_ratio(x, y, w, h) < 0.999:      # 跨屏/出屏都算不可见
                self.reset_position()
                return True
        return False

    def toggle_show(self):
        if self.hidden:
            self.hidden = False
            self.root.deiconify()
            self.root.attributes('-topmost', True)
            self.root.lift()
            if not self.ensure_onscreen():
                self.focus_search()
                self.render()
        else:
            self.hide()

    def focus_search(self):
        try:
            self.search_entry.focus_force()
        except Exception:
            pass

    def rebuild(self):
        apply_theme(self.st)          # 换主题/换背景后要重新推导整套配色
        self.root.configure(bg=T['bg'])
        self.build_ui()
        self.render()
        self.root.after(120, self.render)
