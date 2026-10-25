# -*- coding: utf-8 -*-
"""GeometryMixin：窗口几何 / 靠边自动隐藏 / 折叠展开 / 显示隐藏 / 重置位置。

min_size / apply_geometry / _saved_pos / _expanded_geometry / fit_geometry /
primary_monitor / _enough_visible / _nearest_monitor / clamp_to_screen /
start_move / do_move / start_resize / do_resize /
toggle_pin / edge_update / _edge_hide / _edge_show / _window_monitor / corner_pos /
toggle_collapse / hide / reset_position / ensure_onscreen / toggle_show /
focus_search / rebuild。
"""
import re
import ctypes
from ctypes import wintypes

from clawboard import config
from clawboard import runtime
from clawboard.config import (BAR_H, MIN_W, MIN_H, RESIZE_ZONE,
                              UI_SCALE_LEVELS, scaled)
from clawboard.theme import T, apply_theme
from clawboard.tk_dpi import DpiMixin
from clawboard.win32 import (u32, monitors, dpi_scale, visible_ratio,
                             apply_window_effects)

# 「没有存档位置」的哨兵坐标（apply_geometry / _saved_pos / _expanded_geometry 都用它）。
# 抽成常量是为了让 fit_geometry 能区分「哨兵 → 主屏默认位」与「真实坐标 → 最近屏回推」。
_NO_POS = 10 ** 6


class GeometryMixin(DpiMixin):
    # ---------- 窗口外观（圆角 + 毛玻璃）----------
    def apply_effects(self):
        """应用窗口外观开关（圆角 / Acrylic 毛玻璃）。

        启动时调一次；用户在设置里切换开关后也会调。
        老系统或不支持的环境下静默失败（不弹错、不影响功能）。
        """
        try:
            r, f = apply_window_effects(
                self.root,
                rounded=bool(self.st.get('rounded', True)),
                frosted=bool(self.st.get('frosted', True)),
            )
            self._fx_supported = (r, f)
        except Exception:
            self._fx_supported = (False, False)

    # ---------- UI 等比缩放 ----------
    def apply_ui_scale_init(self):
        """启动时：记录真实 DPI 的 tk scaling，并应用存档里的 UI 缩放档位。

        必须在 build_ui 之前调用（字体走 tk scaling、布局尺寸走 scaled()，
        两者都要在构建 UI 前就位）。BASE_SCALING 是真实 DPI 值，UI 缩放只改
        实时 tk scaling，绝不回写 BASE_SCALING —— 否则 dpi_scale() 双重缩放。
        """
        # frozen 环境下 tk scaling 会延迟到窗口映射后才反映真实 DPI，
        # 所以 BASE_SCALING 从 Win32 窗口 DPI 推算，不读已受用户档位影响的 tk scaling。
        self._dpi_scale = config.DPI_SCALE = dpi_scale(self.root)
        runtime.BASE_SCALING = (96 / 72) * self._dpi_scale
        lvl = float(self.st.get('ui_scale') or 1.0)
        if lvl not in UI_SCALE_LEVELS:
            lvl = 1.0
        config.UI_SCALE = lvl
        self.root.tk.call('tk', 'scaling', runtime.BASE_SCALING * lvl)

    def set_ui_scale(self, level):
        """切换 UI 等比缩放档位。窗口尺寸、字体、布局、最小尺寸一起等比缩放。"""
        level = float(level)
        if level not in UI_SCALE_LEVELS or level == config.UI_SCALE:
            return
        old = config.UI_SCALE
        config.UI_SCALE = level
        self.st['ui_scale'] = level
        self.root.tk.call('tk', 'scaling', runtime.BASE_SCALING * level)
        if not self.collapsed:
            # 窗口几何也等比缩放（相对屏幕左上角不动，宽高按比例）。
            # 关键：必须先放开旧 minsize，否则 geometry 会被它 clamp 住
            # （和折叠时"先放开下限"同一个坑，v1.4.1 就踩过）。
            ratio = level / old
            w = max(1, int(self.root.winfo_width() * ratio))
            h = max(1, int(self.root.winfo_height() * ratio))
            mw, mh = self.min_size()
            w, h = max(mw, w), max(mh, h)
            x, y = self.root.winfo_x(), self.root.winfo_y()
            w, h, x, y = self.fit_geometry(w, h, x, y)
            self.root.minsize(1, 1)               # 先放开旧下限
            self.root.geometry('%dx%d+%d+%d' % (w, h, x, y))
            self.root.minsize(mw, mh)             # 再设回缩放后的新下限
        self.rebuild()
        if not self.collapsed:
            self.root.minsize(*self.min_size())
        self.tip('已缩放至 %d%%' % int(level * 100))
        self.save(True)

    def cycle_ui_scale(self, step):
        """按档位步进缩放（+1 放大一档 / -1 缩小一档），用于快捷键"""
        levels = list(UI_SCALE_LEVELS)
        cur = config.UI_SCALE if config.UI_SCALE in levels else 1.0
        i = levels.index(cur)
        j = max(0, min(len(levels) - 1, i + step))
        if j != i:
            self.set_ui_scale(levels[j])

    # ---------- 几何 ----------
    def min_size(self):
        """面板最小**物理**尺寸：按 DPI 换算，保证在 125%/150% 缩放的屏幕上
        也不会小到"正文装不下几个字"（否则就是用户看到的那种"里面没有内容"）；
        再乘 UI 缩放档位 —— 整体缩小时最小尺寸也跟着等比缩小。"""
        k = config.DPI_SCALE
        # 必须用 config.UI_SCALE（模块属性），不能 import 快照 ——
        # 快照在 set_ui_scale 更新 config.UI_SCALE 后不会跟着变
        return int(MIN_W * k * config.UI_SCALE), int(MIN_H * k * config.UI_SCALE)

    def apply_geometry(self):
        """恢复位置：只要还「抓得住」（≥80×40 可见）就原样恢复，允许跨屏 / 部分出屏"""
        if self.st.get('collapsed'):
            # 上次是折叠着退出的：按折叠态恢复，别把尺寸硬拉到最小尺寸
            self.collapsed = True
            # 折叠态启动时 _restore 还没被赋过值，先把"展开后该回到哪"算好存起来。
            # 漏了这一步的话，第一次点「—」展开会 AttributeError（真实 crash.log 见过）
            self._restore = self._expanded_geometry()
            w, h, x, y = self.fit_geometry(scaled(210), scaled(BAR_H), *(self._saved_pos()))
            self.root.geometry('%dx%d+%d+%d' % (w, h, x, y))
            self.root.minsize(scaled(160), scaled(BAR_H))
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
        """保证窗口「抓得住」（≥ min(80,w)×min(40,h) 露在某个显示器内）；否则拉回最近屏。

        与旧实现（要求**完整**落在某一个显示器内、做不到就回退主屏）的关键差别：
        现在只要还够得着就原样保留 —— 允许跨屏、允许部分出屏地存档与恢复。
        这正是多屏下「跨屏位置存不住、下次启动被丢回主屏」的根源。
        没有存档时的哨兵坐标（_NO_POS）仍回退主屏右下角（首启默认位）。
        """
        if x < _NO_POS and y < _NO_POS and self._enough_visible(x, y, w, h):
            return w, h, x, y                        # 可见足够 → 原样保留
        if x >= _NO_POS or y >= _NO_POS:
            l, t, r, b = self.primary_monitor()      # 哨兵 → 主屏右下角（首启）
        else:
            l, t, r, b = self._nearest_monitor(x, y, w, h)   # 拖出屏 → 拉回最近屏
        w = min(w, max(260, r - l - 24))
        h = min(h, max(200, b - t - 24))
        return w, h, r - w - 14, b - h - 62

    @staticmethod
    def primary_monitor():
        for m in monitors():
            if m[0] <= 0 < m[2] and m[1] <= 0 < m[3]:
                return m
        return monitors()[0]

    @staticmethod
    def _enough_visible(x, y, w, h):
        """窗口是否在某个显示器里露出一块「抓得住」的区域（放行判据）。

        判据：可见矩形宽 ≥ min(80,w) 且高 ≥ min(40,h)。
        - 80 宽足够点中标题栏（标题栏几乎横贯窗口宽度）；
        - 40 高 > 标题栏高度 scaled(BAR_H)≈34：当窗口**顶边仍在屏内**时（下 / 左 / 右
          方向贴边、含向左/右/下拖出屏），标题栏都落在可见区内，可被抓住拖回。
        边界（如实说明）：本判据**不**保证「被上推到顶边以外」时标题栏可见 —— 那时露出的
        是窗口**底部** 40px、标题栏在屏外。但该状态**拖拽不可达**：do_move 只绑标题栏，
        光标被限制在屏内，实测上推极限 window_y≈−34（窗口主体仍完整可见）；
        万一真出现（如跨屏分辨率变化），reset_position() 能把面板召回主屏右下角。
        这是 clamp_to_screen / fit_geometry 共用的「放行」判据：够得着就一笔不动，
        窗口因此可以自由跨屏（跨屏时整个窗口 100% 落在虚拟桌面内）。
        """
        if w <= 0 or h <= 0:
            return False
        nw, nh = min(80, w), min(40, h)
        for (l, t, r, b) in monitors():
            if (min(x + w, r) - max(x, l) >= nw and
                    min(y + h, b) - max(y, t) >= nh):
                return True
        return False

    @staticmethod
    def _nearest_monitor(x, y, w, h):
        """离窗口最近的显示器矩形：优先相交面积最大者；完全不相交则取矩形间距最近者。

        回推目标必须是「最近」而不是固定主屏 —— 用户把面板拖到副屏附近时，
        固定主屏会让面板莫名其妙地跨半个桌面跳回主屏。
        """
        mons = monitors()
        if not mons:
            # 理论上不可达（win32.monitors() 有 [(0,0,1920,1080)] 兜底），但别留崩溃点。
            # 注意：这里不能转调 primary_monitor() —— 它自己也是 monitors()[0]，同样会炸。
            return (0, 0, 1920, 1080)
        best, hit = -1, None
        for (l, t, r, b) in mons:
            iw = min(x + w, r) - max(x, l)
            ih = min(y + h, b) - max(y, t)
            if iw > 0 and ih > 0 and iw * ih > best:
                best, hit = iw * ih, (l, t, r, b)
        if hit is not None:
            return hit
        # 与所有显示器都不相交 → 按「窗口中心到矩形」的距离取最近
        cx, cy = x + w / 2.0, y + h / 2.0
        far, pick = None, mons[0]
        for (l, t, r, b) in mons:
            dx = max(l - cx, 0.0, cx - r)
            dy = max(t - cy, 0.0, cy - b)
            d = dx * dx + dy * dy
            if far is None or d < far:
                far, pick = d, (l, t, r, b)
        return pick

    def clamp_to_screen(self):
        """拖动时保证至少 min(80,w)×min(40,h) 露在某个显示器内（防拖丢）。

        只要还够得着就**一个像素都不动** —— 如此窗口才能自由地跨屏移动。
        旧实现每次把窗口完整推进「相交面积最大」的那台显示器，于是窗口一贴住本屏
        右边界就被钳在 r-w，永远长不到「相交面积翻转」的程度 → 两个方向都跨不过去。
        只有露出的区域已经抓不住时，才回推到**最近**的显示器。
        """
        w, h = self.root.winfo_width(), self.root.winfo_height()
        x, y = self.root.winfo_x(), self.root.winfo_y()
        if self._enough_visible(x, y, w, h):
            return
        l, t, r, b = self._nearest_monitor(x, y, w, h)
        w = min(w, max(260, r - l - 24))
        h = min(h, max(200, b - t - 24))
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
        """鼠标落在窗口边缘 scaled(RESIZE_ZONE) 内时返回方向（'n'/'se'/…），否则 None"""
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
        z = scaled(RESIZE_ZONE)
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

    # ---------- 置顶状态机（用户意图 × 全屏抑制） ----------
    def sync_topmost(self):
        """按「用户意图 + 全屏抑制」统一决定实际的 -topmost，只在变化时才写。

        实际置顶 = 用户意图(_topmost_user) 且 未被抑制。
        抑制有两种：① 前台是全屏程序**且**面板不是用户主动呼出来的（这时面板应被
        游戏覆盖，保持可见、只是不再置顶）；② 粘贴「让位」进行中（_topmost_yield）。

        只改 `root.attributes('-topmost')`，**绝不改 `_topmost_user`**：否则用户
        手动取消置顶后，一进一出全屏就会被强行改回置顶（用户会认为是 bug）。
        """
        want = bool(self._topmost_user)
        if self._topmost_yield or (self._fg_fullscreen and not self._user_pulled):
            want = False
        if want != self._topmost_applied:
            try:
                self.root.attributes('-topmost', want)
            except Exception:
                pass
            self._topmost_applied = want

    def toggle_pin(self):
        """标题栏 📌：切换用户期望置顶的意图，再由 sync_topmost 落地。"""
        self._topmost_user = not bool(self._topmost_user)
        self.sync_topmost()
        self.tip('窗口已置顶' if self._topmost_user else '已取消置顶')

    # ---------- 靠边自动隐藏（像输入法一样贴边收纳） ----------
    def edge_update(self):
        """贴住**窗口所在显示器**的左/右/上边缘且鼠标离开 → 收起只留 6px；鼠标碰边缘 → 滑出。

        边缘判定与收起位置一律用窗口所在显示器，不能用主屏尺寸：
        副屏上 `wx + ww >= winfo_screenwidth()-4` 会恒真（那是主屏宽），窗口会被
        误判成「贴右边缘」并被搬到主屏最右（edge_hide 一开就是必现）。
        """
        workbench = getattr(self, '_workbench_window', None)
        if workbench is not None and workbench.win.winfo_exists() and workbench.win.winfo_ismapped():
            self._edge_tick = 0
            if self._edge_hidden:
                self._edge_show()
            return
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
            l, t, r, b = self._edge_mon or self._window_monitor()
            side = self._edge_side
            near = ((side == 'left' and mx <= l + gap) or
                    (side == 'right' and mx >= r - gap) or
                    (side == 'top' and my <= t + gap))
            if near:
                self._edge_show()
            return
        wx, wy = self.root.winfo_x(), self.root.winfo_y()
        ww, wh = self.root.winfo_width(), self.root.winfo_height()
        l, t, r, b = self._window_monitor()
        side = None
        if wx <= l + 4:
            side = 'left'
        elif wx + ww >= r - 4:
            side = 'right'
        elif wy <= t + 4:
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
        l, t, r, b = self._window_monitor()     # 用窗口所在屏，收起后仍在同一块屏上
        self._edge_side = side
        self._edge_mon = (l, t, r, b)           # 记住所在屏：碰边滑出按它判定
        self._edge_pos = (wx, wy)               # 收起前记住原位，滑出时原样还原
        if side == 'left':
            nx, ny = l - (ww - 6), wy
        elif side == 'right':
            nx, ny = r - 6, wy
        else:
            nx, ny = wx, t - (wh - 6)
        self.root.geometry('+%d+%d' % (nx, ny))
        self._edge_hidden = True

    def _edge_show(self):
        if self._edge_pos:
            self.root.geometry('+%d+%d' % self._edge_pos)
        self._edge_hidden = False
        self._edge_tick = 0

    def _window_monitor(self):
        """窗口**中心点**所在显示器（窗口跨屏时按中心点归属）；取不到则主屏。

        多屏下绝不能再拿 winfo_screenwidth()/winfo_screenheight() 当屏幕边界
        （那只是主屏），否则副屏上的窗口会被按主屏边界错误判定贴边/收起/对齐。
        """
        cx = self.root.winfo_x() + self.root.winfo_width() // 2
        cy = self.root.winfo_y() + self.root.winfo_height() // 2
        for (l, t, r, b) in monitors():
            if l <= cx < r and t <= cy < b:
                return (l, t, r, b)
        return self.primary_monitor()

    def corner_pos(self, w, h):
        """窗口所在屏幕的右下角坐标（底部留出任务栏的高度）。
        折叠成一条标题栏后还留在原处很突兀，贴到右下角更像是"收起来了"。"""
        l, t, r, b = self._window_monitor()
        return max(l + 2, r - w - 14), max(t + 2, b - h - 62)

    def preview_corner(self, w, h):
        """角落预览浮窗（复制提示 / 内容预览 / 图片预览）的落点，返回 (x, y)。

        贴**面板所在显示器**的角落，并与面板错开一侧（面板中点在该屏左半 → 落右下角，
        否则落左下角，避免遮住面板）；y 按该屏底边算 —— 副屏顶边比主屏低（t≠0），
        所以必须用该屏矩形，不能用主屏高度。

        为什么放到 app 侧算：预览浮窗自己只能拿 winfo_screenwidth/height（那是**主屏**），
        面板挪到副屏后预览会孤零零跑到主屏角落、跟面板分居两块屏 —— 正是"不能正常使用"。
        """
        l, t, r, b = self._window_monitor()
        cx = self.root.winfo_x() + self.root.winfo_width() // 2
        if cx - l < (r - l) // 2:
            return r - w - 12, b - h - 62
        return l + 12, b - h - 62

    def toggle_collapse(self):
        self.close_preview()         # 折叠时角落预览一并收起
        self.collapsed = not self.collapsed
        # 折叠状态要跟着存盘：不然折叠着退出后，存档里剩下折叠尺寸，
        # 重启就成了"窗口是折叠大小、程序却以为自己展开着"
        self.st['collapsed'] = self.collapsed
        self.save(True)
        if self.collapsed:
            self._restore = self.root.geometry()
            self.body.pack_forget()
            self.root.minsize(scaled(160), scaled(BAR_H))   # 先放开最小尺寸，否则折叠不成一条标题栏
            if self.st.get('collapse_to_corner', True):
                x, y = self.corner_pos(scaled(210), scaled(BAR_H))     # 贴到右下角
            else:
                x, y = self.root.winfo_x(), self.root.winfo_y()
            self.root.geometry('%dx%d+%d+%d' % (scaled(210), scaled(BAR_H), x, y))
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
        self.close_preview()         # 角落预览跟着一起收
        self.save()
        self.set_num_hint(False)     # 面板藏起来时，Ctrl 的 KeyRelease 可能收不到
        if self.st.get('close_action') == 'quit':
            self.quit_app()
            return
        self.root.withdraw()
        self.hidden = True
        self._user_pulled = False          # 面板已收起 → 撤销「主动呼出」，回到可被全屏抑制的状态
        self.sync_topmost()
        if not self._told_tray:
            self._told_tray = True
            self.hw.balloon('ClawBoard 还在后台运行',
                            '面板已隐藏。点托盘图标或按 %s 叫回来；'
                            '要彻底退出：右键托盘图标 → 退出'
                            % (self.st.get('hotkey', 'ctrl+shift+v').upper()))

    def reset_position(self, mon=None):
        """应急：把面板拉回**主屏**右下角（托盘菜单与热键唤起都会自动兜底）。

        mon 给定时改放到该显示器右下角 —— 供 ensure_onscreen 把跑出屏幕的窗口
        拉到**离它最近**的显示器用。用户主动重置（无参：托盘菜单 command / 热键）
        仍固定回主屏：语义明确、可预期，符合「救命重置」的直觉。
        """
        w, h = 340, 480
        _, _, r, b = mon or self.primary_monitor()
        self.root.geometry('%dx%d+%d+%d' % (w, h, r - w - 14, b - h - 62))
        self._user_pulled = True           # 用户主动找回面板 → 视为主动呼出
        self.root.deiconify()
        self.sync_topmost()
        self.root.lift()
        self.hidden = False
        self._edge_hidden = False
        self._edge_tick = 0
        self.render()
        self.tip('面板位置已重置')

    def ensure_onscreen(self):
        """窗口跑出屏幕时自动拉回（避免"点了没反应"），目标为**离窗口最近**的显示器。

        用 visible_ratio 判定：窗口跨在两屏之间时整个窗口都在虚拟桌面内 → 1.0，
        不再被误判成跑出屏幕（旧实现取各屏交集最大值，跨屏恒 < 1（50/50 骑跨才是 0.5）
        → 必被拉回主屏）。
        只有真的出屏（比例 < 0.999）才拉回，且拉到最近的显示器而不是固定主屏。
        """
        m = re.match(r'^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$', self.root.geometry())
        if m:
            w, h, x, y = (int(v) for v in m.groups())
            if visible_ratio(x, y, w, h) < 0.999:      # 跨屏 = 1.0（不拉回）
                self.reset_position(self._nearest_monitor(x, y, w, h))
                return True
        return False

    def toggle_show(self):
        if self.hidden:
            self.hidden = False
            self._user_pulled = True       # 热键/托盘呼出 → 全屏时也保持置顶可见
            self.root.deiconify()
            self.sync_topmost()
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
