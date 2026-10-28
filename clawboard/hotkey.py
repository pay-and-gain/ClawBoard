# -*- coding: utf-8 -*-
"""隐藏消息窗口（热键 + 托盘，独立线程）+ 图标生成。

HiddenWindow 在独立线程创建不显示的顶层窗口承载热键、托盘与 Shell 重建广播；
make_ico 纯 stdlib 生成 32x32 32bpp ICO，不依赖外部资源。
"""
import ctypes
import os
import threading
import traceback
from ctypes import wintypes

from clawboard.config import APP_NAME, ICON_FILE, UI_ASSET_DIR
from clawboard.win32 import (
    u32, k32, sh32, WNDPROC, WNDCLASS, NOTIFYICONDATA,
    WM_HOTKEY, WM_APP_REG, WM_APP_UNREG, WM_TRAY,
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
    """独立线程创建隐藏顶层窗口；message-only 窗口收不到 TaskbarCreated 广播。"""

    def __init__(self, on_hotkey, on_tray, on_clipboard=None):
        threading.Thread.__init__(self, daemon=True)
        self.on_hotkey = on_hotkey
        self.on_tray = on_tray
        self.on_clipboard = on_clipboard
        self.clipboard_listener = False
        self.hwnd = None
        self.ready = threading.Event()
        self.hotkey_id = 1
        self.hotkey_ok = False
        self._proc = None
        self._icon = None
        self._hk_evt = threading.Event()
        self._stopping = threading.Event()
        self._taskbar_created = 0
        self._tray_enabled = False
        self._tray_lock = threading.RLock()
        # 类名不能复用：同进程中的第二个实例否则仍会调用第一个实例的 WNDPROC。
        self._class_name = 'ClawBoardMsgWindow_%x' % id(self)

    def wndproc(self, hwnd, msg, wp, lp):
        try:
            if self._taskbar_created and msg == self._taskbar_created:
                with self._tray_lock:
                    if self._tray_enabled:
                        self._add_tray()
                return 0
            elif msg == 0x031D and self.on_clipboard:  # WM_CLIPBOARDUPDATE
                self.on_clipboard()
            elif msg == 0x0010:  # WM_CLOSE must be handled by this window's owner.
                self._close_window()
                return 0
            elif msg == WM_APP_REG:
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
        instance = None
        registered = False
        try:
            if self._stopping.is_set():
                return
            self._taskbar_created = u32.RegisterWindowMessageW('TaskbarCreated')
            self._proc = WNDPROC(self.wndproc)
            wc = WNDCLASS()
            wc.lpfnWndProc = self._proc
            wc.lpszClassName = self._class_name
            instance = wc.hInstance = k32.GetModuleHandleW(None)
            registered = bool(u32.RegisterClassW(ctypes.byref(wc)))
            if not registered:
                return
            self.hwnd = u32.CreateWindowExW(0, self._class_name, 'ClawBoardMsg',
                                            0, 0, 0, 0, 0, None,
                                            None, wc.hInstance, None)
            if self.hwnd and self.on_clipboard:
                u32.AddClipboardFormatListener.argtypes = [wintypes.HWND]
                u32.AddClipboardFormatListener.restype = wintypes.BOOL
                u32.RemoveClipboardFormatListener.argtypes = [wintypes.HWND]
                u32.RemoveClipboardFormatListener.restype = wintypes.BOOL
                self.clipboard_listener = bool(u32.AddClipboardFormatListener(self.hwnd))
            self.ready.set()
            if not self.hwnd or self._stopping.is_set():
                return
            msg = wintypes.MSG()
            while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                # 用 NULL 句柄注册的热键没有目标窗口，必须在循环里直接截获
                if msg.message == WM_HOTKEY:
                    self.on_hotkey()
                    continue
                u32.TranslateMessage(ctypes.byref(msg))
                u32.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            traceback.print_exc()
        finally:
            # GetMessage 出错、初始化失败、stop 早于 ready 都走同一条 owner-thread 清理路径。
            try:
                self._close_window()
            finally:
                try:
                    if registered:
                        u32.UnregisterClassW(self._class_name, instance)
                finally:
                    self.ready.set()

    def _close_window(self):
        self._stopping.set()
        if not self.hwnd:
            return
        hwnd = self.hwnd
        self._do_unreg()
        self._hk_evt.set()
        self.tray_del()
        if self.clipboard_listener:
            u32.RemoveClipboardFormatListener(hwnd)
            self.clipboard_listener = False
        u32.DestroyWindow(hwnd)
        self.hwnd = None

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
        with self._tray_lock:
            if self._stopping.is_set():
                return False
            # 记录调用者的启用意图：首次添加也可能恰遇 Explorer 重建而暂时失败。
            self._tray_enabled = True
            return self._add_tray()

    def _add_tray(self):
        if not self.hwnd or self._stopping.is_set():
            return False
        try:
            icon_path = ICON_FILE
            dark_taskbar = None
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                    r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
                    dark_taskbar = not bool(winreg.QueryValueEx(key, 'SystemUsesLightTheme')[0])
            except (ImportError, OSError, AttributeError, TypeError, ValueError):
                pass
            tray_path = os.path.join(UI_ASSET_DIR, 'tray-dark.ico' if dark_taskbar else 'tray-light.ico')
            if dark_taskbar is not None and os.path.isfile(tray_path):
                icon_path = tray_path
            if not os.path.exists(icon_path):
                make_ico(icon_path)
            # Explorer 重建会丢掉通知区图标，不会使本进程持有的 HICON 失效。
            if not self._icon:
                self._icon = u32.LoadImageW(None, icon_path, IMAGE_ICON, 0, 0,
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
        with self._tray_lock:
            self._tray_enabled = False
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
        self._stopping.set()
        try:
            if self.hwnd:
                u32.PostMessageW(self.hwnd, 0x0010, 0, 0)
        except Exception:
            pass
