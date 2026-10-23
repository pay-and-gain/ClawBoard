# -*- coding: utf-8 -*-
"""显示器和窗口几何：矩形、全屏判定与顶层 HWND 解析。"""
import ctypes
from ctypes import wintypes

from clawboard.windows_api import (
    GWL_STYLE, MONITORENUMPROC, MONITORINFO, MONITOR_DEFAULTTONEAREST, WS_CAPTION, u32,
)


def window_rect(hwnd):
    """窗口在屏幕上的矩形 (left, top, right, bottom)，物理坐标。"""
    hwnd = int(hwnd or 0)
    if not hwnd:
        return None
    r = wintypes.RECT()
    try:
        if u32.GetWindowRect(hwnd, ctypes.byref(r)):
            return (r.left, r.top, r.right, r.bottom)
    except Exception:
        pass
    return None

def rects_overlap(a, b):
    """两个矩形是否相交（含边界）。a/b 都是 (left, top, right, bottom)。"""
    ax, ay, ar, ab = a
    bx, by, br, bb = b
    return not (ar <= bx or br <= ax or ab <= by or bb <= ay)

# 桌面 / Shell 窗口本来就铺满整屏，但绝不是「全屏程序」，必须排除；否则桌面上
# 会永远被判成全屏。Shell_TrayWnd/Shell_SecondaryTrayWnd 是任务栏（本就不满屏），一并排除。
_DESKTOP_CLASSES = ('progman', 'workerw', 'shell_traywnd', 'shell_secondarytraywnd')

def class_name_of(hwnd):
    """窗口类名（小写）。取不到返回 ''。"""
    try:
        buf = ctypes.create_unicode_buffer(256)
        u32.GetClassNameW(wintypes.HWND(int(hwnd or 0)), buf, 256)
        return (buf.value or '').lower()
    except Exception:
        return ''

def monitor_rect_of(hwnd):
    """窗口**所在显示器**的完整矩形 (left, top, right, bottom)，物理像素。

    必须用 MonitorFromWindow 取窗口所在的那台显示器 —— 本机双屏 + 主屏 125%，
    拿主屏尺寸去比副屏上的窗口会直接判错。
    """
    hwnd = int(hwnd or 0)
    if not hwnd:
        return None
    try:
        hmon = u32.MonitorFromWindow(wintypes.HWND(hwnd), MONITOR_DEFAULTTONEAREST)
        if not hmon:
            return None
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if u32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            r = mi.rcMonitor
            return (r.left, r.top, r.right, r.bottom)
    except Exception:
        pass
    return None

def rect_covers(win_rect, mon_rect, tol=2):
    """窗口矩形是否覆盖整个显示器矩形（容差 tol 像素，容忍边框 / 取整误差）。"""
    if not win_rect or not mon_rect:
        return False
    wl, wt, wr, wb = win_rect
    ml, mt, mr, mb = mon_rect
    return (wl <= ml + tol and wt <= mt + tol and
            wr >= mr - tol and wb >= mb - tol)

def is_zoomed(hwnd):
    """窗口是否处于「最大化」（WS_MAXIMIZE）。取不到当 False。"""
    try:
        return bool(u32.IsZoomed(wintypes.HWND(int(hwnd or 0))))
    except Exception:
        return False

def has_caption(hwnd):
    """窗口是否有标题栏（WS_CAPTION 位）。取不到当 False。"""
    try:
        style = u32.GetWindowLongW(wintypes.HWND(int(hwnd or 0)), GWL_STYLE)
    except Exception:
        return False
    return bool(style & WS_CAPTION)

def is_fullscreen_window(hwnd, self_hwnd=0):
    """窗口是否「全屏」覆盖了它所在显示器的整个画面。

    用于「全屏程序前台时面板不再置顶」。排除三类：句柄 0 / 面板自己 / 桌面与 Shell。
    另排除「有标题栏的最大化窗口」—— 那不是全屏程序（见下）。

    坐标系：进程启动时已声明 per-monitor DPI 感知（init_dpi_awareness →
    SetProcessDpiAwareness(2)），因此 GetWindowRect 与 GetMonitorInfoW 返回的都是
    **物理像素**，可直接比较，不需要再乘 / 除任何缩放系数（这正是本机双屏 + 主屏
    125% 下不引入 1/缩放 偏差的关键）。

    为什么要「IsZoomed 且有标题栏」这条额外排除：当用户**开启任务栏自动隐藏**时，
    普通最大化窗口的 `rcWork == rcMonitor`，它的矩形会**等于整个显示器** —— 几何上
    与真全屏无法区分，只能靠窗口状态来分。三类真全屏都不会命中该排除：独占全屏与
    F11 式全屏 IsZoomed=False；无边框窗口化全屏即便 IsZoomed 也没有 WS_CAPTION。
    """
    hwnd = int(hwnd or 0)
    if not hwnd:
        return False
    if self_hwnd and hwnd == int(self_hwnd):
        return False
    if class_name_of(hwnd).lower() in _DESKTOP_CLASSES:
        return False
    if not rect_covers(window_rect(hwnd), monitor_rect_of(hwnd), 2):
        return False
    if is_zoomed(hwnd) and has_caption(hwnd):
        return False
    return True

def monitors():
    """列出所有显示器的矩形（多显示器下 winfo_screenwidth 只给主屏，不够用）"""
    out = []

    @MONITORENUMPROC
    def cb(hmon, hdc, lprc, lp):
        r = lprc.contents
        out.append((r.left, r.top, r.right, r.bottom))
        return True
    try:
        u32.EnumDisplayMonitors(None, None, cb, 0)
    except Exception:
        pass
    if not out:
        out = [(0, 0, 1920, 1080)]
    return out

def visible_ratio(x, y, w, h):
    """窗口与**所有**显示器的可见交集**之和**占自身面积的比例（上限 1.0）。

    docstring 一直这么写，但旧实现取的是「各显示器交集比例的最大值」——
    窗口跨在两屏之间时按单屏最多只能算到 **< 1**（恰好 50/50 骑跨才是 0.5，偏向一侧时
    更大但仍 < 1），于是被 ensure_onscreen 误判成「跑出屏幕」而拉回主屏（跨过去了下次
    呼出又被拽回来）。改成求和才与文档一致：
    跨屏（整个窗口落在虚拟桌面内）→ 1.0；完全出屏 → 0；单屏内 → 1.0。
    多显示器矩形互不重叠时和自然 ≤ 1.0，重叠时 clamp 到 1.0 以防 > 1。
    """
    if w <= 0 or h <= 0:
        return 0.0
    total = 0.0
    for (l, t, r, b) in monitors():
        iw = min(x + w, r) - max(x, l)
        ih = min(y + h, b) - max(y, t)
        if iw > 0 and ih > 0:
            total += (iw * ih) / float(w * h)
    return min(total, 1.0)

def top_hwnd(root):
    """取顶层窗口句柄。

    Tk 的 winfo_id() 返回的是内部子窗口；DWM / 合成属性必须作用在顶层窗口上，
    否则调用返回 0x80070006（ERROR_INVALID_HANDLE）。
    """
    try:
        h = int(root.winfo_id())
        p = u32.GetParent(wintypes.HWND(h))
        return int(p) if p else h
    except Exception:
        return 0
