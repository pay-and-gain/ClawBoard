# -*- coding: utf-8 -*-
"""Win32 ctypes 声明 + 系统原语 + 单实例 + 开机自启。

唯一承载点：
- 坑③ DPI 声明：init_dpi_awareness()，读窗口坐标/测量前必须调用。
- 单实例互斥、进程/窗口/显示器/内存统计、发键/前台切换、开机自启都在本模块。
"""
import ctypes
import os
import sys
import time
import winreg
from ctypes import wintypes

from clawboard.config import APP_NAME, BASE_DIR

u32 = ctypes.WinDLL('user32', use_last_error=True)
k32 = ctypes.WinDLL('kernel32', use_last_error=True)
psapi = ctypes.WinDLL('psapi')
advapi = ctypes.WinDLL('advapi32', use_last_error=True)

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


# ---------------- WM_PASTE 直接投递（面板不用让位、不抢焦点） ----------------
WM_PASTE = 0x0302
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TOKEN_INTEGRITY_LEVEL = 25
SECURITY_MANDATORY_HIGH_RID = 0x3000   # 12288


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('flags', wintypes.DWORD),
                ('hwndActive', wintypes.HWND), ('hwndFocus', wintypes.HWND),
                ('hwndCapture', wintypes.HWND), ('hwndMenuOwner', wintypes.HWND),
                ('hwndMoveSize', wintypes.HWND), ('hwndCaret', wintypes.HWND),
                ('rcCaret', wintypes.RECT)]


u32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)]
u32.GetGUIThreadInfo.restype = wintypes.BOOL
u32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                             wintypes.LPARAM]
u32.SendMessageW.restype = ctypes.c_ssize_t
k32.GetCurrentProcessId.restype = wintypes.DWORD
advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                    ctypes.POINTER(wintypes.HANDLE)]
advapi.OpenProcessToken.restype = wintypes.BOOL
advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                       wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
advapi.GetTokenInformation.restype = wintypes.BOOL


def target_focus_hwnd(hwnd_top):
    """目标窗口里真正持有焦点的控件（输入框）。发 WM_PASTE 要发给它，不是顶层窗口。"""
    hwnd_top = int(hwnd_top or 0)
    if not hwnd_top:
        return 0
    try:
        tid = u32.GetWindowThreadProcessId(hwnd_top, None)
        if not tid:
            return hwnd_top
        gti = GUITHREADINFO()
        gti.cbSize = ctypes.sizeof(GUITHREADINFO)
        if u32.GetGUIThreadInfo(tid, ctypes.byref(gti)) and gti.hwndFocus:
            return int(gti.hwndFocus)
    except Exception:
        pass
    return hwnd_top


def _pid_integrity(pid):
    """进程完整性级别 RID（0x1000 低 / 0x2000 中 / 0x3000 高 / 0x4000 系统）。
    拿不到返回 None。"""
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        tok = wintypes.HANDLE()
        if not advapi.OpenProcessToken(h, TOKEN_QUERY, ctypes.byref(tok)):
            return None
        try:
            need = wintypes.DWORD()
            advapi.GetTokenInformation(tok, TOKEN_INTEGRITY_LEVEL, None, 0,
                                       ctypes.byref(need))
            if not need.value:
                return None
            buf = ctypes.create_string_buffer(need.value)
            if not advapi.GetTokenInformation(tok, TOKEN_INTEGRITY_LEVEL, buf,
                                              need.value, ctypes.byref(need)):
                return None
            # TOKEN_MANDATORY_LABEL = { PSID Label; DWORD Attributes; }
            # SID 布局：Revision(1) SubAuthorityCount(1) Authority(6) SubAuthority[n]
            sid_addr = ctypes.c_void_p.from_buffer(buf, 0).value
            if not sid_addr:
                return None
            sub_cnt = ctypes.c_ubyte.from_address(sid_addr + 1).value
            return ctypes.c_uint32.from_address(
                sid_addr + 8 + (sub_cnt - 1) * 4).value
        finally:
            k32.CloseHandle(tok)
    finally:
        k32.CloseHandle(h)


def _integrity_of(hwnd):
    hwnd = int(hwnd or 0)
    if not hwnd:
        return None
    try:
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return _pid_integrity(pid.value)
    except Exception:
        return None


def is_elevated_hwnd(hwnd):
    """目标进程完整性级别是否高于本进程（UAC 高权限窗口）。

    UIPI 会静默拦截发往更高完整性进程的 SendMessage / SendInput，WM_PASTE 无效，
    检测到就得退回「抢焦点 + 模拟 Ctrl+V」（同样可能被拦，但至少有失败提示）。
    """
    me = _pid_integrity(k32.GetCurrentProcessId())
    target = _integrity_of(hwnd)
    if target is None:
        return False                    # 拿不到就当不是，走正常路径
    if me is None:
        return target >= SECURITY_MANDATORY_HIGH_RID
    return target > me


def paste_message(hwnd_top):
    """用 WM_PASTE 直接投递到目标窗口的焦点控件，不抢焦点、面板不动。
    返回 True 表示已发送（不代表目标一定处理）。标准 Edit/RichEdit 可靠，
    浏览器/Electron 一般能透传；高权限窗口会被 UIPI 拦（先 is_elevated_hwnd 判断）。"""
    focus = target_focus_hwnd(hwnd_top)
    if not focus:
        return False
    try:
        u32.SendMessageW(focus, WM_PASTE, 0, 0)
        return True
    except Exception:
        return False


# 只有这些原生编辑控件才 100% 处理 WM_PASTE；其余（浏览器/Electron/UWP/自绘）别赌。
EDIT_CLASSES = ('edit', 'richedit20a', 'richedit20w', 'richedit50w',
                'richedit', 'richeditd2dpt')


def _focus_class_name(hwnd):
    cls = ctypes.create_unicode_buffer(256)
    u32.GetClassNameW(hwnd, cls, 256)
    return cls.value.lower()


def can_paste_message(hwnd_top):
    """目标窗口能否安全地用 WM_PASTE 投递（面板完全不动）。

    只有「焦点控件是标准 Edit/RichEdit 且非高权限窗口」才返回 True ——
    这两条能保证 WM_PASTE 一定生效。其它情况退回抢焦点路径。"""
    if is_elevated_hwnd(hwnd_top):
        return False                    # UIPI 会拦，投了也是白投
    focus = target_focus_hwnd(hwnd_top)
    if not focus:
        return False
    return _focus_class_name(focus) in EDIT_CLASSES


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
        dpi = ctypes.windll.user32.GetDpiForSystem()   # Win10 1607+ / Win11
        if dpi:
            return int(dpi)
    except Exception:
        pass
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)   # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(0, hdc)
        if dpi:
            return int(dpi)
    except Exception:
        pass
    return 96


def dpi_scale(root):
    """当前屏幕相对 100% 的缩放系数（96 DPI=1.0，120 DPI=1.25）。

    用 Win32 GetDpiForSystem 直读系统 DPI，不读 tk scaling —— 后者在 frozen 下
    会延迟生效，且已被 UI 缩放（config.UI_SCALE）改写，读它会双重缩放/误判。
    """
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
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
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


# ---------------- 窗口外观：圆角 + Acrylic 毛玻璃 ----------------
# 实验结论（本机 Win11 实测）：
#   · 圆角 (DWMWA_WINDOW_CORNER_PREFERENCE=33) —— 有效，方角变圆角
#   · Acrylic (SetWindowCompositionAttribute) —— 有效，窗口有毛玻璃底
#   · Mica (DWMWA_SYSTEMBACKDROP_TYPE=38) —— 无效：overrideredirect 是 WS_POPUP，
#     系统不给 Mica 背景（API 返回成功但视觉无变化）
#   · 深色标题栏 —— 无意义（无边框窗口没有标题栏）
# 重要：Tk 的 winfo_id() 是**子窗口**，DWM 属性必须设在**顶层窗口**上，
#       对子窗口调用会返回 0x80070006（句柄无效）。
_dwm = ctypes.windll.dwmapi

DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_DEFAULT = 0
DWMWCP_DONOTROUND = 1
DWMWCP_ROUND = 2

u32.SetWindowCompositionAttribute.argtypes = [wintypes.HWND, ctypes.c_void_p]
u32.SetWindowCompositionAttribute.restype = wintypes.BOOL
WCA_ACCENT_POLICY = 19
ACCENT_DISABLED = 0
ACCENT_ENABLE_BLURBEHIND = 3
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4


class ACCENTPOLICY(ctypes.Structure):
    _fields_ = [('AccentState', ctypes.c_int),
                ('AccentFlags', ctypes.c_int),
                ('GradientColor', ctypes.c_uint),   # 0xAABBGGRR（注意是 BGR）
                ('AnimationId', ctypes.c_int)]


class WINCOMPATTRDATA(ctypes.Structure):
    _fields_ = [('Attribute', ctypes.c_int),
                ('Data', ctypes.POINTER(ACCENTPOLICY)),
                ('SizeOfData', ctypes.c_size_t)]


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

