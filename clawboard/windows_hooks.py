# -*- coding: utf-8 -*-
"""全局键盘钩子；安装、消息泵与卸载归同一工作线程，停止后取消旧回调。"""
import ctypes
import threading
from ctypes import wintypes

from clawboard.windows_api import (
    HOOKPROC, KBDLLHOOKSTRUCT, PM_NOREMOVE, VK_BACK, VK_CAPITAL, VK_RETURN, VK_SHIFT,
    VK_SPACE, VK_TAB, WH_KEYBOARD_LL, WM_KEYDOWN, WM_SYSKEYDOWN, WM_QUIT, k32, u32,
)

# 美式键盘 OEM 键到字符（无 Shift 时）
_OEM_BASE = {0xBC: ',', 0xBE: '.', 0xBD: '-', 0xBA: ';', 0xBF: '/',
             0xDE: "'", 0xDC: '\\', 0xC0: '`', 0xDB: '[', 0xDD: ']', 0xBB: '='}

# 有 Shift 时（数字键的符号 + OEM 键上档）
_OEM_SHIFT = {0xBC: '<', 0x30: ')', 0x31: '!', 0x32: '@', 0x33: '#', 0x34: '$',
              0x35: '%', 0x36: '^', 0x37: '&', 0x38: '*', 0x39: '(', 0xBE: '>',
              0xBD: '_', 0xBA: ':', 0xBF: '?', 0xDE: '"', 0xDC: '|',
              0xC0: '~', 0xDB: '{', 0xDD: '}', 0xBB: '+'}

def vk_to_char(vk, shift, caps):
    """vkCode → 字符（美式键盘简化映射）。返回 '' 表示无法识别。"""
    if 0x30 <= vk <= 0x39:                  # 数字 0-9
        return _OEM_SHIFT.get(vk) if shift else chr(vk)
    if 0x41 <= vk <= 0x5A:                  # 字母 A-Z
        upper = bool(shift) != bool(caps)   # Shift 与 CapsLock 异或决定大小写
        c = chr(vk)
        return c if upper else c.lower()
    if vk == VK_SPACE:
        return ' '
    if vk == VK_TAB:
        return '\t'
    if vk == VK_RETURN:
        return '\n'
    if vk in _OEM_BASE:
        return _OEM_SHIFT.get(vk) if shift else _OEM_BASE[vk]
    return ''


_hook = None
_hook_cb = None
_hook_stop = None
_hook_thread = None
_hook_tid = 0
_hook_lock = threading.RLock()
HOOK_START_TIMEOUT = 1.0
HOOK_STOP_TIMEOUT = 1.0


def start_keyboard_hook(on_char, on_backspace):
    """启动有消息队列的独立 hook 线程；调用方只限时等待初始化结果。"""
    global _hook, _hook_cb, _hook_stop, _hook_thread, _hook_tid
    with _hook_lock:
        if _hook_thread is not None and _hook_thread.is_alive():
            return bool(_hook) and not _hook_stop.is_set()
        ready = threading.Event()
        stop = threading.Event()
        _hook_stop = stop

        def run():
            global _hook, _hook_cb, _hook_stop, _hook_thread, _hook_tid
            handle = None
            callback = None
            try:
                msg = wintypes.MSG()
                _hook_tid = k32.GetCurrentThreadId()
                # PostThreadMessage 只接受已有消息队列的线程。PeekMessage 先建队列，
                # ready 才能同时意味着「可接收退出消息」，而不只是「有 thread id」。
                u32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)
                if stop.is_set():
                    return

                @HOOKPROC
                def callback(nCode, wParam, lParam):
                    if not stop.is_set() and nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                        try:
                            kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                            vk = kb.vkCode
                            if vk == VK_BACK:
                                on_backspace()
                            else:
                                shift = bool(u32.GetKeyState(VK_SHIFT) & 0x8000)
                                caps = bool(u32.GetKeyState(VK_CAPITAL) & 0x0001)
                                char = vk_to_char(vk, shift, caps)
                                if char:
                                    on_char(char)
                        except Exception:
                            # 用户回调失败也必须继续传递按键，不能把系统输入链截断。
                            pass
                    return u32.CallNextHookEx(None, nCode, wParam, lParam)

                _hook_cb = callback
                handle = u32.SetWindowsHookExW(
                    WH_KEYBOARD_LL, callback, k32.GetModuleHandleW(None), 0)
                _hook = handle
                ready.set()
                if not handle:
                    return
                while not stop.is_set():
                    status = u32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                    if status <= 0 or stop.is_set():
                        break
                    u32.TranslateMessage(ctypes.byref(msg))
                    u32.DispatchMessageW(ctypes.byref(msg))
            except Exception:
                pass
            finally:
                stop.set()
                if handle:
                    try:
                        u32.UnhookWindowsHookEx(handle)
                    except Exception:
                        pass
                ready.set()
                with _hook_lock:
                    if _hook_thread is threading.current_thread():
                        _hook = _hook_cb = _hook_stop = _hook_thread = None
                        _hook_tid = 0

        _hook_thread = threading.Thread(target=run, name='ClawBoardKeyboardHook', daemon=True)
        _hook_thread.start()
        if not ready.wait(HOOK_START_TIMEOUT):
            stop.set()
            if _hook_tid:
                u32.PostThreadMessageW(_hook_tid, WM_QUIT, 0, 0)
            return False
        return bool(_hook) and not stop.is_set()


def stop_keyboard_hook():
    """向拥有 hook 的线程发 WM_QUIT；finally 在同一线程卸载并释放回调。"""
    with _hook_lock:
        thread = _hook_thread
        stop = _hook_stop
        tid = _hook_tid
        if stop is not None:
            stop.set()
        if tid:
            try:
                u32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
            except Exception:
                pass
    # 不持锁 join：工作线程的 finally 需要同一把锁清理权威状态。
    if thread is not None and thread is not threading.current_thread():
        thread.join(HOOK_STOP_TIMEOUT)
