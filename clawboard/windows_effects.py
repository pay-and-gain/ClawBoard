# -*- coding: utf-8 -*-
"""窗口材质适配：圆角与 Acrylic；系统不支持时返回 False。"""
import ctypes
from ctypes import wintypes

from clawboard.windows_geometry import top_hwnd

from clawboard.windows_api import (
    _dwm, ACCENTPOLICY, ACCENT_DISABLED, ACCENT_ENABLE_ACRYLICBLURBEHIND,
    DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_DONOTROUND, DWMWCP_ROUND, WCA_ACCENT_POLICY,
    WINCOMPATTRDATA, u32,
)


# ---------------- 窗口外观：圆角 + Acrylic 毛玻璃 ----------------
# 实验结论（本机 Win11 实测）：
#   · 圆角 (DWMWA_WINDOW_CORNER_PREFERENCE=33) —— 有效，方角变圆角
#   · Acrylic (SetWindowCompositionAttribute) —— 有效，窗口有毛玻璃底
#   · Mica (DWMWA_SYSTEMBACKDROP_TYPE=38) —— 无效：overrideredirect 是 WS_POPUP，
#     系统不给 Mica 背景（API 返回成功但视觉无变化）
#   · 深色标题栏 —— 无意义（无边框窗口没有标题栏）
# 重要：Tk 的 winfo_id() 是**子窗口**，DWM 属性必须设在**顶层窗口**上，
#       对子窗口调用会返回 0x80070006（句柄无效）。

def set_rounded(root, on=True):
    """窗口圆角。返回是否成功（老系统不支持时静默失败）。"""
    try:
        v = ctypes.c_int(DWMWCP_ROUND if on else DWMWCP_DONOTROUND)
        hr = _dwm.DwmSetWindowAttribute(
            wintypes.HWND(top_hwnd(root)),
            ctypes.c_uint(DWMWA_WINDOW_CORNER_PREFERENCE),
            ctypes.byref(v), ctypes.sizeof(v))
        return hr == 0
    except Exception:
        return False

def set_acrylic(root, on=True, color=0xB0252831):
    """Acrylic 毛玻璃背景。

    color 是 0xAABBGGRR（Alpha 在前、且是 BGR 顺序）。不透明窗口下只在外围
    间隙露出模糊底；把窗口 -alpha 调低会整体变透（实测过 0.88 会太透，不建议）。
    """
    try:
        accent = ACCENTPOLICY()
        accent.AccentState = ACCENT_ENABLE_ACRYLICBLURBEHIND if on else ACCENT_DISABLED
        accent.AccentFlags = 2
        accent.GradientColor = color
        accent.AnimationId = 0
        data = WINCOMPATTRDATA()
        data.Attribute = WCA_ACCENT_POLICY
        data.Data = ctypes.pointer(accent)
        data.SizeOfData = ctypes.sizeof(accent)
        return bool(u32.SetWindowCompositionAttribute(
            wintypes.HWND(top_hwnd(root)), ctypes.byref(data)))
    except Exception:
        return False

def apply_window_effects(root, rounded=True, frosted=True, frosted_color=0xB0252831):
    """一次性应用窗口外观开关（圆角 + 毛玻璃）。返回 (圆角成功, 毛玻璃成功)。"""
    return (set_rounded(root, rounded), set_acrylic(root, frosted, frosted_color))
