# -*- coding: utf-8 -*-
"""
ClawBoard - Windows 悬浮剪切板 & 常用语面板
零第三方依赖：Python 标准库 tkinter + ctypes(Win32)
适配 Windows 10 / 11

模块分区：
  1. 主题与常量
  2. Win32 声明（剪贴板 / 热键 / 托盘 / 互斥 / 内存统计）
  3. 剪贴板读写 + 敏感内容识别
  4. 图标生成（运行时生成 ClawBoard.ico，不依赖外部资源）
  5. 隐藏消息窗口（热键 + 托盘回调，独立线程）
  6. 通用控件与弹窗
  7. 虚拟滚动列表（固定行高窗口化渲染）
  8. 主程序 ClawBoard
  9. bench 压测入口 / main
"""
import os
import re
import sys
import json
import time
import ctypes
import threading
import traceback
import subprocess
import html as _html
import fnmatch
import tkinter as tk
import winreg
from ctypes import wintypes

APP_NAME = 'ClawBoard'
APP_VER = '1.4.0'

if getattr(sys, 'frozen', False):
    # PyInstaller onefile：__file__ 指向临时解包目录，退出即销毁。
    # 数据文件必须落在 exe 旁边，否则每次退出历史全丢。
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, 'ClawBoard数据.json')
ICON_FILE = os.path.join(BASE_DIR, 'ClawBoard.ico')
CRASH_LOG = os.path.join(BASE_DIR, 'crash.log')

sys.path.insert(0, BASE_DIR)
import query as Q          # F3 查询解析器（独立模块，可单测）

TX = None                  # F4 变换模块延迟到首次打开变换窗口时再导入


def tx():
    """延迟导入 transform：启动时不必拉起 hashlib/base64/urllib"""
    global TX
    if TX is None:
        import transform
        TX = transform
    return TX

FONT = ('Microsoft YaHei UI', 9)
FONT_B = ('Microsoft YaHei UI', 9, 'bold')
FONT_SM = ('Microsoft YaHei UI', 8)
FONT_TITLE = ('Microsoft YaHei UI', 10, 'bold')

ITEM_H = 52          # 虚拟列表固定行高
WHEEL_LINES = 3      # 滚轮一格滚几行（Windows 惯例是 3）
MAX_TEXT = 200000    # 单条文本入库上限（字符）
NO_SAVE = False      # --bench 压测时置 True：压测实例绝不把任何东西写回存档
                     # （曾经漏了这条，压测把「热键」也写进了存档）

# ---------------- 1. 主题 ----------------
DARK = dict(bg='#1e2027', panel='#252831', card='#2c303b', card_h='#39404f',
            card_s='#33465f', card_m='#3d4f6b', fg='#e6e8ee', fg2='#9aa0ad',
            acc='#4f8cff', acc2='#2f6fe0', line='#333844', danger='#e05c5c')
LIGHT = dict(bg='#f4f5f8', panel='#e9ebf0', card='#ffffff', card_h='#eef1f7',
             card_s='#dbe7ff', card_m='#e3edff', fg='#1f2430', fg2='#6b7280',
             acc='#2563eb', acc2='#1d4ed8', line='#d6dae3', danger='#c0392b')
T = dict(DARK)


def set_theme(name):
    T.clear()
    T.update(DARK if name == 'dark' else LIGHT)


# ---------------- 2. Win32 ----------------
u32 = ctypes.WinDLL('user32', use_last_error=True)
k32 = ctypes.WinDLL('kernel32', use_last_error=True)
psapi = ctypes.WinDLL('psapi')

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
HWND_MESSAGE = wintypes.HWND(-3)
WM_HOTKEY = 0x0312
WM_USER = 0x0400
WM_TRAY = WM_USER + 1
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_DESTROY = 0x0002
WM_APP_REG = WM_USER + 2      # 请求注册热键（必须在消息线程内执行）
WM_APP_UNREG = WM_USER + 3
NIF_INFO = 0x00000010
NIIF_INFO = 0x00000001
MOD_ALT, MOD_CONTROL, MOD_SHIFT = 0x0001, 0x0002, 0x0004
VK_V = 0x56
VK_CONTROL = 0x11
VK_SHIFT, VK_MENU = 0x10, 0x12          # Shift / Alt
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
# Windows 官方的「别把我记进剪贴板历史」标记，KeePassXC / 1Password / Bitwarden 都会设置它。
# 取自 Ditto src/Clip.cpp:364 与 :400（ExcludeClipboardContentFromMonitorProcessing、
# CanIncludeInClipboardHistory=0）——这是剪贴板工具该守的礼貌，比任何敏感词正则都准。
CF_NAME_EXCLUDE = 'ExcludeClipboardContentFromMonitorProcessing'
CF_NAME_INCLUDE_HISTORY = 'CanIncludeInClipboardHistory'
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x1, 0x2, 0x4
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)

u32.GetClipboardSequenceNumber.restype = wintypes.DWORD
u32.GetClipboardSequenceNumber.argtypes = []
u32.OpenClipboard.argtypes = [wintypes.HWND]
u32.OpenClipboard.restype = wintypes.BOOL
u32.CloseClipboard.restype = wintypes.BOOL
u32.EmptyClipboard.restype = wintypes.BOOL
u32.GetClipboardData.argtypes = [wintypes.UINT]
u32.GetClipboardData.restype = wintypes.HANDLE
u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
u32.SetClipboardData.restype = wintypes.HANDLE
u32.GetForegroundWindow.restype = wintypes.HWND
u32.SetForegroundWindow.argtypes = [wintypes.HWND]
u32.SetForegroundWindow.restype = wintypes.BOOL
u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
u32.ShowWindow.restype = wintypes.BOOL
u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u32.FindWindowW.restype = wintypes.HWND
u32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
u32.RegisterHotKey.restype = wintypes.BOOL
u32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
u32.UnregisterHotKey.restype = wintypes.BOOL
u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u32.PostMessageW.restype = wintypes.BOOL
u32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
u32.GetCursorPos.restype = wintypes.BOOL

MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                     ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
u32.EnumDisplayMonitors.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                   MONITORENUMPROC, wintypes.LPARAM]
u32.EnumDisplayMonitors.restype = wintypes.BOOL
k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
k32.CreateMutexW.restype = wintypes.HANDLE
u32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
u32.CreateWindowExW.restype = wintypes.HWND
u32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u32.DefWindowProcW.restype = LRESULT
u32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                            wintypes.UINT, wintypes.UINT]
u32.GetMessageW.restype = wintypes.BOOL
u32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
u32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
u32.PostQuitMessage.argtypes = [ctypes.c_int]
u32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                           ctypes.c_int, ctypes.c_int, wintypes.UINT]
u32.LoadImageW.restype = wintypes.HANDLE
u32.DestroyIcon.argtypes = [wintypes.HICON]
u32.DestroyIcon.restype = wintypes.BOOL
sh32 = ctypes.WinDLL('shell32', use_last_error=True)
sh32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.c_void_p]
sh32.Shell_NotifyIconW.restype = wintypes.BOOL
u32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, wintypes.DWORD, ctypes.c_ulong]
u32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
u32.RegisterClipboardFormatW.restype = wintypes.UINT
u32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
u32.IsClipboardFormatAvailable.restype = wintypes.BOOL
u32.GetAsyncKeyState.argtypes = [ctypes.c_int]
u32.GetAsyncKeyState.restype = ctypes.c_short
u32.SendInput.argtypes = [wintypes.UINT, ctypes.c_void_p, ctypes.c_int]
u32.SendInput.restype = wintypes.UINT
u32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
u32.MapVirtualKeyW.restype = wintypes.UINT
u32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
u32.AttachThreadInput.restype = wintypes.BOOL
u32.BringWindowToTop.argtypes = [wintypes.HWND]
u32.BringWindowToTop.restype = wintypes.BOOL
u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
u32.GetWindowThreadProcessId.restype = wintypes.DWORD
k32.GetCurrentThreadId.restype = wintypes.DWORD

k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
k32.GlobalAlloc.restype = wintypes.HANDLE
k32.GlobalLock.argtypes = [wintypes.HANDLE]
k32.GlobalLock.restype = ctypes.c_void_p
k32.GlobalUnlock.argtypes = [wintypes.HANDLE]
k32.GlobalUnlock.restype = wintypes.BOOL
k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
k32.GetModuleHandleW.restype = wintypes.HMODULE
k32.GetCurrentProcess.restype = wintypes.HANDLE
k32.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME),
                                ctypes.POINTER(wintypes.FILETIME),
                                ctypes.POINTER(wintypes.FILETIME),
                                ctypes.POINTER(wintypes.FILETIME)]
k32.GetProcessTimes.restype = wintypes.BOOL


class WNDCLASS(ctypes.Structure):
    _fields_ = [('style', wintypes.UINT), ('lpfnWndProc', WNDPROC),
                ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int),
                ('hInstance', wintypes.HINSTANCE), ('hIcon', wintypes.HICON),
                ('hCursor', wintypes.HANDLE), ('hbrBackground', wintypes.HANDLE),
                ('lpszMenuName', wintypes.LPCWSTR), ('lpszClassName', wintypes.LPCWSTR)]


u32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
u32.RegisterClassW.restype = wintypes.ATOM


class NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('hWnd', wintypes.HWND), ('uID', wintypes.UINT),
                ('uFlags', wintypes.UINT), ('uCallbackMessage', wintypes.UINT),
                ('hIcon', wintypes.HICON), ('szTip', wintypes.WCHAR * 128),
                ('dwState', wintypes.DWORD), ('dwStateMask', wintypes.DWORD),
                ('szInfo', wintypes.WCHAR * 256), ('uTimeout', wintypes.UINT),
                ('uVersion', wintypes.UINT), ('szInfoTitle', wintypes.WCHAR * 64),
                ('dwInfoFlags', wintypes.DWORD), ('guidItem', ctypes.c_byte * 16),
                ('hBalloonIcon', wintypes.HICON)]


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
                ('QuotaPagedPoolUsage', ctypes.c_size_t),
                ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)]


psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE,
                                       ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                                       wintypes.DWORD]
psapi.GetProcessMemoryInfo.restype = wintypes.BOOL


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


# ---------------- 3. 剪贴板 + 敏感内容 ----------------
LAST_SEQ = 0


def clip_seq():
    try:
        return u32.GetClipboardSequenceNumber()
    except Exception:
        return 0


def clip_read():
    if not u32.OpenClipboard(None):
        return None
    try:
        h = u32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = k32.GlobalLock(h)
        if not p:
            return None
        try:
            return ctypes.wstring_at(p)
        finally:
            k32.GlobalUnlock(h)
    finally:
        u32.CloseClipboard()


def clip_write(text):
    """写入剪贴板。成功后同步 LAST_SEQ，避免自己的回写被监听重复入库。"""
    global LAST_SEQ
    data = text.encode('utf-16-le') + b'\x00\x00'
    if not u32.OpenClipboard(None):
        return False
    try:
        u32.EmptyClipboard()
        h = k32.GlobalAlloc(GMEM_MOVEABLE, len(data) + 2)
        if not h:
            return False
        p = k32.GlobalLock(h)
        if not p:
            return False
        ctypes.memmove(p, data, len(data))
        k32.GlobalUnlock(h)
        if not u32.SetClipboardData(CF_UNICODETEXT, h):
            return False
    finally:
        u32.CloseClipboard()
    LAST_SEQ = clip_seq()
    return True


# ---- 发按键：SendInput + 扫描码（取自 Ditto src/SendKeys.cpp:237 / :326）----

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD),
                ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD),
                ('dwExtraInfo', ctypes.c_void_p)]


class MOUSEINPUT(ctypes.Structure):
    """必须原样写出来：INPUT 是联合体，大小取最大成员（64 位下 MOUSEINPUT=32 字节）。
    少写了它、用 byte*24 顶替，sizeof(INPUT) 就是 32 而不是 40，SendInput 会直接失败。"""
    _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG),
                ('mouseData', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
                ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_void_p)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [('uMsg', wintypes.DWORD), ('wParamL', wintypes.WORD),
                ('wParamH', wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [('ki', KEYBDINPUT), ('mi', MOUSEINPUT), ('hi', HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [('type', wintypes.DWORD), ('u', _INPUTUNION)]


def _kbd(vk, up=False):
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.u.ki.wVk = vk
    inp.u.ki.wScan = u32.MapVirtualKeyW(vk, 0)      # 带扫描码，兼容性更好
    inp.u.ki.dwFlags = KEYEVENTF_KEYUP if up else 0
    return inp


def send_key(vk, up=False, gap=0.01):
    try:
        inp = _kbd(vk, up)
        u32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    except Exception:
        return
    if gap:
        time.sleep(gap)


MODIFIER_VKS = (VK_CONTROL, VK_SHIFT, VK_MENU, 0x5B, 0x5C)   # Ctrl/Shift/Alt/LWin/RWin


def all_keys_up(gap=0.005):
    """发键前先抬起所有还按着的修饰键。
    Ditto SendKeys.cpp:237 的 AllKeysUp：用户按着 Ctrl 唤起面板时，残留的 Ctrl
    会把我们的 Ctrl+V 变成 Ctrl+Ctrl+V，目标程序收到的是裸 V，粘贴就"失灵"了。"""
    for vk in MODIFIER_VKS:
        try:
            if u32.GetAsyncKeyState(vk) & 0x8000:
                send_key(vk, up=True, gap=gap)
        except Exception:
            pass


def send_ctrl_v():
    """Ctrl+V。改用 SendInput：一次一个事件、带扫描码，比已废弃的 keybd_event 可靠"""
    all_keys_up()
    send_key(VK_CONTROL, gap=0.008)
    send_key(VK_V, gap=0.012)
    send_key(VK_V, up=True, gap=0.008)
    send_key(VK_CONTROL, up=True, gap=0)


def force_foreground(hwnd, timeout=0.35):
    """把目标窗口抢回前台，并且**等它真的拿到焦点**才返回。
    Ditto ExternalWindowTracker.cpp:187 的 AttachThreadInput 技巧：Windows 默认禁止
    后台进程抢焦点（前台锁定），附加到当前前台线程的输入队列后就允许了；
    :119 的 WaitForActiveWnd 用 Sleep(0) 轮询等焦点真的切过去，比固定 sleep 可靠。"""
    hwnd = int(hwnd or 0)
    if not hwnd:
        return False
    if u32.GetForegroundWindow() == hwnd:
        return True
    attached = False
    fg_tid = 0
    me = k32.GetCurrentThreadId()
    try:
        fg = u32.GetForegroundWindow()
        fg_tid = u32.GetWindowThreadProcessId(fg, None) if fg else 0
        if fg_tid and fg_tid != me:
            attached = bool(u32.AttachThreadInput(fg_tid, me, True))
        u32.BringWindowToTop(wintypes.HWND(hwnd))
        u32.SetForegroundWindow(wintypes.HWND(hwnd))
    except Exception:
        pass
    finally:
        if attached:
            try:
                u32.AttachThreadInput(fg_tid, k32.GetCurrentThreadId(), False)
            except Exception:
                pass
    end = time.time() + timeout
    while time.time() < end:
        if u32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.01)
    return u32.GetForegroundWindow() == hwnd


# ---- 隐私标记：Windows 让应用声明「这条别记进历史」----
_priv_fmt_cache = {}


def _clip_fmt_id(name):
    if name not in _priv_fmt_cache:
        try:
            _priv_fmt_cache[name] = int(u32.RegisterClipboardFormatW(name) or 0)
        except Exception:
            _priv_fmt_cache[name] = 0
    return _priv_fmt_cache[name]


def clip_is_private():
    """剪贴板上带着官方「不要记录」标记时返回 True。
    CanIncludeInClipboardHistory 存在且前 4 字节为 0，或
    ExcludeClipboardContentFromMonitorProcessing 存在即忽略 —— 两项都是 Windows 给
    密码管理器用的信号（Ditto src/Clip.cpp:364 与 :400），比敏感词正则准得多。"""
    ex = _clip_fmt_id(CF_NAME_EXCLUDE)
    inc = _clip_fmt_id(CF_NAME_INCLUDE_HISTORY)
    if not ex and not inc:
        return False
    if not u32.OpenClipboard(None):
        return False
    try:
        if ex and u32.IsClipboardFormatAvailable(ex):
            return True
        if inc and u32.IsClipboardFormatAvailable(inc):
            h = u32.GetClipboardData(inc)
            if h:
                p = k32.GlobalLock(h)
                if p:
                    try:
                        if ctypes.c_uint32.from_address(p).value == 0:
                            return True
                    finally:
                        k32.GlobalUnlock(h)
    except Exception:
        return False
    finally:
        u32.CloseClipboard()
    return False


LAST_SEQ = clip_seq()

SENS_PATTERNS = [
    ('身份证', re.compile(r'(?<!\d)\d{17}[\dXx](?!\d)')),
    ('银行卡', re.compile(r'(?<!\d)\d{16,19}(?!\d)')),
    ('手机号', re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)')),
    ('邮箱', re.compile(r'[\w.+-]+@[\w-]+\.[\w.]{2,}')),
    ('Token', re.compile(r'(?:sk-|ghp_|xox[baprs]-|Bearer\s+)[A-Za-z0-9_\-]{8,}')),
    ('密码', re.compile(r'(?i)(password|passwd|pwd|密码|口令)\s*[:：=]\s*\S{4,}')),
]


def scan_sensitive(text):
    try:
        return [name for name, pat in SENS_PATTERNS if pat.search(text or '')]
    except Exception:
        return []


def mask_text(text, hits):
    def rep(m):
        s = m.group(0)
        return s[:3] + '*' * max(3, len(s) - 5) + s[-2:]
    out = text
    for name, pat in SENS_PATTERNS:
        if name in hits:
            out = pat.sub(rep, out)
    return out


# ---------------- 时间 / 来源 / 迁移（M0·F0·F1） ----------------
SCHEMA_VERSION = 3


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
    """窗口与所有显示器的可见交集占自身面积的比例"""
    best = 0.0
    for (l, t, r, b) in monitors():
        iw = min(x + w, r) - max(x, l)
        ih = min(y + h, b) - max(y, t)
        if iw > 0 and ih > 0:
            best = max(best, (iw * ih) / float(w * h))
    return best


def now_ms():
    return int(time.time() * 1000)


def rel_time(ms, estimated=False):
    """相对时间文案：<1min 刚刚 / <60min N 分钟前 / 今天 HH:MM / 昨天 / 更早"""
    if not ms:
        return '未知时间'
    pre = '约 ' if estimated else ''
    now = now_ms()
    if ms > now + 60000:
        return pre + '时间异常'
    diff = (now - ms) / 1000.0
    if diff < 60:
        return pre + '刚刚'
    if diff < 3600:
        return pre + '%d 分钟前' % int(diff / 60)
    lt = time.localtime(ms / 1000.0)
    n = time.localtime()
    if lt.tm_year == n.tm_year and lt.tm_yday == n.tm_yday:
        return pre + time.strftime('%H:%M', lt)
    if (n.tm_yday - lt.tm_yday) == 1 and lt.tm_year == n.tm_year:
        return pre + '昨天 ' + time.strftime('%H:%M', lt)
    return pre + time.strftime('%m-%d %H:%M', lt)


def full_time(ms):
    if not ms:
        return '—'
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ms / 1000.0))


k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.OpenProcess.restype = wintypes.HANDLE
k32.CloseHandle.argtypes = [wintypes.HANDLE]
k32.CloseHandle.restype = wintypes.BOOL
k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                           wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
k32.QueryFullProcessImageNameW.restype = wintypes.BOOL
u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.GetWindowTextW.restype = ctypes.c_int

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TITLE_BAD_WORDS = ('密码', '银行卡', '登录', 'password', 'bank')


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


def parse_ignore_list(raw):
    """把忽略名单文本拆成通配模式列表。
    没写通配符的按「包含」处理（keepass → *keepass*），对齐 Ditto
    ClipboardViewer.cpp:345 的 WildMatch 语义，但 * / ? 交给 fnmatch，不自己造轮子。"""
    out = []
    for p in re.split(r'[,;\n、\r]', raw or ''):
        p = p.strip().lower()
        if not p:
            continue
        if not any(ch in p for ch in '*?'):
            p = '*' + p + '*'
        out.append(p)
    return out


def match_ignore(app_name, title, apps_raw, titles_raw):
    """命中忽略规则则返回规则描述，否则 None。
    应用名按通配匹配、窗口标题按正则匹配（对齐 CopyQ predefinedcommands.cpp:151 —— 
    预设的「忽略标题含 Password 的窗口」就是这么一条 wndre 正则）。"""
    name = (app_name or '').lower()
    for pat in parse_ignore_list(apps_raw):
        if fnmatch.fnmatch(name, pat):
            return '应用 %s' % (pat.strip('*') or pat)
    t = title or ''
    for pat in re.split(r'[\n;\r]', titles_raw or ''):
        pat = pat.strip()
        if not pat:
            continue
        try:
            if re.search(pat, t, re.I):
                return '标题 /%s/' % pat
        except re.error:
            if pat.lower() in t.lower():
                return '标题 %s' % pat
    return None


def length_filtered(txt, lo, hi):
    """按长度上下限判断是否入库，返回提示语；None 表示放行。
    对应 PasteBar settingsStore.ts:285 的 clipTextMinLength / clipTextMaxLength ——
    一个滤噪声（单个字母、误触），一个挡超长（几 MB 的日志正文）。"""
    n = len(txt or '')
    if lo and n < lo:
        return '内容只有 %d 字符（下限 %d），按设置不入库' % (n, lo)
    if hi and n > hi:
        return '内容有 %d 字符（上限 %d），按设置不入库' % (n, hi)
    return None


def crop_items(items, lim):
    """裁剪到 lim 条：从最旧的一端删，但收藏项永不自动删。
    Ditto DatabaseUtilities.cpp:844 的 RemoveOldEntries 会跳过 lDontAutoDelete，
    CopyQ itemfactory.cpp:328 的 cropToSize 用 canDropItem 豁免置顶项 —— 同一个道理。"""
    if len(items) <= lim:
        return items
    return list(items[:lim]) + [x for x in items[lim:] if x.get('fav')]


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


def detect_content_type(text):
    """我们只监听 CF_UNICODETEXT，这里判定文本的形态用于徽章与 type: 过滤"""
    t = (text or '').strip()
    if not t:
        return 'empty'
    if re.match(r'^https?://\S+$', t) and ' ' not in t:
        return 'url'
    try:
        if (t.startswith('{') and t.endswith('}')) or (t.startswith('[') and t.endswith(']')):
            json.loads(t)
            return 'json'
    except Exception:
        pass
    if '\n' in t:
        return 'multiline'
    return 'text'


def byte_size(text):
    try:
        return len(text.encode('utf-8'))
    except Exception:
        return 0


def human_size(n):
    if n < 1024:
        return '%d B' % n
    if n < 1024 * 1024:
        return '%.1f KB' % (n / 1024.0)
    return '%.1f MB' % (n / 1048576.0)


def to_plain(text):
    """F6：剥成纯文本。<br>/<p>/<li>/表格 要变成换行或制表符，实体要解码"""
    s = text or ''
    if re.search(r'<\s*(br|p|div|li|tr|table|h[1-6]|td|th)', s, re.I):
        s = re.sub(r'<\s*br\s*/?\s*>', '\n', s, flags=re.I)
        s = re.sub(r'</\s*(p|div|li|tr|h[1-6])\s*>', '\n', s, flags=re.I)
        s = re.sub(r'</\s*t[dh]\s*>', '\t', s, flags=re.I)
        s = re.sub(r'<[^>]+>', '', s)
        s = _html.unescape(s)
    s = s.replace('\xa0', ' ')
    s = s.replace('\r\n', '\n').replace('\r', '\n')
    s = re.sub(r'[ \t]+\n', '\n', s)
    s = re.sub(r'\n{3,}', '\n\n', s)
    s = '\n'.join(x.rstrip() for x in s.split('\n'))
    return s.strip('\n')


def backup_data():
    """迁移前备份，返回备份路径（失败返回 None）"""
    if not os.path.exists(DATA_FILE):
        return None
    bak = DATA_FILE + '.bak'
    try:
        with open(DATA_FILE, 'rb') as a:
            with open(bak, 'wb') as b:
                b.write(a.read())
        return bak
    except Exception:
        return None


def migrate(d, note=None):
    """版本化迁移：1 → 2 → 3，幂等可重复执行"""
    v = d.get('schema_version', 1)
    if not isinstance(v, int):
        v = 1

    def pools():
        out = []
        if isinstance(d.get('clip'), list):
            out.append(d['clip'])
        for g in d.get('groups') or []:
            if isinstance(g, dict) and isinstance(g.get('items'), list):
                out.append(g['items'])
        return out

    if v < 2:
        # v1 → v2：补 created_at / seq，老数据没有真实时间戳，按倒序估算并标记
        seq = 0
        for pool in pools():
            for it in pool:
                if not isinstance(it, dict):
                    continue
                seq += 1
                if not it.get('created_at'):
                    it['created_at'] = now_ms() - seq * 1000
                    it.setdefault('is_estimated', 1)   # 老数据无时间戳 → 标记为估算
                it.setdefault('seq', seq)
        v = 2
    if v < 3:
        # v2 → v3：补 F0/F1/F2 全部字段
        for pool in pools():
            for it in pool:
                if not isinstance(it, dict):
                    continue
                it.setdefault('updated_at', it.get('created_at'))
                it.setdefault('last_used_at', None)
                it.setdefault('source_app', 'unknown')
                it.setdefault('source_title', None)
                it.setdefault('copy_count', 1)
                it.setdefault('fav', 0)
                it.setdefault('meta', None)
                if not it.get('content_type'):
                    it['content_type'] = detect_content_type(it.get('text', ''))
                if not it.get('content_size'):
                    it['content_size'] = byte_size(it.get('text', ''))
        v = 3
    d['schema_version'] = v
    return d


# ---------------- 4. 图标生成 ----------------
def make_ico(path, size=32):
    """纯 stdlib 生成 32x32 32bpp ICO：蓝底圆角 + 白色剪贴板"""
    w = h = size
    bg = (79, 140, 255, 255)
    white = (255, 255, 255, 255)
    px = [[(0, 0, 0, 0) for _ in range(w)] for _ in range(h)]
    r = 6
    corners = ((r, r), (w - 1 - r, r), (r, h - 1 - r), (w - 1 - r, h - 1 - r))
    for y in range(h):
        for x in range(w):
            inside = True
            for cx, cy in corners:
                if ((cx == r and x < r and y < r) or
                        (cx == w - 1 - r and x > w - 1 - r and y < r) or
                        (cy == h - 1 - r and x < r and y > h - 1 - r) or
                        (cx == w - 1 - r and cy == h - 1 - r and
                         x > w - 1 - r and y > h - 1 - r)):
                    if (x - cx) ** 2 + (y - cy) ** 2 > r * r:
                        inside = False
            if inside:
                px[y][x] = bg
    for y in range(7, 27):
        for x in range(9, 23):
            px[y][x] = white
    for y in range(5, 8):
        for x in range(12, 20):
            px[y][x] = white
    for y in (15, 18, 21):
        for x in range(11, 21):
            px[y][x] = bg
    xor = bytearray()
    for y in range(h - 1, -1, -1):
        for x in range(w):
            b, g, rr, a = px[y][x]
            xor += bytes((b, g, rr, a))
    and_mask = bytes(((w + 31) // 32) * 4 * h)
    dib = bytearray()
    dib += (40).to_bytes(4, 'little')
    dib += w.to_bytes(4, 'little', signed=True)
    dib += (h * 2).to_bytes(4, 'little', signed=True)
    dib += (1).to_bytes(2, 'little') + (32).to_bytes(2, 'little')
    dib += (0).to_bytes(4, 'little') + len(bytes(xor) + and_mask).to_bytes(4, 'little')
    dib += bytes(16)
    img = bytes(dib) + bytes(xor) + and_mask
    entry = bytearray()
    entry += bytes((w, h, 0, 0)) + (1).to_bytes(2, 'little') + (32).to_bytes(2, 'little')
    entry += len(img).to_bytes(4, 'little') + (22).to_bytes(4, 'little')
    with open(path, 'wb') as f:
        f.write((0).to_bytes(2, 'little') + (1).to_bytes(2, 'little') +
                (1).to_bytes(2, 'little') + bytes(entry) + img)
    return path


# ---------------- 5. 隐藏消息窗口（热键 + 托盘） ----------------
class HiddenWindow(threading.Thread):
    """独立线程创建 message-only 窗口，承载 RegisterHotKey 与托盘回调"""

    def __init__(self, on_hotkey, on_tray):
        threading.Thread.__init__(self, daemon=True)
        self.on_hotkey = on_hotkey
        self.on_tray = on_tray
        self.hwnd = None
        self.ready = threading.Event()
        self.hotkey_id = 1
        self.hotkey_ok = False
        self._proc = None
        self._icon = None
        self._hk_evt = threading.Event()

    def wndproc(self, hwnd, msg, wp, lp):
        try:
            if msg == WM_APP_REG:
                self._do_reg(int(wp), int(lp))
            elif msg == WM_APP_UNREG:
                self._do_unreg()
            elif msg == WM_TRAY:
                if lp == WM_LBUTTONUP:
                    self.on_tray('left')
                elif lp == WM_RBUTTONUP:
                    self.on_tray('right')
            elif msg == WM_DESTROY:
                u32.PostQuitMessage(0)
                return 0
        except Exception:
            pass
        return u32.DefWindowProcW(hwnd, msg, wp, lp)

    def run(self):
        try:
            self._proc = WNDPROC(self.wndproc)
            wc = WNDCLASS()
            wc.lpfnWndProc = self._proc
            wc.lpszClassName = 'ClawBoardMsgWindow'
            wc.hInstance = k32.GetModuleHandleW(None)
            u32.RegisterClassW(ctypes.byref(wc))
            self.hwnd = u32.CreateWindowExW(0, 'ClawBoardMsgWindow', 'ClawBoardMsg',
                                            0, 0, 0, 0, 0, HWND_MESSAGE,
                                            None, wc.hInstance, None)
        except Exception:
            traceback.print_exc()
        finally:
            self.ready.set()
        if not self.hwnd:
            return
        try:
            msg = wintypes.MSG()
            while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                # 用 NULL 句柄注册的热键没有目标窗口，必须在循环里直接截获
                if msg.message == WM_HOTKEY:
                    self.on_hotkey()
                    continue
                u32.TranslateMessage(ctypes.byref(msg))
                u32.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            pass

    def _do_reg(self, vk, mod):
        """必须在消息线程内调用，hwnd 传 NULL：热键消息直接进本线程队列"""
        self._do_unreg()
        self.hotkey_ok = bool(u32.RegisterHotKey(None, self.hotkey_id, mod, vk))
        self._hk_evt.set()

    def _do_unreg(self):
        try:
            u32.UnregisterHotKey(None, self.hotkey_id)
        except Exception:
            pass
        self.hotkey_ok = False

    def reg_hotkey(self, mod, vk, timeout=0.6):
        """主线程调用：投递消息让消息线程注册，等结果回来"""
        if not self.hwnd:
            return False
        self._hk_evt.clear()
        self.hotkey_ok = False
        if not u32.PostMessageW(self.hwnd, WM_APP_REG, vk, mod):
            return False
        self._hk_evt.wait(timeout)
        return self.hotkey_ok

    def unreg_hotkey(self):
        if self.hwnd:
            try:
                self._hk_evt.clear()
                u32.PostMessageW(self.hwnd, WM_APP_UNREG, 0, 0)
            except Exception:
                pass
        self.hotkey_ok = False

    def tray_add(self):
        if not self.hwnd:
            return False
        try:
            if not os.path.exists(ICON_FILE):
                make_ico(ICON_FILE)
            self._icon = u32.LoadImageW(None, ICON_FILE, IMAGE_ICON, 0, 0,
                                        LR_LOADFROMFILE | LR_DEFAULTSIZE)
            nid = NOTIFYICONDATA()
            nid.cbSize = ctypes.sizeof(nid)
            nid.hWnd = self.hwnd
            nid.uID = 1
            nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            nid.uCallbackMessage = WM_TRAY
            nid.hIcon = self._icon
            nid.szTip = APP_NAME + ' 剪切板'
            return bool(sh32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))
        except Exception:
            return False

    def balloon(self, title, msg):
        """气泡提示：隐藏到托盘时告诉用户去哪儿找回来"""
        if not self.hwnd:
            return False
        try:
            nid = NOTIFYICONDATA()
            nid.cbSize = ctypes.sizeof(nid)
            nid.hWnd = self.hwnd
            nid.uID = 1
            nid.uFlags = NIF_INFO
            nid.szInfoTitle = (title or '')[:63]
            nid.szInfo = (msg or '')[:255]
            nid.dwInfoFlags = NIIF_INFO
            nid.uTimeout = 6000
            return bool(sh32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid)))
        except Exception:
            return False

    def tray_del(self):
        try:
            nid = NOTIFYICONDATA()
            nid.cbSize = ctypes.sizeof(nid)
            nid.hWnd = self.hwnd
            nid.uID = 1
            sh32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
        except Exception:
            pass
        if self._icon:
            u32.DestroyIcon(self._icon)
            self._icon = None

    def stop(self):
        try:
            if self.hwnd:
                u32.PostQuitMessage(0)
        except Exception:
            pass


# ---------------- 6. 通用控件 ----------------
_seq = [0]


def uid():
    _seq[0] += 1
    return '%d_%d' % (int(time.time() * 1000), _seq[0])


def now_str():
    return time.strftime('%m-%d %H:%M')


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


def preview(text, n=90):
    t = ' '.join((text or '').split())
    return t if len(t) <= n else t[:n] + '…'


def dark_top(win, title):
    win.configure(bg=T['bg'])
    win.overrideredirect(True)
    win.attributes('-topmost', True)
    bar = tk.Frame(win, bg=T['panel'], height=30)
    bar.pack(fill='x')
    bar.pack_propagate(False)
    tk.Label(bar, text=title, bg=T['panel'], fg=T['fg'], font=FONT_B).pack(side='left', padx=10)
    return bar


def center_on(win, parent, w, h):
    win.update_idletasks()
    px, py = parent.winfo_rootx(), parent.winfo_rooty()
    pw, ph = parent.winfo_width(), parent.winfo_height()
    win.geometry('%dx%d+%d+%d' % (w, h, max(px + (pw - w) // 2, 0), max(py + (ph - h) // 2, 0)))


def safe_release(win):
    """关闭弹窗时释放（可能根本没 grab 过，不能让它抛异常打断流程）"""
    try:
        win.grab_release()
    except Exception:
        pass


class Dialog:
    """非模态输入对话框：on_ok 回调，绝不阻塞主循环"""

    def __init__(self, parent, title, fields, on_ok=None, ok_text='确定'):
        self.result = None
        self.on_ok = on_ok
        self.parent = parent
        self.win = tk.Toplevel(parent)
        self.win.transient(parent)
        dark_top(self.win, title)
        self.win.attributes('-topmost', True)
        self.win.after(60, lambda: (self.win.lift(), self.win.focus_force()))
        body = tk.Frame(self.win, bg=T['bg'])
        body.pack(fill='both', expand=True, padx=12, pady=10)
        self.vars = {}
        for label, default, multi in fields:
            if label:
                tk.Label(body, text=label, bg=T['bg'], fg=T['fg2'], font=FONT_SM,
                         anchor='w').pack(fill='x')
            if multi:
                w = tk.Text(body, height=5, bg=T['card'], fg=T['fg'],
                            insertbackground=T['fg'], relief='flat', font=FONT,
                            wrap='word', bd=0, highlightthickness=1,
                            highlightbackground=T['line'], highlightcolor=T['acc'])
                w.insert('1.0', default or '')
                w.pack(fill='x', pady=(2, 8))
                self.vars[label] = (None, w)
            else:
                v = tk.StringVar(value=default or '')
                e = tk.Entry(body, textvariable=v, bg=T['card'], fg=T['fg'],
                             insertbackground=T['fg'], relief='flat', font=FONT, bd=0,
                             highlightthickness=1, highlightbackground=T['line'],
                             highlightcolor=T['acc'])
                e.pack(fill='x', ipady=4, pady=(2, 8))
                self.vars[label] = (v, None)
        btns = tk.Frame(self.win, bg=T['bg'])
        btns.pack(fill='x', padx=12, pady=(0, 12))
        self._mk_btn(btns, ok_text, T['acc'], self._ok).pack(side='right', padx=(6, 0))
        self._mk_btn(btns, '取消', T['card_h'], self._cancel).pack(side='right')
        self.win.bind('<Return>', lambda e: self._ok())
        self.win.bind('<Escape>', lambda e: self._cancel())
        self.win.protocol('WM_DELETE_WINDOW', self._cancel)

    def _mk_btn(self, master, text, color, cmd):
        b = tk.Label(master, text=text, bg=color, fg='#ffffff', font=FONT_B,
                     padx=14, pady=5, cursor='hand2')
        b.bind('<Button-1>', lambda e: cmd())
        b.bind('<Enter>', lambda e: b.configure(bg=T['acc2'] if color == T['acc'] else T['line']))
        b.bind('<Leave>', lambda e: b.configure(bg=color))
        return b

    def _ok(self):
        out = [w.get('1.0', 'end-1c') if w is not None else v.get()
               for v, w in self.vars.values()]
        self.result = out
        safe_release(self.win)
        self.win.destroy()
        if self.on_ok:
            self.on_ok(out)

    def _cancel(self):
        self.result = None
        safe_release(self.win)
        self.win.destroy()

    def show(self, w=380, h=None):
        if h is None:
            self.win.update_idletasks()
            h = self.win.winfo_reqheight()
        center_on(self.win, self.parent, w, h)
        return self.result


class SplitDialog:
    MODES = ['自动（换行/逗号/分号/顿号/空格）', '按换行', '按逗号', '按空格', '按分号', '自定义分隔符']

    def __init__(self, app, text):
        self.app = app
        self.win = tk.Toplevel(app.root)
        self.win.transient(app.root)
        dark_top(self.win, '拆词')
        self.win.attributes('-topmost', True)
        self.win.after(60, lambda: (self.win.lift(), self.win.focus_force()))
        body = tk.Frame(self.win, bg=T['bg'])
        body.pack(fill='both', expand=True, padx=12, pady=8)
        tk.Label(body, text='源文本', bg=T['bg'], fg=T['fg2'], font=FONT_SM, anchor='w').pack(fill='x')
        self.txt = tk.Text(body, height=5, bg=T['card'], fg=T['fg'], insertbackground=T['fg'],
                           relief='flat', font=FONT, wrap='word', bd=0,
                           highlightthickness=1, highlightbackground=T['line'],
                           highlightcolor=T['acc'])
        self.txt.insert('1.0', text)
        self.txt.pack(fill='x', pady=(2, 8))
        row = tk.Frame(body, bg=T['bg'])
        row.pack(fill='x', pady=(0, 6))
        tk.Label(row, text='分隔方式', bg=T['bg'], fg=T['fg2'], font=FONT_SM).pack(side='left')
        self.mode = tk.StringVar(value=self.MODES[0])
        mb = tk.Label(row, text='▾ 选择', bg=T['card'], fg=T['fg'], font=FONT_SM,
                      padx=8, pady=3, cursor='hand2')
        mb.pack(side='right')
        mb.bind('<Button-1>', lambda e: self.mode_menu(mb))
        self.custom = tk.Entry(body, bg=T['card'], fg=T['fg'], insertbackground=T['fg'],
                               relief='flat', font=FONT, bd=0, highlightthickness=1,
                               highlightbackground=T['line'], highlightcolor=T['acc'])
        self.custom.insert(0, '|')
        self.custom.pack(fill='x', pady=(0, 6))
        self.prev = tk.Label(body, text='', bg=T['bg'], fg=T['acc'], font=FONT_SM,
                             anchor='w', wraplength=330, justify='left')
        self.prev.pack(fill='x', pady=(0, 6))
        btns = tk.Frame(body, bg=T['bg'])
        btns.pack(fill='x')
        self.mk(btns, '拆成常用语', T['acc'], self.ok).pack(side='right', padx=(6, 0))
        self.mk(btns, '预览', T['card_h'], self.do_preview).pack(side='right')
        self.mk(btns, '取消', T['card_h'], self.cancel).pack(side='left')
        self.win.bind('<Escape>', lambda e: self.cancel())
        self.win.protocol('WM_DELETE_WINDOW', self.cancel)
        self.do_preview()
        center_on(self.win, self.app.root, 380, 360)

    def mk(self, master, text, color, cmd):
        b = tk.Label(master, text=text, bg=color, fg='#fff', font=FONT_B,
                     padx=12, pady=5, cursor='hand2')
        b.bind('<Button-1>', lambda e: cmd())
        return b

    def mode_menu(self, anchor):
        m = tk.Menu(self.win, tearoff=0, bg=T['panel'], fg=T['fg'], bd=0,
                    activebackground=T['card_h'], activeforeground=T['fg'],
                    font=FONT, relief='flat')
        for x in self.MODES:
            m.add_command(label=x, command=lambda x=x: (self.mode.set(x), self.do_preview()))
        m.tk_popup(anchor.winfo_rootx(), anchor.winfo_rooty() + anchor.winfo_height())

    def do_split(self):
        raw = self.txt.get('1.0', 'end-1c')
        m = self.mode.get()
        table = {self.MODES[0]: r'[\r\n,;；，、\s]+', self.MODES[1]: r'[\r\n]+',
                 self.MODES[2]: r'[,，]+', self.MODES[3]: r'[ \t]+', self.MODES[4]: r'[;；]+'}
        if m in table:
            parts = re.split(table[m], raw)
        else:
            sep = self.custom.get()
            parts = raw.split(sep) if sep else [raw]
        return [p.strip() for p in parts if p.strip()]

    def do_preview(self):
        parts = self.do_split()
        self.prev.configure(text='预览：共 %d 条 → %s' %
                            (len(parts), ' | '.join(parts[:6]) + (' …' if len(parts) > 6 else '')))

    def ok(self):
        parts = self.do_split()
        if not parts:
            self.prev.configure(text='没拆出任何内容', fg=T['danger'])
            return
        g = self.app.cur_group()
        for p in parts:
            g['items'].insert(0, {'id': uid(), 'name': preview(p, 12), 'text': p})
        self.app.save(True)
        self.app.tab = 'phrase'
        self.app.render()
        self.app.tip('已拆出 %d 条常用语' % len(parts))
        safe_release(self.win)
        self.win.destroy()

    def cancel(self):
        safe_release(self.win)
        self.win.destroy()


# ---------------- 7. 虚拟滚动列表 ----------------
class Tip:
    """悬停提示：延迟 450ms 弹出，移开立即销毁"""

    def __init__(self, root):
        self.root = root
        self.win = None
        self.job = None

    def show(self, text, x, y):
        self.hide()
        self.job = self.root.after(450, lambda: self._pop(text, x, y))

    def _pop(self, text, x, y):
        self.hide()
        w = tk.Toplevel(self.root)
        w.overrideredirect(True)
        w.attributes('-topmost', True)
        tk.Label(w, text=text, bg=T['panel'], fg=T['fg'], font=FONT_SM,
                 justify='left', padx=8, pady=5, bd=1, relief='solid').pack()
        w.geometry('+%d+%d' % (x + 18, y + 18))
        self.win = w

    def hide(self):
        if self.job:
            try:
                self.root.after_cancel(self.job)
            except Exception:
                pass
            self.job = None
        if self.win:
            try:
                self.win.destroy()
            except Exception:
                pass
            self.win = None


class ThinBar(tk.Canvas):
    """自绘细滑动条：没有两端箭头，滑块颜色看得见、拖得动。

    直接实现 tk 的 yscrollcommand 协议，谁都能接：
        canvas.configure(yscrollcommand=bar.set)
    """

    MIN_THUMB = 28          # 滑块最小高度，再短就抓不住了

    def __init__(self, master, on_move, width=8, on_wheel=None):
        tk.Canvas.__init__(self, master, width=width, bg=T['bg'],
                           highlightthickness=0, bd=0)
        self.on_move = on_move
        self.w = width
        self._first = 0.0
        self._last = 1.0
        self._grab = None       # 按住滑块时，记录鼠标相对滑块顶端的偏移
        self._mode = 0          # 0 静默 1 悬停 2 拖动
        self.bind('<Configure>', lambda e: self._draw())
        self.bind('<Button-1>', self._press)
        self.bind('<B1-Motion>', self._move)
        self.bind('<ButtonRelease-1>', self._release)
        self.bind('<Enter>', lambda e: self._paint(1))
        self.bind('<Leave>', lambda e: self._paint(0))
        if on_wheel:
            self.bind('<MouseWheel>', on_wheel)

    # ---------- tk Scrollbar 协议 ----------
    def set(self, first, last):
        first, last = float(first), float(last)
        if abs(first - self._first) < 1e-6 and abs(last - self._last) < 1e-6:
            return
        self._first, self._last = first, last
        self._draw()

    def get(self):
        return (self._first, self._last)

    # ---------- 内部 ----------
    def _geom(self):
        """返回 (滑块顶端 y, 滑块高度, 轨道高度)"""
        h = max(1, self.winfo_height())
        span = max(0.0, min(1.0, self._last - self._first))
        if span >= 0.9999:
            return 0, h, h
        th = max(self.MIN_THUMB, int(h * span))
        y = int(self._first * (h - th) / (1.0 - span))
        return y, th, h

    def _draw(self):
        # 窗口销毁瞬间仍可能收到 <Configure>，此时 canvas 已不能画了，直接放弃
        try:
            self.delete('all')
            h = max(1, self.winfo_height())
            self.create_rectangle(0, 0, self.w, h, fill=T['panel'], outline='')
            y, th, _ = self._geom()
            if th >= h:             # 内容不满一屏：只留一条淡轨道，不影响观感
                return
            if self._mode == 2:
                col = T['acc']      # 拖动中
            elif self._mode == 1:
                col = T['fg']       # 悬停
            else:
                col = T['fg2']      # 静默也看得见
            self.create_rectangle(1, y + 1, self.w - 1, y + th - 1, fill=col, outline='')
        except tk.TclError:
            pass

    def _paint(self, mode):
        if self._grab is not None:
            self._mode = 2
            return
        self._mode = mode
        self._draw()

    def _press(self, e):
        y, th, h = self._geom()
        if th >= h:
            return
        if y <= e.y <= y + th:
            self._grab = e.y - y            # 抓住滑块本体
        else:
            self._grab = th // 2            # 点轨道：滑块中心跟过来
            self._move(e)
        self._mode = 2
        self._draw()

    def _move(self, e):
        if self._grab is None:
            return
        _, th, h = self._geom()
        span = max(0.0, min(1.0, self._last - self._first))
        if span >= 0.9999 or h - th <= 0:
            return
        y = max(0, min(h - th, e.y - self._grab))
        first = y * (1.0 - span) / (h - th)
        self._first = first
        self._last = first + span
        self._draw()
        self.on_move(first)

    def _release(self, e):
        self._grab = None
        self._paint(1)


class ScrollFrame(tk.Frame):
    """可滚动容器：内容放 .inner。滚轮 + 右侧细滚动条，内层宽度自动跟随。"""

    def __init__(self, master, bg=None):
        bg = bg or T['bg']
        tk.Frame.__init__(self, master, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0,
                                yscrollincrement=24)
        self.sb = ThinBar(self, lambda f: self.canvas.yview_moveto(f),
                          width=8, on_wheel=self._wheel)
        self.sb.pack(side='right', fill='y')      # 先占位，再让 canvas 吃掉剩余宽度
        self.canvas.pack(side='left', fill='both', expand=True)
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._wid = self.canvas.create_window((0, 0), window=self.inner, anchor='nw')
        self._acc = 0.0
        self.inner.bind('<Configure>', self._on_inner)
        self.canvas.bind('<Configure>', self._on_canvas)
        self.canvas.bind('<MouseWheel>', self._wheel)

    def _on_inner(self, _=None):
        try:
            self.canvas.configure(scrollregion=self.canvas.bbox('all') or (0, 0, 0, 0))
        except tk.TclError:
            pass

    def _on_canvas(self, e):
        try:
            self.canvas.itemconfigure(self._wid, width=e.width)
        except tk.TclError:
            pass

    def bind_wheel_tree(self, w=None):
        """内容建好后调用一次：给所有子控件补上滚轮绑定（含后加的）"""
        w = w or self.inner
        for c in w.winfo_children():
            c.bind('<MouseWheel>', self._wheel)
            self.bind_wheel_tree(c)

    def _wheel(self, e):
        d = getattr(e, 'delta', 0)
        if not d:
            return 'break'
        self._acc += d / 120.0
        steps = int(self._acc)
        if not steps:
            return 'break'
        self._acc -= steps
        self.canvas.yview_scroll(-steps * WHEEL_LINES, 'units')
        return 'break'


class VirtualList(tk.Frame):
    """固定行高窗口化渲染：5000 条只创建可视区 widget"""

    def __init__(self, master, on_click, on_menu, on_hover):
        tk.Frame.__init__(self, master, bg=T['bg'])
        self.on_click = on_click
        self.on_menu = on_menu
        self.on_hover = on_hover
        self.tip = Tip(self.winfo_toplevel())
        self.items = []
        self.sel = None
        self.multi = set()
        self.kw = ''
        self.pool = {}
        self.wids = {}
        self._vw = 0
        self._last_w = -1
        self._maxc = 0
        self._maxc2 = 40
        self.canvas = tk.Canvas(self, bg=T['bg'], highlightthickness=0, bd=0)
        self.sb = ThinBar(self, self._bar_move, width=8, on_wheel=self._wheel)
        # 顺序很重要：canvas 的请求宽度是 378px，先 pack 它会把后 pack 的滑动条压成 1px
        self.sb.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.canvas.configure(yscrollcommand=self.sb.set)
        self._acc = 0.0        # 滚轮增量累积：触控板/高精度滚轮的 delta 常小于 120
        self.show_num = False  # 按住 Ctrl 时在行首显示 1..9/0
        self.canvas.bind('<MouseWheel>', self._wheel)
        self.canvas.bind('<Configure>', lambda e: self.update_view())

    def set_data(self, items, sel, kw):
        self.items = items
        self.sel = sel
        self.kw = kw
        self.clear_pool()
        self.canvas.yview_moveto(0)
        self.update_view()

    def clear_pool(self):
        for i in list(self.pool):
            self._drop(i)

    def _drop(self, i):
        w = self.pool.pop(i, None)
        wid = self.wids.pop(i, None)
        try:
            if wid:
                self.canvas.delete(wid)
        except Exception:
            pass
        try:
            if w:
                w.destroy()
        except Exception:
            pass

    def _wheel(self, e):
        """滚轮滚动。delta/120 直接取整会让触控板（delta=40/±1）永远为 0 滚不动，
        所以先把增量累加起来，攒够一格再滚。"""
        d = getattr(e, 'delta', 0)
        if not d:
            return 'break'
        self._acc += d / 120.0
        steps = int(self._acc)
        if not steps:
            return 'break'
        self._acc -= steps
        self.scroll_rows(-steps * WHEEL_LINES)
        return 'break'

    def _bar_move(self, first):
        """拖滑动条：first 是滑块顶端对应的比例"""
        self.canvas.yview_moveto(first)
        self.update_view()

    def scroll_rows(self, rows):
        """按行滚动（负值向下），夹在首尾之间，滚到头不会滚出空白"""
        n = len(self.items)
        if n <= 0 or not rows:
            return
        total = n * ITEM_H
        h = max(1, self.canvas.winfo_height())
        top = self.canvas.canvasy(0) + rows * ITEM_H
        top = max(0.0, min(max(0.0, total - h), top))
        self.canvas.yview_moveto(top / float(total))
        self.update_view()

    def yview_step(self, px):
        """按像素步进滚动（bench 与键盘翻页用）"""
        self.canvas.yview_scroll(max(1, int(px / ITEM_H)), 'units')

    def scroll_to_index(self, i):
        total = max(1, len(self.items) * ITEM_H)
        h = max(1, self.canvas.winfo_height())
        self.canvas.yview_moveto(max(0.0, min(1.0, (i * ITEM_H - h / 2.0) / float(total))))
        self.update_view()

    def update_view(self):
        n = len(self.items)
        w = max(60, self.canvas.winfo_width())
        self._vw = w
        if self._last_w != w:
            self.canvas.configure(scrollregion=(0, 0, w, max(1, n * ITEM_H)))
            self._last_w = w
        else:
            self.canvas.configure(scrollregion=(0, 0, w, max(1, n * ITEM_H)))
        if n == 0:
            self.clear_pool()
            return
        h = max(ITEM_H, self.canvas.winfo_height())
        top = self.canvas.canvasy(0)
        start = max(0, int(top // ITEM_H))
        end = min(n, int((top + h) // ITEM_H) + 2)
        for i in list(self.pool):
            if i < start or i >= end:
                self._drop(i)
        for i in range(start, end):
            f = self.pool.get(i)
            if f is None:
                f = self._mk_item(i)
                self.pool[i] = f
                self.wids[i] = self.canvas.create_window((0, i * ITEM_H), window=f,
                                                         anchor='nw', width=w, height=ITEM_H)
            else:
                self.canvas.coords(self.wids[i], 0, i * ITEM_H)
                if f._vw != w:
                    self.canvas.itemconfig(self.wids[i], width=w)
                    f._vw = w
            f._idx = i
            self._fill(f, i)

    def _mk_item(self, i):
        f = tk.Frame(self.canvas, bg=T['card'], height=ITEM_H, cursor='hand2')
        f.pack_propagate(False)
        f._idx = i
        f._vw = 0
        # 序号列：按住 Ctrl 时显示 1..9/0，提示「Ctrl+数字直接粘贴」（Ditto QListCtrl.cpp:610）
        f._num = tk.Label(f, bg=T['card'], font=FONT_SM, fg=T['acc'], anchor='w')
        f._num.place(x=6, y=7, width=16, height=16)
        row = tk.Frame(f, bg=T['card'])
        row.place(x=24, y=6, relwidth=1, width=-112, height=18)
        f._row = row
        f._l1a = tk.Label(row, bg=T['card'], font=FONT, anchor='w')
        f._l1b = tk.Label(row, bg=T['card'], font=FONT, anchor='w', fg=T['acc'])
        f._l1c = tk.Label(row, bg=T['card'], font=FONT, anchor='w')
        for lb in (f._l1a, f._l1b, f._l1c):
            lb.pack(side='left')
        f._badge = tk.Label(f, bg=T['card'], font=FONT_SM, fg=T['fg2'], anchor='e')
        f._badge.place(relx=1.0, x=-10, y=6, anchor='ne', height=18, width=80)
        f._l2 = tk.Label(f, bg=T['card'], font=FONT_SM, fg=T['fg2'], anchor='w')
        f._l2.place(x=24, y=28, relwidth=1, width=-32, height=16)
        for wg in (f, row, f._num, f._l1a, f._l1b, f._l1c, f._l2, f._badge):
            wg.bind('<Button-1>', lambda e, ff=f: self.on_click(ff._idx, e))
            wg.bind('<Button-3>', lambda e, ff=f: self.on_menu(e, ff._idx))
            wg.bind('<Enter>', lambda e, ff=f: (self._hover(ff._idx, True),
                                                self.on_hover(ff._idx, e.x_root, e.y_root)))
            wg.bind('<Leave>', lambda e, ff=f: (self._hover(ff._idx, False),
                                                self.tip.hide()))
            # 鼠标停在条目上时事件不会冒泡到 canvas，必须逐个子控件接管滚轮
            wg.bind('<MouseWheel>', self._wheel)
        return f

    def _paint(self, f, c):
        f.configure(bg=c)
        f._row.configure(bg=c)
        f._num.configure(bg=c)
        f._l1a.configure(bg=c)
        f._l1b.configure(bg=c)
        f._l1c.configure(bg=c)
        f._l2.configure(bg=c)
        f._badge.configure(bg=c)

    def _hover(self, i, on):
        f = self.pool.get(i)
        if not f or not (0 <= i < len(self.items)):
            return
        if self.items[i].get('id') == self.sel:
            return
        self._paint(f, T['card_h'] if on else T['card'])

    def _first_hit(self, body):
        """找出该高亮哪个词。
        原实现拿整串 `self.kw` 去 find，搜「hello world」这种多词时永远找不到 → 不高亮。
        CopyQ filterlineedit.cpp:198 是按空白拆词逐词匹配的（AND），这里照做：
        整串命中就整串高亮，否则取第一个能命中的词。"""
        kw = (self.kw or '').strip()
        if not kw:
            return '', -1
        low = body.lower()
        p = low.find(kw.lower())
        if p >= 0:
            return kw, p
        for w in kw.split():
            p = low.find(w.lower())
            if p >= 0:
                return w, p
        return '', -1

    def _fill(self, f, i):
        it = self.items[i]
        if it.get('id') == self.sel:
            c = T['card_s']
        elif it.get('id') in self.multi:
            c = T['card_m']
        else:
            c = T['card']
        self._paint(f, c)
        body = it.get('disp') or it.get('text', '')
        w = self._vw or 300
        maxc = max(8, int(w / 7.2))
        if self._maxc != maxc:
            self._maxc = maxc
            self._maxc2 = max(8, int(w / 6.5))
        f._num.configure(text=('0' if i == 9 else str(i + 1)) if
                         (self.show_num and i < 10) else '')
        kw, pos = self._first_hit(body)
        if pos >= 0 and kw:
            s = max(0, pos - 6)
            seg = body[s:s + maxc]
            a = seg[:pos - s]
            b = seg[pos - s:pos - s + len(kw)]
            cc = seg[pos - s + len(kw):]
            f._l1a.configure(text=a, fg=T['fg'])
            f._l1b.configure(text=b)
            f._l1c.configure(text=preview(cc, max(1, maxc - len(a) - len(b))), fg=T['fg'])
        else:
            f._l1a.configure(text=preview(body, maxc), fg=T['fg'])
            f._l1b.configure(text='')
            f._l1c.configure(text='')
        f._l2.configure(text=preview(it.get('sub', ''), self._maxc2 or 40),
                        fg=T['acc'] if it.get('kind') == 'phrase' else T['fg2'])
        f._badge.configure(text=it.get('badge', ''))


# ---------------- 8. 主程序 ----------------
DEFAULT_SETTINGS = dict(theme='dark', hotkey='ctrl+shift+v', max_items=500,
                        listen=True, autopaste=True, mask_sensitive=True,
                        skip_sensitive=False, show_time=False, record_title=False,
                        group_by_time=False, edge_hide=False, edge_delay=8,
                        close_action='hide')      # hide=隐藏到托盘 / quit=直接退出
# v1.4.0 补齐项（对照 Ditto / PasteBar 的同类设置）
DEFAULT_SETTINGS.update(
    ignore_apps='keepass,1password,bitwarden,lastpass',   # 通配名单，命中不记录
    ignore_titles='',                                     # 正则名单（窗口标题）
    min_len=1,          # 短于这个长度不入库（0=不限），滤掉单个字母之类的噪声
    max_len=0,          # 长于这个长度不入库（0=不限，仍受 MAX_TEXT 硬上限保护）
    smart_private=True,  # 遵守 Windows「别记录我」剪贴板标记
    keep_on_clear=True,  # 清空历史时保留收藏项
)
# 开机自启不存配置文件，直接读注册表真实状态，避免"设置里开着其实没开"


class ClawBoard:
    def __init__(self, root):
        self.root = root
        self.tab = 'clip'
        self.sel_clip = None
        self.sel_phrase = None
        self.search = tk.StringVar()
        self.collapsed = False
        self.prev_hwnd = None
        self.save_timer = None
        self._need_show = False
        self._tray_menu = False
        self.hidden = False
        self.hotkey_ok = False
        self.hotkey_fallback = False
        self._hk_down = False
        self._paste_fail = False
        self._anchor_idx = None
        self.search_err = ''
        self._told_tray = False
        self._edge_hidden = False
        self._edge_tick = 0
        self._edge_side = None
        self._edge_pos = None
        self.t0 = time.time()

        self.data = self.load_data()
        self.st = self.data['settings']
        self._seq = max([int(x.get('seq') or 0) for x in self.data['clip']] or [0])
        set_theme(self.st['theme'])

        root.title(APP_NAME)
        root.overrideredirect(True)
        root.attributes('-topmost', True)
        root.attributes('-alpha', 0.97)
        root.configure(bg=T['bg'])
        root.bind('<Escape>', lambda e: self.hide())
        root.bind('<Up>', lambda e: self.move_sel(-1))
        root.bind('<Down>', lambda e: self.move_sel(1))
        root.bind('<Return>', lambda e: self.enter_sel())
        root.bind('<Control-f>', lambda e: self.focus_search())
        root.bind('<Delete>', lambda e: self.del_sel())
        root.bind('<Control-Shift-Return>', lambda e: self.paste_plain_sel())
        root.bind('<Control-t>', lambda e: self.open_transform())
        root.bind('<Control-e>', lambda e: self.open_export())
        root.bind('<Control-q>', lambda e: self.quit_app())
        # Ctrl+1..9 / Ctrl+0 → 直接粘贴第 1..10 项
        # （PasteBar ClipboardHistoryQuickPastePage.tsx:307，0 表示第 10 项）
        for _i in range(1, 10):
            root.bind('<Control-Key-%d>' % _i,
                      lambda e, n=_i: self.quick_paste(n))
        root.bind('<Control-Key-0>', lambda e: self.quick_paste(10))
        # 按住 Ctrl 时行首显示序号，把这组快捷键亮出来（Ditto QListCtrl.cpp:610）
        for _k in ('Control_L', 'Control_R'):
            root.bind('<KeyPress-%s>' % _k, lambda e: self.set_num_hint(True))
            root.bind('<KeyRelease-%s>' % _k, lambda e: self.set_num_hint(False))
        root.protocol('WM_DELETE_WINDOW', self.hide)

        self.build_ui()
        self.apply_geometry()
        self.save(True)      # 把修正后的位置立刻写回，避免下次启动又去纠正一遍
        self.setup_system()
        self.render()
        self.root.after(120, self.render)
        self.poll_clip()
        self.poll_bg()          # 前台窗口记录已并入本循环，定时器从 3 个降到 2 个

    # ---------- 数据 ----------
    @staticmethod
    def norm_item(it, seq):
        """保证单条记录字段齐全（任何缺字段都在这里兜住）"""
        if not isinstance(it, dict):
            return None
        if not isinstance(it.get('text'), str):
            return None
        if not it.get('created_at'):
            it['created_at'] = now_ms() - seq * 1000
            it['is_estimated'] = 1
        it.setdefault('is_estimated', 0)
        it.setdefault('seq', seq)
        it.setdefault('updated_at', it.get('created_at'))
        it.setdefault('last_used_at', None)
        it.setdefault('source_app', 'unknown')
        it.setdefault('source_title', None)
        it.setdefault('copy_count', 1)
        it.setdefault('fav', 0)
        it.setdefault('meta', None)
        it.setdefault('sens', None)
        it.setdefault('time', time.strftime('%m-%d %H:%M',
                                            time.localtime(it['created_at'] / 1000.0)))
        if not it.get('content_type'):
            it['content_type'] = detect_content_type(it.get('text', ''))
        if not it.get('content_size'):
            it['content_size'] = byte_size(it.get('text', ''))
        it.setdefault('id', uid())
        return it

    def load_data(self):
        # 注意：schema_version 默认必须是 1，否则老文件（无该字段）会被误判为已迁移
        d = {'clip': [], 'groups': [{'name': '默认', 'items': []}], 'gi': 0,
             'geom': None, 'settings': dict(DEFAULT_SETTINGS), 'schema_version': 1}
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                for k in list(d):
                    if k in loaded:
                        d[k] = loaded[k]
            except Exception:
                self.note('数据文件读取失败，已用默认值启动（原文件未改动）')
        if int(d.get('schema_version', 1)) < SCHEMA_VERSION:
            bak = backup_data()
            try:
                d = self.validate(migrate(d))
                self.save_now(d)
                self.note('数据已迁移到 v%d（备份：%s）' % (SCHEMA_VERSION, bak))
            except Exception as e:
                self.note('迁移失败，已回滚备份：%s' % e)
                if bak and os.path.exists(bak):
                    try:
                        with open(bak, 'rb') as a:
                            with open(DATA_FILE, 'wb') as b:
                                b.write(a.read())
                    except Exception:
                        pass
                d = self.validate(d)
        else:
            d = self.validate(d)
        return d

    def save_now(self, d=None):
        """同步落盘（迁移后立即写回用）"""
        if NO_SAVE:
            return False
        d = d or self.data
        tmp = DATA_FILE + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
            os.replace(tmp, DATA_FILE)
            return True
        except Exception as e:
            self.note('保存失败：%s' % e)
            return False

    @staticmethod
    def validate(d):
        """配置 schema 校验：任何非法字段回退默认值，绝不崩溃"""
        if not isinstance(d.get('clip'), list):
            d['clip'] = []
        seq = 0
        normed = []
        for x in d['clip']:
            seq += 1
            it = ClawBoard.norm_item(x, seq)
            if it:
                normed.append(it)
        d['clip'] = normed
        gs = []
        raw_groups = d.get('groups')
        if not isinstance(raw_groups, list):
            raw_groups = []
        for g in raw_groups:
            if not isinstance(g, dict) or not isinstance(g.get('name'), str):
                continue
            items = []
            for x in g.get('items', []):
                seq += 1
                it = ClawBoard.norm_item(x, seq)
                if it:
                    items.append(it)
            gs.append({'name': g['name'], 'items': items})
        d['groups'] = gs or [{'name': '默认', 'items': []}]
        try:
            gi = int(d.get('gi', 0))
        except Exception:
            gi = 0
        d['gi'] = min(max(0, gi), len(d['groups']) - 1)
        s = d.get('settings') if isinstance(d.get('settings'), dict) else {}
        fixed = dict(DEFAULT_SETTINGS)
        for k, v in fixed.items():
            if k in s and isinstance(s[k], type(v)):
                fixed[k] = s[k]
        if fixed['theme'] not in ('dark', 'light'):
            fixed['theme'] = 'dark'
        try:
            fixed['max_items'] = min(5000, max(10, int(fixed['max_items'])))
        except Exception:
            fixed['max_items'] = 500
        d['settings'] = fixed
        if not isinstance(d.get('geom'), str):
            d['geom'] = None
        return d

    def save(self, later=False):
        if NO_SAVE:
            return

        def do():
            self.data['geom'] = self.root.geometry()
            tmp = DATA_FILE + '.tmp'
            try:
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=1)
                os.replace(tmp, DATA_FILE)
            except Exception as e:
                self.note('保存失败：%s' % e)
            self.save_timer = None
        if later:
            if self.save_timer:
                self.root.after_cancel(self.save_timer)
            self.save_timer = self.root.after(300, do)
        else:
            do()

    def note(self, msg):
        """写运行日志。绝不写入剪贴板原文。"""
        try:
            with open(CRASH_LOG, 'a', encoding='utf-8') as f:
                f.write('[%s] %s\n' % (time.strftime('%F %T'), msg))
        except Exception:
            pass

    # ---------- 系统接入 ----------
    def setup_system(self):
        self.hw = HiddenWindow(self.on_hotkey, self.on_tray)
        self.hw.start()
        self.hw.ready.wait(3)
        if not self.hw.tray_add():
            self.note('托盘图标添加失败')
        self.apply_hotkey()

    def apply_hotkey(self):
        table = {'ctrl+shift+v': (MOD_CONTROL | MOD_SHIFT, VK_V),
                 'alt+v': (MOD_ALT, VK_V),
                 'ctrl+alt+v': (MOD_CONTROL | MOD_ALT, VK_V)}
        # 被占用就自动退到备用组合，而不是直接放弃（Ctrl+Shift+V 常被输入法/其他软件抢）
        want = self.st.get('hotkey', 'ctrl+shift+v')
        order = [want] + [k for k in table if k != want]
        used = None
        for key in order:
            if key in table and self.hw.reg_hotkey(*table[key]):
                used = key
                break
        self.hotkey_ok = bool(used)
        self.hotkey_fallback = (not used)
        if used and used != want:
            self.st['hotkey'] = used
            self.save(True)
            self.note('热键 %s 被占用，自动改用 %s' % (want, used))
            self.tip('热键被占用，已改用 %s' % used.upper())
        elif not used:
            self.note('所有候选热键均注册失败，降级为轮询检测')
            self.tip('热键全被占用，已启用降级检测')

    def on_hotkey(self):
        self.root.after(0, self.toggle_show)

    def on_tray(self, which):
        if which == 'left':
            self.root.after(0, self.toggle_show)
        else:
            self._tray_menu = True

    def poll_bg(self):
        """主线程统一消费后台事件 + 热键降级 + 靠边隐藏 + 前台窗口记录。

        整个循环体包在 try 里：以前任何一处异常都会让这个 after 链断掉，
        后果是面板点了没反应、粘贴后回不来、托盘菜单失效 —— 必须保证永续。
        """
        try:
            try:
                h = u32.GetForegroundWindow()
                if h and h != self.root.winfo_id():
                    self.prev_hwnd = h
            except Exception:
                pass
            if self._tray_menu:
                self._tray_menu = False
                self.tray_menu()
            if self._need_show:
                self._need_show = False
                self.root.deiconify()
                self.root.attributes('-topmost', True)
                if not self.ensure_onscreen():
                    self.render()
            if getattr(self, '_paste_fail', False):
                self._paste_fail = False
                self.tip('目标窗口拒绝焦点（可能是管理员权限），已复制，请手动 Ctrl+V')
            if self.hotkey_fallback:
                self._poll_hotkey()
            self.edge_update()
        except Exception as e:
            self.note('poll_bg 异常已吞掉（循环继续）：%s' % e)
        self.root.after(120, self.poll_bg)

    def _poll_hotkey(self):
        """RegisterHotKey 失败时的降级：轮询检测组合键（带按下防抖）"""
        try:
            down = ((u32.GetAsyncKeyState(VK_CONTROL) & 0x8000) and
                    (u32.GetAsyncKeyState(0x10) & 0x8000) and      # VK_SHIFT
                    (u32.GetAsyncKeyState(VK_V) & 0x8000))
        except Exception:
            return
        if down and not self._hk_down:
            self._hk_down = True
            self.toggle_show()
        elif not down:
            self._hk_down = False

    # ---------- UI ----------
    def build_ui(self):
        r = self.root
        for w in list(r.winfo_children()):
            w.destroy()
        self.bar = tk.Frame(r, bg=T['panel'], height=30, cursor='fleur')
        self.bar.pack(fill='x')
        self.bar.pack_propagate(False)
        self.title_lb = tk.Label(self.bar, text='⚡ ' + APP_NAME, bg=T['panel'],
                                 fg=T['acc'], font=FONT_TITLE)
        self.title_lb.pack(side='left', padx=8)
        self.bar.bind('<ButtonPress-1>', self.start_move)
        self.bar.bind('<B1-Motion>', self.do_move)
        self.bar.bind('<Double-Button-1>', lambda e: self.toggle_collapse())
        for txt, cmd, col in (('✕', self.hide, T['danger']),
                              ('📌', self.toggle_pin, None),
                              ('—', self.toggle_collapse, None)):
            b = tk.Label(self.bar, text=txt, bg=T['panel'], fg=T['fg2'], font=FONT,
                         width=3, cursor='hand2')
            b.pack(side='right')
            b.bind('<Button-1>', lambda e, c=cmd: c())
            b.bind('<Enter>', lambda e, b=b, c=col: b.configure(fg=c or T['fg']))
            b.bind('<Leave>', lambda e, b=b: b.configure(fg=T['fg2']))

        self.body = tk.Frame(r, bg=T['bg'])
        self.body.pack(fill='both', expand=True)

        tabs = tk.Frame(self.body, bg=T['bg'], height=32)
        tabs.pack(fill='x')
        tabs.pack_propagate(False)
        self.tab_clip = self.mk_tab(tabs, '剪贴板', 'clip')
        self.tab_phr = self.mk_tab(tabs, '常用语', 'phrase')

        self.gbar = tk.Frame(self.body, bg=T['bg'], height=28)
        self.gname = tk.Label(self.gbar, text='', bg=T['bg'], fg=T['fg'],
                              font=FONT_B, cursor='hand2')
        self.gname.pack(side='left', padx=(8, 2))
        self.gname.bind('<Button-1>', lambda e: self.group_menu())
        tk.Label(self.gbar, text='▾', bg=T['bg'], fg=T['fg2'], font=FONT_SM).pack(side='left')

        self.vlist = VirtualList(self.body, self.on_click_item,
                                 self.on_menu_item, self.on_hover_item)
        self.vlist.pack(fill='both', expand=True, padx=(6, 0), pady=4)

        self.tool = tk.Frame(self.body, bg=T['panel'], height=36)
        self.tool.pack(fill='x')
        self.tool.pack_propagate(False)
        self.search_entry = tk.Entry(self.tool, textvariable=self.search, bg=T['card'],
                                     fg=T['fg'], insertbackground=T['fg'], relief='flat',
                                     font=FONT_SM, bd=0, highlightthickness=1,
                                     highlightbackground=T['line'], highlightcolor=T['acc'])
        self.search_entry.pack(side='left', padx=6, ipady=3, fill='x', expand=True)
        self.search_entry.bind('<KeyRelease>', lambda e: self.render())
        self.search_entry.bind('<Escape>', lambda e: self.hide())
        self.search_entry.bind('<Return>', self.on_search_return)
        self.search_entry.bind('<Button-3>', lambda e: self.search_menu(e))
        self.search_entry.bind('<Control-a>', self.select_all_visible)
        for txt, tip, cmd in (('＋', '新增常用语', self.add_phrase),
                              ('拆', '拆词：把一段文字拆成多条常用语', self.split_words),
                              ('删', '删除选中项', self.del_sel),
                              ('清', '清空当前列表', self.clear_list),
                              ('🔧', '文本变换（Ctrl+T）', self.open_transform),
                              ('?', '搜索语法帮助', self.open_query_help),
                              ('⚙', '设置', self.open_settings)):
            self.mk_tool_btn(txt, tip, cmd)

        self.grip = tk.Label(r, text='◢', bg=T['bg'], fg=T['line'], font=('Consolas', 9),
                             cursor='sizing')
        self.grip.place(relx=1.0, rely=1.0, anchor='se')
        self.grip.bind('<ButtonPress-1>', self.start_resize)
        self.grip.bind('<B1-Motion>', self.do_resize)

    def mk_tab(self, master, text, key):
        f = tk.Frame(master, bg=T['bg'], cursor='hand2')
        f.pack(side='left', fill='y')
        lb = tk.Label(f, text=text, bg=T['bg'], fg=T['fg2'], font=FONT_B, padx=14, pady=6)
        lb.pack()
        bar = tk.Frame(f, bg=T['bg'], height=2)
        bar.pack(fill='x', side='bottom')
        for w in (f, lb):
            w.bind('<Button-1>', lambda e: self.set_tab(key))
        f._lb, f._bar, f._key = lb, bar, key
        return f

    def mk_tool_btn(self, text, tip, cmd):
        b = tk.Label(self.tool, text=text, bg=T['card'], fg=T['fg'], font=FONT_B,
                     width=3, cursor='hand2')
        b.pack(side='left', padx=2, pady=5)
        b.bind('<Button-1>', lambda e: cmd())
        b.bind('<Enter>', lambda e: (b.configure(bg=T['card_h']), self.tip(tip)))
        b.bind('<Leave>', lambda e: b.configure(bg=T['card']))
        return b

    def tip(self, text):
        self.title_lb.configure(text='⚡ ' + text)
        self.root.after(2500, lambda: self.title_lb.configure(text='⚡ ' + APP_NAME))

    def confirm(self, text, on_yes):
        Dialog(self.root, '确认', [('', text, True)],
               on_ok=lambda v: on_yes(), ok_text='确定').show(430, 200)

    # ---------- 几何 ----------
    def apply_geometry(self):
        """恢复位置。必须完整落在某一个显示器内：跨屏缝隙会让面板看起来开着却点不到"""
        g = self.data.get('geom')
        if g:
            m = re.match(r'^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$', g)
            if m:
                w, h, x, y = (int(v) for v in m.groups())
                w, h, x, y = self.fit_geometry(w, h, x, y)
                self.root.geometry('%dx%d+%d+%d' % (w, h, x, y))
                return
        w, h, x, y = self.fit_geometry(340, 480, 10 ** 6, 10 ** 6)
        self.root.geometry('%dx%d+%d+%d' % (w, h, x, y))

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
        self.root.geometry('+%d+%d' % (self.root.winfo_x() + e.x_root - self._mx,
                                       self.root.winfo_y() + e.y_root - self._my))
        self.clamp_to_screen()
        self._mx, self._my = e.x_root, e.y_root

    def start_resize(self, e):
        self._rx, self._ry = e.x_root, e.y_root
        self._rw, self._rh = self.root.winfo_width(), self.root.winfo_height()

    def do_resize(self, e):
        w = max(240, self._rw + (e.x_root - self._rx))
        h = max(160, self._rh + (e.y_root - self._ry))
        self.root.geometry('%dx%d' % (w, h))
        self.vlist.update_view()

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

    def toggle_collapse(self):
        self.collapsed = not self.collapsed
        if self.collapsed:
            self._restore = self.root.geometry()
            self.body.pack_forget()
            self.root.geometry('210x30+%d+%d' % (self.root.winfo_x(), self.root.winfo_y()))
        else:
            self.body.pack(fill='both', expand=True)
            self.root.geometry(self._restore)
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

    def quit_app(self):
        # 记一条：事后才能区分「用户正常退出」和「进程被外部杀掉」（后者不会留下任何痕迹）
        self.note('用户触发退出（托盘 / Ctrl+Q / 设置里的退出按钮）')
        try:
            self.hw.unreg_hotkey()
            self.hw.tray_del()
            self.hw.stop()
        except Exception:
            pass
        self.save()
        self.root.destroy()

    # ---------- Tab / 分组 ----------
    def set_tab(self, key):
        self.tab = key
        self.render()

    def cur_group(self):
        return self.data['groups'][self.data['gi']]

    def group_menu(self):
        m = tk.Menu(self.root, tearoff=0, bg=T['panel'], fg=T['fg'], bd=0,
                    activebackground=T['card_h'], activeforeground=T['fg'],
                    font=FONT, relief='flat')
        for i, g in enumerate(self.data['groups']):
            m.add_command(label=('● ' if i == self.data['gi'] else '   ') + g['name'],
                          command=lambda i=i: self.switch_group(i))
        m.add_separator()
        m.add_command(label='＋ 新建分组', command=self.new_group)
        m.add_command(label='✎ 重命名当前分组', command=self.rename_group)
        m.add_command(label='✕ 删除当前分组', command=self.del_group)
        m.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())

    def switch_group(self, i):
        self.data['gi'] = i
        self.save(True)
        self.render()

    def new_group(self):
        def done(v):
            if v and v[0].strip():
                self.data['groups'].append({'name': v[0].strip(), 'items': []})
                self.data['gi'] = len(self.data['groups']) - 1
                self.save(True)
                self.render()
        Dialog(self.root, '新建分组', [('分组名称', '新分组', False)], on_ok=done).show(320)

    def rename_group(self):
        g = self.cur_group()

        def done(v):
            if v and v[0].strip():
                g['name'] = v[0].strip()
                self.save(True)
                self.render()
        Dialog(self.root, '重命名分组', [('分组名称', g['name'], False)], on_ok=done).show(320)

    def del_group(self):
        if len(self.data['groups']) <= 1:
            self.tip('至少要保留一个分组')
            return
        g = self.cur_group()

        def do_del():
            i = self.data['gi']
            del self.data['groups'][i]
            self.data['gi'] = max(0, i - 1)
            self.save(True)
            self.render()
        self.confirm('删除分组「%s」及其 %d 条常用语？此操作不可撤销。' %
                     (g['name'], len(g['items'])), do_del)

    # ---------- 渲染 ----------
    def visible_items(self):
        q = self.search.get().strip()
        out = []
        pool = self.data['clip'] if self.tab == 'clip' else self.cur_group()['items']
        sel = self.sel_clip if self.tab == 'clip' else self.sel_phrase
        self.search_err = ''
        kw = ''
        if q:
            pool, cond = Q.match(q, pool)
            if cond['errors']:
                self.search_err = cond['errors'][0]
            kw = cond['terms'][0] if cond['terms'] else ''
        for it in pool:
            text = it['text']
            name = it.get('name') or ''
            hits = it.get('sens') or []
            disp = text
            if hits and self.st['mask_sensitive'] and not it.get('mask_off'):
                disp = mask_text(text, hits)
            size = int(it.get('content_size') or 0)
            if self.tab == 'phrase':
                sub = name or preview(text, 28)
                badge = human_size(byte_size(text))
            else:
                parts = []
                if self.st['show_time']:
                    parts.append(rel_time(it.get('created_at'), it.get('is_estimated')))
                parts.append(it.get('source_app') or 'unknown')
                if int(it.get('copy_count') or 1) > 1:
                    parts.append('×%d' % it['copy_count'])
                if hits:
                    parts.append('⚠' + '/'.join(hits))
                sub = ' · '.join(parts)
                badge = '%s · %s' % (it.get('content_type') or 'text', human_size(size))
            if it.get('fav'):
                disp = '★ ' + disp
            out.append({'id': it['id'], 'disp': disp, 'text': text, 'sub': sub,
                        'badge': badge, 'kind': self.tab, 'sens': hits,
                        'created_at': it.get('created_at'),
                        'est': it.get('is_estimated'),
                        'app': it.get('source_app') or 'unknown'})
        return out, sel, kw

    def render(self):
        for t in (self.tab_clip, self.tab_phr):
            on = (t._key == self.tab)
            t._lb.configure(fg=T['fg'] if on else T['fg2'])
            t._bar.configure(bg=T['acc'] if on else T['bg'])
        if self.tab == 'phrase':
            if not self.gbar.winfo_ismapped():
                self.gbar.pack(fill='x', before=self.vlist)
            self.gname.configure(text=self.cur_group()['name'])
        else:
            if self.gbar.winfo_ismapped():
                self.gbar.pack_forget()
        items, sel, kw = self.visible_items()
        try:
            self.search_entry.configure(
                highlightbackground=T['danger'] if self.search_err else T['line'])
        except Exception:
            pass
        if self.search_err:
            self.tip('语法：' + self.search_err)
        self.vlist.set_data(items, sel, kw)

    # ---------- 交互 ----------
    def on_click_item(self, i, e=None):
        """Ctrl = 多选切换，Shift = 连选，都不触发粘贴；普通单击 = 选中并粘贴"""
        items = self.vlist.items
        if not (0 <= i < len(items)):
            return
        it = items[i]
        if e is not None:
            state = getattr(e, 'state', 0)
            if state & 0x0004:                      # Ctrl
                cid = it['id']
                if cid in self.vlist.multi:
                    self.vlist.multi.discard(cid)
                else:
                    self.vlist.multi.add(cid)
                self.vlist.update_view()
                self.tip('已选 %d 条' % len(self.vlist.multi))
                return
            if state & 0x0001:                      # Shift
                anchor = self._anchor_idx if self._anchor_idx is not None else 0
                a, b = min(anchor, i), max(anchor, i)
                for k in range(a, b + 1):
                    self.vlist.multi.add(items[k]['id'])
                self.vlist.update_view()
                self.tip('已选 %d 条' % len(self.vlist.multi))
                return
        self._anchor_idx = i
        if not (getattr(e, 'state', 0) & 0x0004):
            self.vlist.multi.clear()
        if self.tab == 'clip':
            self.sel_clip = it['id']
        else:
            self.sel_phrase = it['id']
        self.vlist.sel = it['id']
        self.vlist.update_view()
        self.paste(it['text'], cid=it['id'])

    def on_menu_item(self, e, i):
        items = self.vlist.items
        if not (0 <= i < len(items)):
            return
        it = items[i]
        kind = self.tab
        text = it['text']
        m = tk.Menu(self.root, tearoff=0, bg=T['panel'], fg=T['fg'], bd=0,
                    activebackground=T['card_h'], activeforeground=T['fg'],
                    font=FONT, relief='flat')
        m.add_command(label='复制', command=lambda: clip_write(text))
        m.add_command(label='粘贴到上一窗口', command=lambda: self.paste(text, True, it['id']))
        m.add_command(label='粘贴为纯文本', command=lambda: self.paste_plain(it))
        m.add_separator()
        if kind == 'clip':
            m.add_command(label='＋ 存为常用语', command=lambda: self.save_as_phrase(text))
        else:
            m.add_command(label='✎ 编辑内容', command=lambda: self.edit_phrase(it['id']))
            m.add_command(label='🏷 命名', command=lambda: self.rename_phrase(it['id']))
        m.add_command(label='拆 拆词', command=lambda: self.split_words(text))
        m.add_command(label='🔧 文本变换', command=self.open_transform)
        m.add_command(label='★ 收藏' if not it.get('fav') else '☆ 取消收藏',
                      command=lambda: self.toggle_fav(it['id']))
        m.add_command(label='🕘 查看详情', command=lambda: self.show_detail(it))
        m.add_command(label='↗ 选中这条用于导出',
                      command=lambda: (self.vlist.multi.add(it['id']),
                                       self.vlist.update_view(),
                                       self.tip('已选 %d 条' % len(self.vlist.multi))))
        if it.get('sens'):
            m.add_command(label='👁 切换原文/打码', command=lambda: self.toggle_sens(it['id']))
        m.add_separator()
        m.add_command(label='✕ 删除', command=lambda: self.del_item(it['id'], kind))
        m.tk_popup(e.x_root, e.y_root)

    def on_hover_item(self, i, x, y):
        """F0：列表里默认不显示时间，悬停才给相对时间"""
        items = self.vlist.items
        if not (0 <= i < len(items)):
            return
        it = items[i]
        txt = '复制于 %s\n来源 %s\n%s' % (rel_time(it.get('created_at'), it.get('est')),
                                         it.get('app', 'unknown'), it.get('badge', ''))
        self.vlist.tip.show(txt, x, y)

    def toggle_fav(self, cid):
        pool = self.data['clip'] if self.tab == 'clip' else self.cur_group()['items']
        for x in pool:
            if x['id'] == cid:
                x['fav'] = 0 if x.get('fav') else 1
        self.save(True)
        self.render()

    def show_detail(self, it):
        """F0：隐藏时间戳的查询入口，三个时间语义不混用"""
        src = it.get('source_app') or 'unknown'
        body = '\n'.join([
            '首次复制：%s%s' % (full_time(it.get('created_at')),
                                '（估算值）' if it.get('is_estimated') else ''),
            '再次复制：%s（共 %s 次）' % (full_time(it.get('updated_at')),
                                        it.get('copy_count', 1)),
            '最近粘贴：%s' % full_time(it.get('last_used_at')),
            '来源应用：%s' % src,
            '窗口标题：%s' % (it.get('source_title') or '（未记录）'),
            '类型/大小：%s / %s（%d 字符）' % (it.get('content_type'),
                                            human_size(int(it.get('content_size') or 0)),
                                            len(it.get('text') or '')),
            '序号 seq：%s' % it.get('seq'),
            '',
            '内容预览：',
            preview(it.get('text'), 200),
        ])
        Dialog(self.root, '条目详情', [('', body, True)],
               on_ok=lambda v: None, ok_text='关闭').show(460, 380)

    def toggle_sens(self, cid):
        pool = self.data['clip'] if self.tab == 'clip' else self.cur_group()['items']
        for x in pool:
            if x['id'] == cid:
                x['mask_off'] = not x.get('mask_off')
        self.render()

    def set_num_hint(self, on):
        """按住 Ctrl 时在每行行首显示 1..9/0，把这组快捷键亮出来"""
        on = bool(on)
        if bool(getattr(self.vlist, 'show_num', False)) == on:
            return
        self.vlist.show_num = on
        self.vlist.update_view()

    def quick_paste(self, n):
        """Ctrl+1..9 / Ctrl+0：直接粘贴第 1..10 项，不必先按 ↑↓ 再回车。
        序号映射来自 PasteBar（index 9 显示成 0），下标减一取第 n 项。"""
        items = self.vlist.items
        if n > len(items):
            self.tip('当前列表只有 %d 条' % len(items))
            return 'break'
        it = items[n - 1]
        self.vlist.sel = it['id']
        if self.tab == 'clip':
            self.sel_clip = it['id']
        else:
            self.sel_phrase = it['id']
        self.vlist.update_view()
        self.paste(it.get('text') or '', cid=it['id'])
        return 'break'

    def paste(self, text, force=False, cid=None):
        """粘贴出去：只刷新 last_used_at，绝不改写 created_at"""
        if cid:
            pool = self.data['clip'] if self.tab == 'clip' else self.cur_group()['items']
            for x in pool:
                if x['id'] == cid:
                    x['last_used_at'] = now_ms()
                    break
            self.save(True)
        if not clip_write(text):
            self.tip('剪贴板被占用，写入失败')
            return False
        if (self.st['autopaste'] or force) and not self.hidden:
            hwnd = self.prev_hwnd
            self.root.withdraw()
            self.root.update()
            threading.Thread(target=self._paste_worker, args=(hwnd,), daemon=True).start()
            # 保险：万一后台线程没来得及恢复，1.5 秒后强制把面板叫回来
            self.root.after(1500, self._ensure_visible)
        return True

    def _ensure_visible(self):
        if not self.hidden and self.root.state() == 'withdrawn':
            self.root.deiconify()
            self.root.attributes('-topmost', True)
            if not self.ensure_onscreen():
                self.render()

    def _paste_worker(self, hwnd):
        """把焦点还给原窗口，再模拟 Ctrl+V。
        时序照 Ditto：① AttachThreadInput 绕过 Windows 的前台锁定；② **等**目标窗口真的
        拿到焦点再发键（Ditto WaitForActiveWnd），不再用固定 sleep —— 那个值在慢机器上
        不够、在快机器上白等；③ 发键前先抬掉残留修饰键（见 all_keys_up）。"""
        ok = False
        try:
            if hwnd:
                time.sleep(0.06)
                ok = force_foreground(hwnd, timeout=0.4)
                if ok:
                    time.sleep(0.05)        # 给目标程序处理 WM_SETFOCUS 的时间
                    send_ctrl_v()
        except Exception:
            ok = False
        time.sleep(0.12)
        self._need_show = True
        self._paste_fail = not ok

    def paste_plain_sel(self):
        items = self.vlist.items
        sel = self.sel_clip if self.tab == 'clip' else self.sel_phrase
        if not sel and items:
            sel = items[0]['id']
        for it in items:
            if it['id'] == sel:
                self.paste_plain(it)
                return
        self.tip('先选中一条再按 Ctrl+Shift+Enter')

    def paste_plain(self, it):
        """F6：粘贴为纯文本。三个坑全处理：不污染历史 / 还原焦点 / 失败降级提示"""
        text = to_plain(it.get('text') or '')
        if len(text.encode('utf-8')) > 5 * 1024 * 1024:
            clip_write(text)
            self.tip('文本超 5MB，已放入剪贴板，请手动 Ctrl+V')
            return
        if not self.paste(text, True, it.get('id')):
            self.tip('剪贴板被占用，已尝试复制，请手动 Ctrl+V')

    def move_sel(self, delta):
        items = self.vlist.items
        if not items:
            return
        sel = self.sel_clip if self.tab == 'clip' else self.sel_phrase
        cur = 0
        for i, it in enumerate(items):
            if it['id'] == sel:
                cur = i
                break
        nxt = min(len(items) - 1, max(0, cur + delta))
        tgt = items[nxt]['id']
        if self.tab == 'clip':
            self.sel_clip = tgt
        else:
            self.sel_phrase = tgt
        self.vlist.sel = tgt
        self.vlist.scroll_to_index(nxt)

    def enter_sel(self):
        items = self.vlist.items
        sel = self.sel_clip if self.tab == 'clip' else self.sel_phrase
        if not sel and items:
            sel = items[0]['id']
            if self.tab == 'clip':
                self.sel_clip = sel
            else:
                self.sel_phrase = sel
        for it in items:
            if it['id'] == sel:
                self.paste(it['text'], True, it['id'])
                return

    def del_item(self, cid, kind):
        if kind == 'clip':
            self.data['clip'] = [x for x in self.data['clip'] if x['id'] != cid]
            if self.sel_clip == cid:
                self.sel_clip = None
        else:
            g = self.cur_group()
            g['items'] = [x for x in g['items'] if x['id'] != cid]
            if self.sel_phrase == cid:
                self.sel_phrase = None
        self.save(True)
        self.render()

    def del_sel(self):
        cid = self.sel_clip if self.tab == 'clip' else self.sel_phrase
        if not cid:
            self.tip('先选中一条')
            return
        self.del_item(cid, self.tab)

    def clear_list(self):
        if self.tab == 'clip':
            favs = [x for x in self.data['clip'] if x.get('fav')] if self.st.get('keep_on_clear') else []

            def do_clear():
                self.data['clip'] = favs
                self.sel_clip = None
                self.save(True)
                self.render()
                self.tip('已清空，保留 %d 条收藏' % len(favs) if favs else '剪贴板历史已清空')
            extra = '，其中 %d 条收藏会保留' % len(favs) if favs else ''
            self.confirm('清空全部剪贴板历史？共 %d 条%s，不可撤销。' %
                         (len(self.data['clip']), extra), do_clear)
        else:
            g = self.cur_group()

            def do_clear():
                g['items'] = []
                self.sel_phrase = None
                self.save(True)
                self.render()
                self.tip('分组已清空')
            self.confirm('清空分组「%s」？共 %d 条，不可撤销。' %
                         (g['name'], len(g['items'])), do_clear)

    # ---------- 常用语 ----------
    def add_phrase(self):
        init = clip_read() or ''

        def done(v):
            if v and v[1].strip():
                self.push_phrase(v[0].strip(), v[1])
        Dialog(self.root, '新增常用语',
               [('名称（可留空）', '', False), ('内容', init, True)], on_ok=done).show(400, 300)

    def save_as_phrase(self, text):
        def done(v):
            if v and v[1].strip():
                self.push_phrase(v[0].strip(), v[1])
        Dialog(self.root, '存为常用语',
               [('名称（可留空）', preview(text, 20), False), ('内容', text, True)],
               on_ok=done).show(400, 300)

    def push_phrase(self, name, text):
        self.cur_group()['items'].insert(0, {'id': uid(), 'name': name, 'text': text})
        self.save(True)
        self.tab = 'phrase'
        self.render()

    def edit_phrase(self, cid):
        it = self.find(cid, 'phrase')
        if not it:
            return

        def done(v):
            if v and v[0].strip():
                it['text'] = v[0]
                self.save(True)
                self.render()
        Dialog(self.root, '编辑内容', [('内容', it['text'], True)], on_ok=done).show(400, 240)

    def rename_phrase(self, cid):
        it = self.find(cid, 'phrase')
        if not it:
            return

        def done(v):
            if v is not None:
                it['name'] = v[0].strip()
                self.save(True)
                self.render()
        Dialog(self.root, '命名', [('名称', it.get('name') or '', False)],
               on_ok=done).show(340)

    def find(self, cid, kind):
        pool = self.data['clip'] if kind == 'clip' else self.cur_group()['items']
        for it in pool:
            if it['id'] == cid:
                return it
        return None

    def find_raw_item(self, cid):
        """按 id 找真实数据条目（跨剪贴板与所有常用语分组）"""
        for x in self.data['clip']:
            if x.get('id') == cid:
                return x
        for g in self.data['groups']:
            for x in g.get('items', []):
                if x.get('id') == cid:
                    return x
        return None

    def split_words(self, text=None):
        if text is None:
            sel = self.sel_clip if self.tab == 'clip' else self.sel_phrase
            it = self.find(sel, self.tab) if sel else None
            text = it['text'] if it else (clip_read() or '')
        SplitDialog(self, text)

    # ---------- 设置 ----------
    def open_settings(self):
        SettingsWindow(self)

    # ---------- F3 搜索：历史 / 帮助 ----------
    def on_search_return(self, e=None):
        q = self.search.get().strip()
        if q:
            h = list(self.data.get('search_history') or [])
            if q in h:
                h.remove(q)
            h.insert(0, q)
            self.data['search_history'] = h[:10]
            self.save(True)
        self.enter_sel()
        return 'break'

    def search_menu(self, e):
        m = tk.Menu(self.root, tearoff=0, bg=T['panel'], fg=T['fg'], bd=0,
                    activebackground=T['card_h'], activeforeground=T['fg'],
                    font=FONT, relief='flat')
        hist = list(self.data.get('search_history') or [])[:10]
        if hist:
            for q in hist:
                m.add_command(label=q, command=lambda v=q: (self.search.set(v), self.render()))
        else:
            m.add_command(label='（暂无历史）', state='disabled')
        m.add_separator()
        m.add_command(label='导出当前结果…', command=self.open_export)
        m.add_command(label='语法帮助', command=self.open_query_help)
        m.add_command(label='清空搜索历史', command=self.clear_history)
        m.tk_popup(e.x_root, e.y_root)

    def clear_history(self):
        self.data['search_history'] = []
        self.search.set('')
        self.save(True)
        self.render()

    def select_all_visible(self, e=None):
        for it in self.vlist.items:
            self.vlist.multi.add(it['id'])
        self.vlist.update_view()
        self.tip('已全选 %d 条' % len(self.vlist.multi))
        return 'break'

    def open_query_help(self):
        body = '\n'.join('%-32s %s' % (a, b) for a, b in Q.SYNTAX_HELP)
        Dialog(self.root, '搜索语法', [('', body, True)],
               on_ok=lambda v: None, ok_text='知道了').show(540, 440)

    # ---------- F4 变换 / F5 导出 ----------
    def current_target_text(self):
        items = self.vlist.items
        sel = self.sel_clip if self.tab == 'clip' else self.sel_phrase
        for it in items:
            if it['id'] == sel:
                return it.get('text', ''), it
        if items:
            return items[0].get('text', ''), items[0]
        return clip_read() or '', None

    def open_transform(self):
        text, it = self.current_target_text()
        if not text:
            self.tip('没有可变换的内容')
            return
        TransformWindow(self, text, it)

    def open_export(self):
        ExportDialog(self)

    def rebuild(self):
        self.root.configure(bg=T['bg'])
        self.build_ui()
        self.render()
        self.root.after(120, self.render)

    # ---------- 托盘 ----------
    def tray_menu(self):
        m = tk.Menu(self.root, tearoff=0, bg=T['panel'], fg=T['fg'], bd=0,
                    activebackground=T['card_h'], activeforeground=T['fg'],
                    font=FONT, relief='flat')
        m.add_command(label='打开面板', command=self.toggle_show)
        m.add_command(label=('⏸ 暂停监听' if self.st['listen'] else '▶ 恢复监听'),
                      command=self.toggle_listen)
        m.add_command(label='⚙ 设置', command=self.open_settings)
        m.add_command(label='⟲ 面板找不到了？重置位置', command=self.reset_position)
        m.add_command(label='ℹ 关于', command=self.about)
        m.add_separator()
        m.add_command(label='✕ 退出', command=self.quit_app)
        try:
            m.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        except Exception:
            pass

    def toggle_listen(self):
        self.st['listen'] = not self.st['listen']
        self.save(True)
        self.tip('监听已暂停' if not self.st['listen'] else '监听已恢复')

    def about(self):
        Dialog(self.root, '关于 ' + APP_NAME,
               [('', '%s %s\n\n零依赖 Python / tkinter\n数据文件：%s\n\n唤起热键：%s' %
                 (APP_NAME, APP_VER, DATA_FILE, self.st['hotkey']), True)],
               on_ok=lambda v: None, ok_text='知道了').show(430, 260)

    # ---------- 循环 ----------
    def poll_clip(self):
        global LAST_SEQ
        if not self.st['listen']:
            LAST_SEQ = clip_seq()
            self.root.after(400, self.poll_clip)
            return
        try:
            seq = clip_seq()
            if seq != LAST_SEQ:
                LAST_SEQ = seq
                if self.st.get('smart_private', True) and clip_is_private():
                    # 密码管理器用这个标记告诉所有监听者「这条别记」
                    self.tip('这条带了「不要记录」标记，已跳过')
                else:
                    txt = clip_read()
                    if txt and txt.strip():
                        if len(txt) > MAX_TEXT:
                            txt = txt[:MAX_TEXT] + '\n…（内容超长已截断）'
                        hits = scan_sensitive(txt)
                        if hits and self.st['skip_sensitive']:
                            self.tip('检测到%s，按设置不入库' % '/'.join(hits))
                        else:
                            self.ingest(txt, hits)
        except Exception as e:
            self.note('监听异常：%s' % e)
        self.root.after(400, self.poll_clip)

    def next_seq(self):
        self._seq += 1
        return self._seq

    def ingest(self, txt, hits=None, manual=False):
        """入库：重复内容只刷新 updated_at / copy_count，created_at 永不改写。
        manual=True 是用户手动添加（拆词、变换存新条目），此时跳过忽略规则与长度过滤。"""
        ts = now_ms()
        # 不在这里做 50ms 延迟重试：那会卡住 UI 线程。抓不到就交给后台线程补抓。
        src, src_hwnd = capture_source(self.root.winfo_id(), delay_retry=False)
        # 只在真的要用标题时才去取（取标题是有开销的）
        title = None
        if src_hwnd and (self.st['record_title'] or (self.st.get('ignore_titles') or '').strip()):
            title = window_title_of(src_hwnd)
        if not manual:
            lo = int(self.st.get('min_len') or 0)
            hi = int(self.st.get('max_len') or 0)
            msg = length_filtered(txt, lo, hi)
            if msg:
                self.tip(msg)
                return
            hit = match_ignore(src, title, self.st.get('ignore_apps'),
                               self.st.get('ignore_titles'))
            if hit:
                self.tip('命中忽略规则（%s），未记录' % hit)
                return
        dup = None
        for x in self.data['clip']:
            if x.get('text') == txt:
                dup = x
                break
        if dup is not None:
            dup['copy_count'] = int(dup.get('copy_count') or 1) + 1
            dup['updated_at'] = ts
            dup['time'] = now_str()
            if src != 'unknown':
                dup['source_app'] = src
            self.data['clip'].remove(dup)
            self.data['clip'].insert(0, dup)
        else:
            exist = [int(x.get('created_at') or 0) for x in self.data['clip']]
            mx = max(exist) if exist else 0
            if ts < mx:
                self.note('系统时钟回拨（新 %d < 库中最大 %d），本次用 seq 兜底排序' % (ts, mx))
                ts = mx + 1
            rec = {'id': uid(), 'text': txt, 'created_at': ts, 'updated_at': ts,
               'seq': self.next_seq(), 'source_app': src,
               'content_type': detect_content_type(txt),
               'content_size': byte_size(txt), 'copy_count': 1, 'fav': 0,
               'is_estimated': 0}
        # 空值字段一律不落盘：1 万条能省下 MB 级内存与文件体积
        if title and self.st['record_title']:
            rec['source_title'] = title
        if hits:
            rec['sens'] = hits
        self.data['clip'].insert(0, rec)
        if src == 'unknown':
            threading.Thread(target=self._late_source, args=(rec['id'],),
                             daemon=True).start()
        lim = int(self.st['max_items'])
        if len(self.data['clip']) > lim:
            self.data['clip'] = crop_items(self.data['clip'], lim)
        self.save(True)
        if self.tab == 'clip':
            self.render()

    def _late_source(self, rid):
        """后台补抓来源：竞态下第一次可能抓到自己或抓空，50ms 后再试一次"""
        time.sleep(0.05)
        src, hwnd = capture_source(self.root.winfo_id(), delay_retry=False)
        if src == 'unknown':
            return
        for x in self.data['clip']:
            if x.get('id') == rid:
                x['source_app'] = src
                if self.st.get('record_title') and hwnd:
                    t = window_title_of(hwnd)
                    if t:
                        x['source_title'] = t
                break
        else:
            return
        self.save(True)
        try:
            self.root.after(0, self.render)
        except Exception:
            pass


class SettingsWindow:
    HKS = [('Ctrl+Shift+V（默认）', 'ctrl+shift+v'), ('Alt+V', 'alt+v'),
           ('Ctrl+Alt+V', 'ctrl+alt+v'), ('不启用', 'none')]

    def __init__(self, app):
        self.app = app
        st = app.st
        self.win = tk.Toplevel(app.root)
        self.win.transient(app.root)
        dark_top(self.win, '设置')
        self.win.attributes('-topmost', True)
        self.win.after(60, lambda: (self.win.lift(), self.win.focus_force()))
        # 内容放进可滚动容器：选项变多了也不怕窗口装不下
        self.sc = ScrollFrame(self.win)
        self.sc.pack(fill='both', expand=True, padx=(14, 8), pady=(10, 0))
        body = self.sc.inner
        self.row_switch(body, '监听剪贴板', 'listen')
        self.row_switch(body, '单击后自动粘贴到上一窗口', 'autopaste')
        self.row_switch(body, '敏感内容打码显示', 'mask_sensitive')
        self.row_switch(body, '敏感内容不入库', 'skip_sensitive')
        self.row_switch(body, '列表中显示时间', 'show_time')
        self.row_switch(body, '记录来源窗口标题（隐私）', 'record_title')
        self.row_switch(body, '靠边自动隐藏（贴屏幕边缘自动收起）', 'edge_hide')
        self.row_autostart_switch(body)
        self.row_close_action(body)
        self.row_theme(body)
        self.row_hotkey(body)
        self.row_int(body, '历史最大条数（10-5000）', 'max_items')
        self.row_int(body, '捕获长度下限（0=不限）', 'min_len', lo=0, hi=1000)
        self.row_int(body, '捕获长度上限（0=不限）', 'max_len', lo=0, hi=200000, width=9)
        self.row_switch(body, '遵守「别记录我」标记（密码管理器用）', 'smart_private')
        self.row_switch(body, '清空历史时保留收藏项', 'keep_on_clear')
        self.row_text(body, '忽略这些程序（逗号分隔，支持 * ?）', 'ignore_apps',
                      '例：keepass, *bitwarden*, 微信')
        self.row_text(body, '忽略标题匹配的窗口（正则，分号分隔）', 'ignore_titles',
                      '例：密码; Password; ^私密')
        btns = tk.Frame(self.win, bg=T['bg'])    # 固定在窗口底部，不跟着内容滚
        btns.pack(fill='x', padx=14, pady=(8, 10))
        b = tk.Label(btns, text='关闭', bg=T['acc'], fg='#fff', font=FONT_B,
                     padx=16, pady=5, cursor='hand2')
        b.pack(side='right')
        b.bind('<Button-1>', lambda e: (app.save(True), safe_release(self.win),
                                        self.win.destroy()))
        q = tk.Label(btns, text='退出程序', bg=T['danger'], fg='#fff', font=FONT_B,
                     padx=14, pady=5, cursor='hand2')
        q.pack(side='left')
        q.bind('<Button-1>', lambda e: (app.save(True), safe_release(self.win),
                                        self.win.destroy(), app.quit_app()))
        self.win.bind('<Escape>', lambda e: (safe_release(self.win), self.win.destroy()))
        self.sc.bind_wheel_tree()          # 所有子控件接管滚轮
        center_on(self.win, app.root, 380, 470)
        self.win.after(80, self.sc._on_inner)

    def row_close_action(self, master):
        """点 ✕ 的行为：默认隐藏到托盘，也可改成直接退出"""
        r = tk.Frame(master, bg=T['bg'])
        r.pack(fill='x', pady=3)
        tk.Label(r, text='点标题栏 ✕ 时', bg=T['bg'], fg=T['fg'], font=FONT,
                 anchor='w').pack(side='left')
        lb = tk.Label(r, text='', bg=T['card'], fg=T['fg'], font=FONT_SM,
                      padx=8, pady=2, cursor='hand2')
        lb.pack(side='right')

        def paint():
            v = self.app.st.get('close_action', 'hide')
            lb.configure(text='隐藏到托盘' if v == 'hide' else '直接退出程序')

        def setv(val):
            self.app.st['close_action'] = val
            self.app.save(True)
            paint()
            self.app.tip('✕ 现在会%s' % ('隐藏到托盘' if val == 'hide' else '直接退出'))

        def menu(_=None):
            m = tk.Menu(self.win, tearoff=0, bg=T['panel'], fg=T['fg'], bd=0,
                        activebackground=T['card_h'], activeforeground=T['fg'],
                        font=FONT, relief='flat')
            m.add_command(label='隐藏到托盘（继续后台监听）', command=lambda: setv('hide'))
            m.add_command(label='直接退出程序', command=lambda: setv('quit'))
            m.tk_popup(lb.winfo_rootx(), lb.winfo_rooty() + lb.winfo_height())
        lb.bind('<Button-1>', menu)
        paint()

    def row_switch(self, master, text, key):
        r = tk.Frame(master, bg=T['bg'])
        r.pack(fill='x', pady=3)
        tk.Label(r, text=text, bg=T['bg'], fg=T['fg'], font=FONT, anchor='w').pack(side='left')
        st = self.app.st
        lb = tk.Label(r, text='', bg=T['card'], font=FONT_B, width=6, cursor='hand2')
        lb.pack(side='right')

        def paint():
            on = bool(st.get(key))
            lb.configure(text='开' if on else '关',
                         fg='#fff' if on else T['fg2'],
                         bg=T['acc'] if on else T['card'])

        def toggle(_=None):
            st[key] = not st.get(key)
            paint()
            self.app.save(True)
        lb.bind('<Button-1>', toggle)
        paint()

    def row_theme(self, master):
        r = tk.Frame(master, bg=T['bg'])
        r.pack(fill='x', pady=3)
        tk.Label(r, text='主题', bg=T['bg'], fg=T['fg'], font=FONT).pack(side='left')
        for name, label in (('dark', '暗色'), ('light', '亮色')):
            lb = tk.Label(r, text=label, bg=T['card'], fg=T['fg'], font=FONT,
                          padx=8, pady=2, cursor='hand2')
            lb.pack(side='right', padx=2)
            lb.bind('<Button-1>', lambda e, n=name: self.set_theme(n))

    def set_theme(self, name):
        self.app.st['theme'] = name
        self.app.save(True)
        set_theme(name)
        self.app.rebuild()
        safe_release(self.win)
        self.win.destroy()

    def row_hotkey(self, master):
        r = tk.Frame(master, bg=T['bg'])
        r.pack(fill='x', pady=3)
        tk.Label(r, text='全局唤起热键', bg=T['bg'], fg=T['fg'], font=FONT).pack(side='left')
        cur = [l for l, v in self.HKS if v == self.app.st.get('hotkey')]
        lb = tk.Label(r, text=cur[0] if cur else '未设置', bg=T['card'], fg=T['fg'],
                      font=FONT_SM, padx=8, pady=2, cursor='hand2')
        lb.pack(side='right')
        lb.bind('<Button-1>', lambda e: self.hk_menu(lb))

    def hk_menu(self, anchor):
        m = tk.Menu(self.win, tearoff=0, bg=T['panel'], fg=T['fg'], bd=0,
                    activebackground=T['card_h'], activeforeground=T['fg'],
                    font=FONT, relief='flat')
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
        r.pack(fill='x', pady=3)
        tk.Label(r, text=text, bg=T['bg'], fg=T['fg'], font=FONT).pack(side='left')
        v = tk.StringVar(value=str(self.app.st.get(key)))
        e = tk.Entry(r, textvariable=v, bg=T['card'], fg=T['fg'], insertbackground=T['fg'],
                     relief='flat', font=FONT, bd=0, width=width, justify='right',
                     highlightthickness=1, highlightbackground=T['line'],
                     highlightcolor=T['acc'])
        e.pack(side='right')

        def commit(_=None):
            try:
                n = min(hi, max(lo, int(v.get())))
            except Exception:
                n = int(DEFAULT_SETTINGS[key])
            self.app.st[key] = n
            v.set(str(n))
            self.app.save(True)
        e.bind('<Return>', commit)
        e.bind('<FocusOut>', commit)

    def row_text(self, master, text, key, hint=''):
        """文本型设置：忽略名单这类可能写很长，占一整行，回车或失焦时提交"""
        r = tk.Frame(master, bg=T['bg'])
        r.pack(fill='x', pady=3)
        tk.Label(r, text=text, bg=T['bg'], fg=T['fg'], font=FONT,
                 anchor='w').pack(fill='x')
        if hint:
            tk.Label(r, text=hint, bg=T['bg'], fg=T['fg2'], font=FONT_SM,
                     anchor='w').pack(fill='x')
        v = tk.StringVar(value=str(self.app.st.get(key) or ''))
        e = tk.Entry(r, textvariable=v, bg=T['card'], fg=T['fg'], insertbackground=T['fg'],
                     relief='flat', font=FONT_SM, bd=0, highlightthickness=1,
                     highlightbackground=T['line'], highlightcolor=T['acc'])
        e.pack(fill='x', ipady=3, pady=(2, 0))

        def commit(_=None):
            self.app.st[key] = v.get().strip()
            self.app.save(True)
        e.bind('<Return>', commit)
        e.bind('<FocusOut>', commit)
        return e

    def row_autostart_switch(self, master):
        """开机自启：直接读写当前用户注册表 Run 项，状态以注册表真实值为准"""
        r = tk.Frame(master, bg=T['bg'])
        r.pack(fill='x', pady=3)
        tk.Label(r, text='开机自启（写当前用户注册表，可随时关）', bg=T['bg'],
                 fg=T['fg'], font=FONT, anchor='w').pack(side='left')
        lb = tk.Label(r, text='', bg=T['card'], font=FONT_B, width=6, cursor='hand2')
        lb.pack(side='right')

        def paint():
            on, _ = get_autostart()
            lb.configure(text='开' if on else '关',
                         fg='#fff' if on else T['fg2'],
                         bg=T['acc'] if on else T['card'])

        def toggle(_=None):
            on, _ = get_autostart()
            ok = set_autostart(not on)
            paint()
            if not ok:
                self.app.tip('开机自启设置失败（注册表不可写）')
            else:
                self.app.tip('开机自启已开启' if not on else '开机自启已关闭')
        lb.bind('<Button-1>', toggle)
        paint()

        r2 = tk.Frame(master, bg=T['bg'])
        r2.pack(fill='x', pady=(0, 4))
        b = tk.Label(r2, text='不想改注册表？点这里打开启动文件夹手动放快捷方式',
                     bg=T['bg'], fg=T['fg2'], font=FONT_SM, cursor='hand2', anchor='w')
        b.pack(anchor='w')
        b.bind('<Button-1>', lambda e: self.open_startup())

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


class TransformWindow:
    """F4：左侧选变换，右侧看结果，底部三个动作。>5MB 走异步，不卡 UI"""

    def __init__(self, app, text, item=None):
        self.app = app
        self.item = item
        self.win = tk.Toplevel(app.root)
        self.win.transient(app.root)
        dark_top(self.win, '文本变换')
        self.win.attributes('-topmost', True)
        self.win.after(60, lambda: (self.win.lift(), self.win.focus_force()))
        mid = tk.Frame(self.win, bg=T['bg'])
        mid.pack(fill='both', expand=True, padx=10, pady=6)

        lf = tk.Frame(mid, bg=T['bg'])
        lf.pack(side='left', fill='y')
        self.lb = tk.Listbox(lf, bg=T['card'], fg=T['fg'], bd=0, relief='flat',
                             highlightthickness=1, highlightbackground=T['line'],
                             selectbackground=T['acc'], font=FONT_SM,
                             width=20, height=20)
        sb = ThinBar(lf, lambda f: self.lb.yview_moveto(f), width=8)
        self.lb.configure(yscrollcommand=sb.set)
        self.lb.pack(side='left', fill='y')
        sb.pack(side='left', fill='y', padx=(2, 0))
        # Windows 的 Tk Listbox 自带没有任何滚轮绑定，必须自己接管
        self.lb.bind('<MouseWheel>', self.lb_wheel)
        for _, label, _ in tx().TRANSFORMS:
            self.lb.insert('end', label)
        self.lb.bind('<<ListboxSelect>>', lambda e: self.run())

        rf = tk.Frame(mid, bg=T['bg'])
        rf.pack(side='left', fill='both', expand=True, padx=(10, 0))
        tk.Label(rf, text='原文', bg=T['bg'], fg=T['fg2'], font=FONT_SM,
                 anchor='w').pack(fill='x')
        self.src = tk.Text(rf, height=9, bg=T['card'], fg=T['fg'],
                           insertbackground=T['fg'], relief='flat', font=FONT_SM,
                           wrap='word', bd=0, highlightthickness=1,
                           highlightbackground=T['line'], highlightcolor=T['acc'])
        self.src.insert('1.0', text[:200000])
        self.src.pack(fill='both', expand=True)
        tk.Label(rf, text='结果', bg=T['bg'], fg=T['fg2'], font=FONT_SM,
                 anchor='w').pack(fill='x')
        self.out = tk.Text(rf, height=9, bg=T['card'], fg=T['fg'],
                           insertbackground=T['fg'], relief='flat', font=FONT_SM,
                           wrap='word', bd=0, highlightthickness=1,
                           highlightbackground=T['line'], highlightcolor=T['acc'])
        self.out.pack(fill='both', expand=True)

        btns = tk.Frame(self.win, bg=T['bg'])
        btns.pack(fill='x', padx=10, pady=(0, 10))
        for label, cmd in (('复制到剪贴板', self.copy_out),
                           ('存为新条目', self.save_new),
                           ('覆盖原条目', self.overwrite)):
            b = tk.Label(btns, text=label, bg=T['card'], fg=T['fg'], font=FONT,
                         padx=10, pady=5, cursor='hand2')
            b.pack(side='left', padx=3)
            b.bind('<Button-1>', lambda e, c=cmd: c())
        b = tk.Label(btns, text='关闭', bg=T['acc'], fg='#fff', font=FONT_B,
                     padx=14, pady=5, cursor='hand2')
        b.pack(side='right')
        b.bind('<Button-1>', lambda e: (safe_release(self.win), self.win.destroy()))
        self.win.bind('<Escape>', lambda e: (safe_release(self.win), self.win.destroy()))
        center_on(self.win, app.root, 760, 540)

    def lb_wheel(self, e):
        """变换列表的滚轮：同样按 1/120 格累积，触控板不丢事件"""
        d = getattr(e, 'delta', 0)
        if not d:
            return 'break'
        self._acc = getattr(self, '_acc', 0.0) + d / 120.0
        steps = int(self._acc)
        if not steps:
            return 'break'
        self._acc -= steps
        self.lb.yview_scroll(-steps * WHEEL_LINES, 'units')
        return 'break'

    def run(self):
        sel = self.lb.curselection()
        if not sel:
            return
        key = tx().TRANSFORMS[int(sel[0])][0]
        src = self.src.get('1.0', 'end-1c')
        if len(src.encode('utf-8')) > 5 * 1024 * 1024:
            self.out.delete('1.0', 'end')
            self.out.insert('1.0', '内容超过 5MB，后台处理中…')
            threading.Thread(target=self._work, args=(key, src), daemon=True).start()
        else:
            self._work(key, src)

    def _work(self, key, src):
        try:
            res, err = tx().apply(key, src), None
        except Exception as e:
            res, err = '', str(e)
        try:
            self.win.after(0, lambda: self._show(res, err))
        except Exception:
            pass

    def _show(self, res, err):
        self.out.delete('1.0', 'end')
        if err:
            self.out.configure(fg=T['danger'])
            self.out.insert('1.0', '变换失败：' + err)
        else:
            self.out.configure(fg=T['fg'])
            self.out.insert('1.0', res[:500000])

    def _out_text(self):
        t = self.out.get('1.0', 'end-1c')
        if not t:
            self.app.tip('先选一个变换')
            return None
        return t

    def copy_out(self):
        t = self._out_text()
        if t is not None:
            clip_write(t)
            self.app.tip('结果已复制到剪贴板')

    def save_new(self):
        t = self._out_text()
        if t is None:
            return
        self.app.tab = 'clip'
        self.app.ingest(t)
        self.app.tip('已存为新条目（原条目保留）')

    def overwrite(self):
        t = self._out_text()
        if t is None:
            return
        raw = self.app.find_raw_item(self.item['id']) if self.item else None
        if not raw:
            self.app.tip('没有可覆盖的原条目，请用「存为新条目」')
            return
        raw['text'] = t
        raw['content_size'] = byte_size(t)
        raw['content_type'] = detect_content_type(t)
        raw['updated_at'] = now_ms()      # created_at 原样保留
        self.app.save(True)
        self.app.render()
        self.app.tip('已覆盖原条目（首次复制时间未改）')


class ExportDialog:
    """F5：把历史导出成 TXT / CSV / JSON / Markdown"""

    def __init__(self, app):
        self.app = app
        ids = set(app.vlist.multi)
        items = [x for x in app.vlist.items if x['id'] in ids] if ids else list(app.vlist.items)
        self.items = items
        if not items:
            app.tip('没有可导出的内容')
            return
        self.win = tk.Toplevel(app.root)
        self.win.transient(app.root)
        dark_top(self.win, '批量导出')
        self.win.attributes('-topmost', True)
        self.win.after(60, lambda: (self.win.lift(), self.win.focus_force()))
        body = tk.Frame(self.win, bg=T['bg'])
        body.pack(fill='both', expand=True, padx=14, pady=10)
        tk.Label(body, text='共 %d 条待导出（多选优先，否则导出当前筛选结果）'
                 % len(items), bg=T['bg'], fg=T['fg'], font=FONT, anchor='w').pack(fill='x')
        self.fmt = tk.StringVar(value='txt')
        self.rows = []
        for v, label in (('txt', 'TXT（序号/时间/来源/内容）'),
                         ('csv', 'CSV（Excel 友好，带 BOM）'),
                         ('json', 'JSON（完整字段，可再导入）'),
                         ('md', 'Markdown（适合归档笔记）')):
            r = tk.Frame(body, bg=T['bg'])
            r.pack(fill='x', pady=2)
            dot = tk.Label(r, text='○', bg=T['bg'], fg=T['fg2'], font=FONT, cursor='hand2')
            dot.pack(side='left')
            tk.Label(r, text=label, bg=T['bg'], fg=T['fg'], font=FONT_SM,
                     cursor='hand2').pack(side='left')

            def pick(_, v=v):
                self.fmt.set(v)
                self.paint()
            for w in (dot, r):
                w.bind('<Button-1>', pick)
            r._dot = dot
            r._v = v
            self.rows.append(r)
        self.paint()
        sens = sum(1 for x in items if x.get('sens'))
        if sens:
            tk.Label(body, text='⚠ 其中 %d 条含敏感内容，导出为明文' % sens,
                     bg=T['bg'], fg=T['danger'], font=FONT_SM, anchor='w').pack(fill='x', pady=4)
        btns = tk.Frame(body, bg=T['bg'])
        btns.pack(fill='x', pady=(8, 0))
        b = tk.Label(btns, text='导出到本目录', bg=T['acc'], fg='#fff', font=FONT_B,
                     padx=14, pady=5, cursor='hand2')
        b.pack(side='right')
        b.bind('<Button-1>', lambda e: self.do_export())
        b2 = tk.Label(btns, text='取消', bg=T['card_h'], fg=T['fg'], font=FONT,
                      padx=14, pady=5, cursor='hand2')
        b2.pack(side='right', padx=(0, 6))
        b2.bind('<Button-1>', lambda e: (safe_release(self.win), self.win.destroy()))
        center_on(self.win, app.root, 480, 340)

    def paint(self):
        cur = self.fmt.get()
        for r in self.rows:
            r._dot.configure(text='●' if r._v == cur else '○',
                             fg=T['acc'] if r._v == cur else T['fg2'])

    def do_export(self):
        fmt = self.fmt.get()
        stamp = time.strftime('%Y%m%d-%H%M%S')
        path = os.path.join(BASE_DIR, '导出_%s.%s' % (stamp, fmt if fmt != 'md' else 'md'))
        tmp = path + '.tmp'
        raw = [self.app.find_raw_item(x['id']) for x in self.items]
        raw = [x for x in raw if x]
        try:
            if fmt == 'txt':
                lines = []
                for i, it in enumerate(raw, 1):
                    lines.append('[%d] %s | %s | %s\n%s\n' % (
                        i, full_time(it.get('created_at')),
                        it.get('source_app') or 'unknown',
                        it.get('content_type') or 'text', it.get('text', '')))
                data = '\n'.join(lines).encode('utf-8')
            elif fmt == 'csv':
                import csv
                import io
                buf = io.StringIO()
                w = csv.writer(buf)
                w.writerow(['时间(本地)', '来源应用', '类型', '大小(字节)', '内容'])
                for it in raw:
                    w.writerow([full_time(it.get('created_at')),
                                it.get('source_app') or 'unknown',
                                it.get('content_type') or 'text',
                                it.get('content_size') or 0,
                                it.get('text', '').replace('\n', '\\n')])
                data = buf.getvalue().encode('utf-8-sig')     # BOM 防 Excel 中文乱码
            elif fmt == 'json':
                data = json.dumps({'version': SCHEMA_VERSION, 'items': raw},
                                  ensure_ascii=False, indent=1).encode('utf-8')
            else:
                lines = ['# 剪贴板导出 %s\n' % time.strftime('%F %T')]
                for it in raw:
                    lines.append('## %s · %s\n\n```\n%s\n```\n' % (
                        full_time(it.get('created_at')),
                        it.get('source_app') or 'unknown', it.get('text', '')))
                data = '\n'.join(lines).encode('utf-8')
            with open(tmp, 'wb') as f:
                f.write(data)
            os.replace(tmp, path)          # 先写 tmp 再改名，不留半截文件
        except Exception as e:
            self.app.note('导出失败：%s' % e)
            self.app.tip('导出失败：%s' % e)
            return
        self.app.tip('已导出 %d 条 → %s' % (len(raw), os.path.basename(path)))
        safe_release(self.win)
        self.win.destroy()


# ---------------- 崩溃兜底 ----------------
def install_excepthook():
    def hook(etype, val, tb):
        try:
            with open(CRASH_LOG, 'a', encoding='utf-8') as f:
                f.write('\n==== 未捕获异常 %s ====\n' % time.strftime('%F %T'))
                f.write(''.join(traceback.format_exception(etype, val, tb)))
        except Exception:
            pass
        sys.__excepthook__(etype, val, tb)
    sys.excepthook = hook


def tk_error(root):
    def cb(exc, val, tb):
        try:
            with open(CRASH_LOG, 'a', encoding='utf-8') as f:
                f.write('\n==== Tk 回调异常 %s ====\n' % time.strftime('%F %T'))
                f.write(''.join(traceback.format_exception(exc, val, tb)))
        except Exception:
            pass
    root.report_callback_exception = cb


# ---------------- 9. 入口 ----------------
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


def bench():
    """性能实测：跑完输出真实数字后退出（压测数据绝不落盘）"""
    import random
    import string
    global NO_SAVE
    NO_SAVE = True       # 必须在建实例之前：__init__ 里就会 save 一次（曾经漏了这条，热键被改掉）
    root = tk.Tk()
    app = ClawBoard(root)
    root.geometry('340x480+-2000+-2000')   # 移出屏幕但保持 mapped，保证布局真实
    root.update()
    print('启动到可响应: %.0f ms' % ((time.time() - app.t0) * 1000))
    print('初始常驻内存: %.1f MB' % mem_mb())

    base = ''.join(random.choice(string.ascii_letters + '测试中文') for _ in range(60))
    n = 10000
    t0 = time.time()
    for i in range(n):
        app.data['clip'].append({'id': uid(), 'text': base + str(i), 'time': now_str()})
    print('灌入 %d 条耗时: %.0f ms' % (n, (time.time() - t0) * 1000))

    t0 = time.time()
    app.render()
    root.update()
    print('%d 条首次渲染: %.0f ms' % (n, (time.time() - t0) * 1000))

    t0 = time.time()
    for _ in range(30):
        app.vlist.yview_step(60)
        app.vlist.update_view()
        root.update()
    print('滚动刷新 x30 平均: %.2f ms/次' % ((time.time() - t0) / 30 * 1000))

    t0 = time.time()
    for i in range(200):
        app.search.set(str(random.randint(0, n)))
        app.render()
    print('普通搜索 200 次平均: %.2f ms/次' % ((time.time() - t0) / 200 * 1000))

    t0 = time.time()
    for i in range(50):
        app.search.set('app:chrome size:>10 time:<1d')
        app.render()
    print('高级语法搜索 50 次平均: %.2f ms/次' % ((time.time() - t0) / 50 * 1000))
    app.search.set('')
    app.render()

    c0 = cpu_ms()
    w0 = time.time()
    time.sleep(3)
    print('空闲 3 秒 CPU 占用: %.2f %%' % ((cpu_ms() - c0) / ((time.time() - w0) * 10.0)))
    print('%d 条后内存: %.1f MB' % (n, mem_mb()))
    print('虚拟列表实际 widget 数: %d / %d 条' % (len(app.vlist.pool), n))
    # 压测数据绝不落盘：直接销毁，不走 save()
    try:
        app.hw.unreg_hotkey()
        app.hw.tray_del()
        app.hw.stop()
    except Exception:
        pass
    app.root.destroy()


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    install_excepthook()
    if '--bench' in sys.argv:
        bench()
        return
    if not single_instance():
        sys.exit(0)
    root = tk.Tk()
    tk_error(root)
    app = ClawBoard(root)
    app.note('%s v%s 启动（热键 %s，pid %d）' % (APP_NAME, APP_VER, app.st['hotkey'],
                                                os.getpid()))
    root.mainloop()


if __name__ == '__main__':
    main()
