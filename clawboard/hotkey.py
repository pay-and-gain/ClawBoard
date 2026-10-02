# -*- coding: utf-8 -*-
"""隐藏消息窗口（热键 + 托盘，独立线程）+ 图标生成。

HiddenWindow 在独立线程创建 message-only 窗口承载 RegisterHotKey 与托盘回调；
make_ico 纯 stdlib 生成 32x32 32bpp ICO，不依赖外部资源。
"""
import ctypes
import os
import threading
import traceback
from ctypes import wintypes

from clawboard.config import APP_NAME, ICON_FILE
from clawboard.win32 import (
    u32, k32, sh32, WNDPROC, WNDCLASS, NOTIFYICONDATA,
    HWND_MESSAGE, WM_HOTKEY, WM_APP_REG, WM_APP_UNREG, WM_TRAY,
    WM_LBUTTONUP, WM_RBUTTONUP, WM_DESTROY,
    NIF_INFO, NIIF_INFO, NIM_ADD, NIM_MODIFY, NIM_DELETE,
    NIF_MESSAGE, NIF_ICON, NIF_TIP, IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE,
)


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
