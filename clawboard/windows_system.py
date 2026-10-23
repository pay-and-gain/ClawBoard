# -*- coding: utf-8 -*-
"""系统服务：进程来源、资源统计、DPI、单实例与当前用户自启动。"""
import ctypes
import os
import sys
import time
import winreg
from ctypes import wintypes

from clawboard.config import APP_NAME, BASE_DIR
from clawboard.windows_geometry import top_hwnd

from clawboard.windows_api import (
    PROCESS_MEMORY_COUNTERS, PROCESS_QUERY_LIMITED_INFORMATION, gdi32, k32, psapi,
    shcore, u32,
)


TITLE_BAD_WORDS = ('密码', '银行卡', '登录', 'password', 'bank')

def mem_mb():
    c = PROCESS_MEMORY_COUNTERS()
    c.cb = ctypes.sizeof(c)
    if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
        return c.WorkingSetSize / 1048576.0
    return -1.0

def cpu_ms():
    a, b, c, d = (wintypes.FILETIME(), wintypes.FILETIME(),
                  wintypes.FILETIME(), wintypes.FILETIME())
    if k32.GetProcessTimes(k32.GetCurrentProcess(), ctypes.byref(a),
                           ctypes.byref(b), ctypes.byref(c), ctypes.byref(d)):
        t = ((c.dwHighDateTime << 32) + c.dwLowDateTime +
             (d.dwHighDateTime << 32) + d.dwLowDateTime)
        return t / 10000.0
    return -1.0

def proc_name_of(hwnd):
    pid = wintypes.DWORD(0)
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return 'unknown'
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h:
        return 'unknown'
    try:
        buf = ctypes.create_unicode_buffer(512)
        size = wintypes.DWORD(512)
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            base = os.path.basename(buf.value)
            return os.path.splitext(base)[0] or 'unknown'
    finally:
        k32.CloseHandle(h)
    return 'unknown'

def window_title_of(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    u32.GetWindowTextW(hwnd, buf, 512)
    t = (buf.value or '').strip()
    low = t.lower()
    if any(w in low for w in TITLE_BAD_WORDS):
        return None          # 含敏感词的窗口标题一律不记录
    return t or None

def system_dpi():
    """真实系统 DPI（96/120/144…），不依赖 Tk scaling 的初始化时机。

    frozen 环境下 Tk 的 tk scaling 会延迟到窗口映射后才反映真实 DPI，
    直接读它会拿到默认 1.333、把 125% 缩放误判成 100%。所以改用 Win32 直读。
    """
    try:
        dpi = u32.GetDpiForSystem()   # Win10 1607+ / Win11
        if dpi:
            return int(dpi)
    except Exception:
        pass
    try:
        hdc = u32.GetDC(None)
        if hdc:
            try:
                dpi = gdi32.GetDeviceCaps(hdc, 88)   # LOGPIXELSX
                if dpi:
                    return int(dpi)
            finally:
                u32.ReleaseDC(None, hdc)
    except Exception:
        pass
    return 96

def dpi_scale(root):
    """当前屏幕相对 100% 的缩放系数（96 DPI=1.0，120 DPI=1.25）。

    优先读取窗口所在屏的 DPI；窗口尚未建立或旧系统不支持时才回退系统 DPI。
    不读已被 UI 缩放改写的 tk scaling，否则会双重缩放。
    """
    try:
        hwnd = top_hwnd(root)
        dpi = u32.GetDpiForWindow(hwnd)
        if 48 <= dpi <= 384:
            return dpi / 96.0
    except Exception:
        pass
    k = system_dpi() / 96.0
    return k if 0.5 <= k <= 4.0 else 1.0

def capture_source(self_hwnd, delay_retry=True):
    """抓取当前前台进程名。竞态：抓到自己/空 → 延迟 50ms 重试一次"""
    for attempt in range(2):
        hwnd = u32.GetForegroundWindow()
        if hwnd and hwnd != self_hwnd:
            name = proc_name_of(hwnd)
            if name != 'unknown':
                return name, hwnd
        if attempt == 0 and delay_retry:
            time.sleep(0.05)
    return 'unknown', None

def init_dpi_awareness():
    """坑③唯一承载点：读窗口坐标/测量前必须先声明 DPI 感知。

    内部 SetProcessDpiAwareness(2) + try/except；`dpi_scale(root)` 也归本模块。
    约定：任何读取窗口几何/做屏幕测量的路径（main/--shot/--bench/测试脚本）都复用本函数。
    """
    try:
        if shcore is not None:
            shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

MUTEX = [None]

def single_instance():
    """互斥体：二次启动聚焦已有实例后退出"""
    MUTEX[0] = k32.CreateMutexW(None, True, 'ClawBoard_SingleInstance_Mutex')
    if ctypes.get_last_error() == 183:      # ERROR_ALREADY_EXISTS
        try:
            hwnd = u32.FindWindowW(None, APP_NAME)
            if hwnd:
                u32.ShowWindow(hwnd, 9)     # SW_RESTORE
                u32.SetForegroundWindow(hwnd)
        except Exception:
            pass
        return False
    return True

# ---------------- 开机自启（只写当前用户注册表，可逆） ----------------
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'

RUN_NAME = 'ClawBoard'

def autostart_cmd():
    """frozen 时写 exe 自身；脚本运行时写 pythonw + 脚本路径"""
    if getattr(sys, 'frozen', False):
        return '"%s"' % sys.executable
    py = sys.executable.replace('python.exe', 'pythonw.exe')
    if not os.path.exists(py):
        py = sys.executable
    return '"%s" "%s"' % (py, os.path.join(BASE_DIR, 'ClawBoard.py'))

def get_autostart():
    """读取注册表真实状态，不信任配置文件"""
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY)
        v, _ = winreg.QueryValueEx(k, RUN_NAME)
        winreg.CloseKey(k)
        return True, v
    except Exception:
        return False, ''

def set_autostart(on):
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
        if on:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, autostart_cmd())
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except Exception:
                pass
        winreg.CloseKey(k)
        return True
    except Exception:
        return False
