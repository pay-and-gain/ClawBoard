# -*- coding: utf-8 -*-
"""Win32 DLL、常量、句柄结构与 ctypes 声明的唯一来源。"""
import ctypes
from ctypes import wintypes


u32 = ctypes.WinDLL('user32', use_last_error=True)

k32 = ctypes.WinDLL('kernel32', use_last_error=True)

psapi = ctypes.WinDLL('psapi')

advapi = ctypes.WinDLL('advapi32', use_last_error=True)

CF_UNICODETEXT = 13

CF_HDROP = 15                 # 资源管理器按 Ctrl+C 复制文件时的格式（HDROP 句柄列表）

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

u32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
u32.RegisterWindowMessageW.restype = wintypes.UINT

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

u32.DestroyWindow.argtypes = [wintypes.HWND]
u32.DestroyWindow.restype = wintypes.BOOL

u32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
u32.UnregisterClassW.restype = wintypes.BOOL

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

# shell32 的别名，供「读取 CF_HDROP 文件路径」使用。
# 坑③同类：DragQueryFileW 的第一个参数 HDROP 是 64 位句柄，且返回 c_uint（文件数/字符数），
# 不声明 argtypes/restype 会被 ctypes 按 c_int 截断 64 位句柄（本项目此前 GetClipboardData /
# GlobalSize 就栽在这里），所以这里必须显式声明。
shell32 = sh32

shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT,
                                   wintypes.LPWSTR, wintypes.UINT]

shell32.DragQueryFileW.restype = wintypes.UINT

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

# HKL 是句柄，不能沿用 ctypes 默认的 c_int；调用者需要的是目标焦点线程，
# 传 0 会误读当前 hook/worker 自己的布局。
u32.GetKeyboardLayout.argtypes = [wintypes.DWORD]
u32.GetKeyboardLayout.restype = ctypes.c_void_p

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

class WNDCLASS(ctypes.Structure):
    _fields_ = [('style', wintypes.UINT), ('lpfnWndProc', WNDPROC),
                ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int),
                ('hInstance', wintypes.HINSTANCE), ('hIcon', wintypes.HICON),
                ('hCursor', wintypes.HANDLE), ('hbrBackground', wintypes.HANDLE),
                ('lpszMenuName', wintypes.LPCWSTR), ('lpszClassName', wintypes.LPCWSTR)]

u32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]

u32.RegisterClassW.restype = wintypes.ATOM

class _NOTIFYICONTIMEOUT(ctypes.Union):
    # 两个名字共用同一 DWORD；分开声明会错移气泡标题、图标标志和后续字段。
    _fields_ = [('uTimeout', wintypes.UINT), ('uVersion', wintypes.UINT)]


class NOTIFYICONDATA(ctypes.Structure):
    _anonymous_ = ('timeout_version',)
    _fields_ = [('cbSize', wintypes.DWORD), ('hWnd', wintypes.HWND), ('uID', wintypes.UINT),
                ('uFlags', wintypes.UINT), ('uCallbackMessage', wintypes.UINT),
                ('hIcon', wintypes.HICON), ('szTip', wintypes.WCHAR * 128),
                ('dwState', wintypes.DWORD), ('dwStateMask', wintypes.DWORD),
                ('szInfo', wintypes.WCHAR * 256), ('timeout_version', _NOTIFYICONTIMEOUT),
                ('szInfoTitle', wintypes.WCHAR * 64),
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

MODIFIER_VKS = (VK_CONTROL, VK_SHIFT, VK_MENU, 0x5B, 0x5C)   # Ctrl/Shift/Alt/LWin/RWin

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

u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]

u32.GetWindowRect.restype = wintypes.BOOL

# ---------------- 全屏检测（全屏程序前台时面板不再置顶） ----------------
MONITOR_DEFAULTTONEAREST = 2

class MONITORINFO(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD),
                ('rcMonitor', wintypes.RECT),
                ('rcWork', wintypes.RECT),
                ('dwFlags', wintypes.DWORD)]

u32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]

u32.MonitorFromWindow.restype = wintypes.HMONITOR

u32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]

u32.GetMonitorInfoW.restype = wintypes.BOOL

# 坑③同类：HWND 在 64 位是 64 位句柄，不声明 argtypes 会被 ctypes 按 c_int 截断。
u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

u32.GetClassNameW.restype = ctypes.c_int

# 窗口状态 / 样式：用于「有标题栏的最大化窗口不算全屏」这条排除。
# GetWindowLongW 的 HWND 同样必须声明 argtypes（64 位句柄截断坑），返回值用 LONG。
u32.IsZoomed.argtypes = [wintypes.HWND]

u32.IsZoomed.restype = wintypes.BOOL

u32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]

u32.GetWindowLongW.restype = wintypes.LONG

GWL_STYLE = -16

WS_CAPTION = 0x00C00000          # WS_BORDER | WS_DLGFRAME

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

WH_KEYBOARD_LL = 13

WM_KEYDOWN = 0x0100

WM_KEYUP = 0x0101

WM_SYSKEYDOWN = 0x0104

WM_SYSKEYUP = 0x0105

VK_BACK = 0x08

VK_TAB = 0x09

VK_RETURN = 0x0D

VK_SPACE = 0x20

VK_CAPITAL = 0x14

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [('vkCode', wintypes.DWORD), ('scanCode', wintypes.DWORD),
                ('flags', wintypes.DWORD), ('time', wintypes.DWORD),
                ('dwExtraInfo', ctypes.c_void_p)]

HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM,
                              wintypes.LPARAM)

u32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE,
                                  wintypes.DWORD]

u32.SetWindowsHookExW.restype = ctypes.c_void_p

u32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM,
                               wintypes.LPARAM]

u32.CallNextHookEx.restype = ctypes.c_ssize_t

u32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]

u32.UnhookWindowsHookEx.restype = wintypes.BOOL

u32.GetKeyState.argtypes = [ctypes.c_int]

u32.GetKeyState.restype = ctypes.c_short

# 所有跨进程消息都有有界等待；结果指针是 DWORD_PTR，64 位不能用 DWORD。
SMTO_ABORTIFHUNG = 0x0002
WM_QUIT = 0x0012
PM_NOREMOVE = 0x0000
u32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t),
]
u32.SendMessageTimeoutW.restype = LRESULT
u32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT,
                                  wintypes.WPARAM, wintypes.LPARAM]
u32.PostThreadMessageW.restype = wintypes.BOOL
u32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                            wintypes.UINT, wintypes.UINT, wintypes.UINT]
u32.PeekMessageW.restype = wintypes.BOOL
# Tk 给的是内部子窗口；取父 HWND 时同样必须保留全部句柄位。
u32.GetParent.argtypes = [wintypes.HWND]
u32.GetParent.restype = wintypes.HWND

# DPI/GDI/DWM 也通过同一组 DLL 对象，避免功能模块另开未声明的句柄接口。
gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
_dwm = ctypes.WinDLL('dwmapi', use_last_error=True)
try:
    shcore = ctypes.WinDLL('shcore', use_last_error=True)
except OSError:
    shcore = None
u32.GetDC.argtypes = [wintypes.HWND]
u32.GetDC.restype = wintypes.HDC
u32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
u32.ReleaseDC.restype = ctypes.c_int
gdi32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
gdi32.GetDeviceCaps.restype = ctypes.c_int
try:
    u32.GetDpiForSystem.argtypes = []
    u32.GetDpiForSystem.restype = wintypes.UINT
    u32.GetDpiForWindow.argtypes = [wintypes.HWND]
    u32.GetDpiForWindow.restype = wintypes.UINT
except AttributeError:
    pass
if shcore is not None:
    shcore.SetProcessDpiAwareness.argtypes = [ctypes.c_int]
    shcore.SetProcessDpiAwareness.restype = ctypes.c_long
_dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD,
                                     ctypes.c_void_p, wintypes.DWORD]
_dwm.DwmSetWindowAttribute.restype = ctypes.c_long
