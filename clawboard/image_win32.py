# -*- coding: utf-8 -*-
"""Windows clipboard adapter for image bytes, separate from codecs and UI."""
import ctypes
from ctypes import wintypes

from clawboard.clipboard import _write_own_marker, _ack_own_write, clip_seq
from clawboard.image import CF_DIB, GMEM_MOVEABLE, MAX_DIB_BYTES

u32 = ctypes.WinDLL('user32', use_last_error=True)
k32 = ctypes.WinDLL('kernel32', use_last_error=True)

u32.GetClipboardData.argtypes = [wintypes.UINT]
u32.GetClipboardData.restype = wintypes.HANDLE
u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
u32.SetClipboardData.restype = wintypes.HANDLE
u32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
u32.IsClipboardFormatAvailable.restype = wintypes.BOOL
u32.OpenClipboard.argtypes = [wintypes.HWND]
u32.OpenClipboard.restype = wintypes.BOOL
u32.CloseClipboard.restype = wintypes.BOOL
u32.EmptyClipboard.restype = wintypes.BOOL
u32.GetClipboardSequenceNumber.restype = wintypes.DWORD
k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
k32.GlobalAlloc.restype = wintypes.HANDLE
k32.GlobalLock.argtypes = [wintypes.HANDLE]
k32.GlobalLock.restype = ctypes.c_void_p
k32.GlobalUnlock.argtypes = [wintypes.HANDLE]
k32.GlobalUnlock.restype = wintypes.BOOL
k32.GlobalSize.argtypes = [wintypes.HANDLE]
k32.GlobalSize.restype = ctypes.c_size_t
k32.GlobalFree.argtypes = [wintypes.HANDLE]
k32.GlobalFree.restype = wintypes.HANDLE


def clipboard_has_image():
    try:
        return bool(u32.IsClipboardFormatAvailable(CF_DIB))
    except Exception:
        return False


def read_clipboard_dib():
    if not u32.OpenClipboard(None):
        return None
    try:
        handle = u32.GetClipboardData(CF_DIB)
        if not handle:
            return None
        size = k32.GlobalSize(handle)
        if size < 40 or size > MAX_DIB_BYTES:
            return None
        pointer = k32.GlobalLock(handle)
        if not pointer:
            return None
        try:
            return ctypes.string_at(pointer, size)
        finally:
            k32.GlobalUnlock(handle)
    except Exception:
        return None
    finally:
        u32.CloseClipboard()


def write_clipboard_dib(dib):
    if not (40 <= len(dib) <= MAX_DIB_BYTES) or not u32.OpenClipboard(None):
        return False
    handle = None
    transferred = False
    try:
        if not u32.EmptyClipboard():
            return False
        handle = k32.GlobalAlloc(GMEM_MOVEABLE, len(dib))
        if not handle:
            return False
        pointer = k32.GlobalLock(handle)
        if not pointer:
            return False
        try:
            ctypes.memmove(pointer, dib, len(dib))
        finally:
            k32.GlobalUnlock(handle)
        transferred = bool(u32.SetClipboardData(CF_DIB, handle))
        if not transferred:
            return False
        marker = _write_own_marker()
        sequence = clip_seq()
    except Exception:
        return False
    finally:
        if handle and not transferred:
            k32.GlobalFree(handle)
        u32.CloseClipboard()
    _ack_own_write(sequence, marker)
    return True
