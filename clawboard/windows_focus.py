# -*- coding: utf-8 -*-
"""窗口焦点与粘贴投递：完整性检查、焦点切换和有界 WM_PASTE。"""
import ctypes
import time
from ctypes import wintypes

from clawboard.windows_api import (
    GUITHREADINFO, PROCESS_QUERY_LIMITED_INFORMATION, SECURITY_MANDATORY_HIGH_RID,
    TOKEN_INTEGRITY_LEVEL, TOKEN_QUERY, WM_PASTE, SMTO_ABORTIFHUNG, advapi, k32, u32,
)


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

PASTE_MESSAGE_TIMEOUT_MS = 500


def paste_message(hwnd_top):
    """有界发送 WM_PASTE；返回是否送达，不把控件自己的零返回值当作失败。

    目标窗口卡住时最多等待 500ms，避免后台粘贴任务永远占住工作线程。
    返回 False 后调用方可提示用户手动粘贴或使用焦点切换路径。
    """
    focus = target_focus_hwnd(hwnd_top)
    if not focus:
        return False
    try:
        result = ctypes.c_size_t()
        return bool(u32.SendMessageTimeoutW(
            focus, WM_PASTE, 0, 0, SMTO_ABORTIFHUNG,
            PASTE_MESSAGE_TIMEOUT_MS, ctypes.byref(result)))
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
