# -*- coding: utf-8 -*-
"""图片剪贴板处理：DIB ↔ PNG（零依赖，无 PIL）。

剪贴板里的图片是 CF_DIB 格式（BITMAPINFOHEADER + 像素数据，自底向上）。
Tk 的 PhotoImage 只认 PNG/GIF/PGM，不认 DIB，所以这里用标准库 zlib 手动做
DIB → PNG 转换（已验证全链路：构造 DIB → 写剪贴板 → 读回 → PNG → PhotoImage 加载）。

PNG 编码只处理一种情况：32 位 BGRA（biBitCount=32），这是截图工具（微信/QQ/系统
截图）最常见的格式。其它位深（24/16/8）后续按需扩展。
"""
import ctypes
import os
import struct
import zlib
from ctypes import wintypes

u32 = ctypes.WinDLL('user32', use_last_error=True)
k32 = ctypes.WinDLL('kernel32', use_last_error=True)

CF_DIB = 8
GMEM_MOVEABLE = 0x0002

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
k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
k32.GlobalAlloc.restype = wintypes.HANDLE
k32.GlobalLock.argtypes = [wintypes.HANDLE]
k32.GlobalLock.restype = ctypes.c_void_p
k32.GlobalUnlock.argtypes = [wintypes.HANDLE]
k32.GlobalUnlock.restype = wintypes.BOOL
k32.GlobalSize.argtypes = [wintypes.HANDLE]
k32.GlobalSize.restype = ctypes.c_size_t


def dib_to_png(dib):
    """DIB 字节 → (png 字节, 宽, 高)。只支持 32 位 BGRA。"""
    biSize = struct.unpack_from('<I', dib, 0)[0]
    wpx = struct.unpack_from('<i', dib, 4)[0]
    hpx = struct.unpack_from('<i', dib, 8)[0]
    bitcount = struct.unpack_from('<H', dib, 14)[0]
    if bitcount != 32:
        raise ValueError('不支持的位深：%d（当前只支持 32 位）' % bitcount)
    px = dib[biSize:]
    stride = ((wpx * 4) + 3) & ~3           # 每行 4 字节对齐

    raw = bytearray()
    for y in range(hpx - 1, -1, -1):        # DIB 自底向上，PNG 自顶向下
        row = px[y * stride:y * stride + wpx * 4]
        raw.append(0)                        # filter byte: None
        for i in range(0, len(row), 4):      # BGRA → RGBA
            b, g, r, a = row[i], row[i + 1], row[i + 2], row[i + 3]
            raw += bytes((r, g, b, a))

    def chunk(typ, data):
        c = struct.pack('>I', len(data)) + typ + data
        return c + struct.pack('>I', zlib.crc32(typ + data) & 0xFFFFFFFF)

    ihdr = struct.pack('>IIBBBBB', wpx, hpx, 8, 6, 0, 0, 0)   # 8bit RGBA
    png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) +
           chunk(b'IDAT', zlib.compress(bytes(raw), 6)) + chunk(b'IEND', b''))
    return png, wpx, hpx


def clipboard_has_image():
    """剪贴板当前是否有图片（CF_DIB）。"""
    try:
        return bool(u32.IsClipboardFormatAvailable(CF_DIB))
    except Exception:
        return False


def read_clipboard_dib():
    """读剪贴板里的 DIB 字节，无图片或失败返回 None。"""
    if not u32.OpenClipboard(None):
        return None
    try:
        h = u32.GetClipboardData(CF_DIB)
        if not h:
            return None
        size = k32.GlobalSize(h)
        p = k32.GlobalLock(h)
        if not p:
            return None
        try:
            return ctypes.string_at(p, size)
        finally:
            k32.GlobalUnlock(h)
    except Exception:
        return None
    finally:
        u32.CloseClipboard()


def write_clipboard_dib(dib):
    """把 DIB 字节写入剪贴板（阶段 2 粘贴图片用）。"""
    if not u32.OpenClipboard(None):
        return False
    try:
        u32.EmptyClipboard()
        h = k32.GlobalAlloc(GMEM_MOVEABLE, len(dib))
        if not h:
            return False
        p = k32.GlobalLock(h)
        if not p:
            return False
        ctypes.memmove(p, dib, len(dib))
        k32.GlobalUnlock(h)
        return bool(u32.SetClipboardData(CF_DIB, h))
    except Exception:
        return False
    finally:
        u32.CloseClipboard()
