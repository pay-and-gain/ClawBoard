# -*- coding: utf-8 -*-
"""图片剪贴板处理：DIB ↔ PNG（零依赖，无 PIL）。

剪贴板里的图片是 CF_DIB 格式（BITMAPINFOHEADER + 像素数据，自底向上）。
Tk 的 PhotoImage 只认 PNG/GIF/PGM，不认 DIB，所以这里用标准库 zlib 手动做
DIB → PNG 转换（已验证全链路：构造 DIB → 写剪贴板 → 读回 → PNG → PhotoImage 加载）。

PNG 编码支持两种位深：32 位 BGRA（biBitCount=32）与 24 位 BGR（biBitCount=24），
这也是截图工具（微信/QQ/系统截图）最常见的格式。24 位转 PNG 时 alpha 补 255；
biHeight 为负表示自顶向下存储，不再要求一定是自底向上。
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
    """DIB 字节 → (png 字节, 宽, 高)。支持 32 位 BGRA 与 24 位 BGR。

    biHeight 为负表示自顶向下存储（top-down），为正表示自底向上（bottom-up，
    DIB 最常见）。PNG 一律自顶向下，因此 bottom-up 需要把行序翻转。
    """
    biSize = struct.unpack_from('<I', dib, 0)[0]
    wpx = struct.unpack_from('<i', dib, 4)[0]
    biHeight = struct.unpack_from('<i', dib, 8)[0]
    bitcount = struct.unpack_from('<H', dib, 14)[0]
    if bitcount == 32:
        bpp = 4
    elif bitcount == 24:
        bpp = 3
    else:
        raise ValueError('不支持的位深：%d（当前支持 24/32 位）' % bitcount)

    topdown = biHeight < 0
    hpx = abs(biHeight)
    px = dib[biSize:]
    stride = ((wpx * bpp) + 3) & ~3           # 每行 4 字节对齐

    rows = range(hpx) if topdown else range(hpx - 1, -1, -1)
    raw = bytearray()
    for y in rows:
        row = px[y * stride:y * stride + wpx * bpp]
        raw.append(0)                        # filter byte: None
        for i in range(0, len(row), bpp):    # BGRA / BGR → RGBA
            b, g, r = row[i], row[i + 1], row[i + 2]
            a = row[i + 3] if bpp == 4 else 255
            raw += bytes((r, g, b, a))

    def chunk(typ, data):
        c = struct.pack('>I', len(data)) + typ + data
        return c + struct.pack('>I', zlib.crc32(typ + data) & 0xFFFFFFFF)

    ihdr = struct.pack('>IIBBBBB', wpx, hpx, 8, 6, 0, 0, 0)   # 8bit RGBA
    png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) +
           chunk(b'IDAT', zlib.compress(bytes(raw), 6)) + chunk(b'IEND', b''))
    return png, wpx, hpx


def png_to_dib(png):
    """PNG 字节 → (dib 字节, 宽, 高)。支持 8 位 RGBA/RGB（含全部 5 种 filter）。"""
    if png[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('不是合法 PNG')
    pos = 8
    w = h = bitdepth = colortype = 0
    idat = b''
    while pos < len(png):
        length = struct.unpack_from('>I', png, pos)[0]
        typ = png[pos + 4:pos + 8]
        data = png[pos + 8:pos + 8 + length]
        if typ == b'IHDR':
            w = struct.unpack_from('>I', data, 0)[0]
            h = struct.unpack_from('>I', data, 4)[0]
            bitdepth = data[8]
            colortype = data[9]
        elif typ == b'IDAT':
            idat += data
        elif typ == b'IEND':
            break
        pos += 12 + length
    if bitdepth != 8 or colortype not in (2, 6):   # RGB / RGBA
        raise ValueError('不支持的 PNG 格式（只支持 8 位 RGB/RGBA）')
    bpp = 3 if colortype == 2 else 4
    stride = w * bpp
    raw = zlib.decompress(idat)

    # 还原 filter
    rows = []
    i = 0
    prev = bytearray(stride)
    for _y in range(h):
        ft = raw[i]
        i += 1
        row = bytearray(raw[i:i + stride])
        i += stride
        if ft == 1:                       # Sub
            for x in range(bpp, stride):
                row[x] = (row[x] + row[x - bpp]) & 0xFF
        elif ft == 2:                     # Up
            for x in range(stride):
                row[x] = (row[x] + prev[x]) & 0xFF
        elif ft == 3:                     # Average
            for x in range(stride):
                a = row[x - bpp] if x >= bpp else 0
                row[x] = (row[x] + ((a + prev[x]) >> 1)) & 0xFF
        elif ft == 4:                     # Paeth
            for x in range(stride):
                a = row[x - bpp] if x >= bpp else 0
                b = prev[x]
                c = prev[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                row[x] = (row[x] + pr) & 0xFF
        rows.append(row)
        prev = row

    # RGB(A) → 32 位 BGRA，自底向上
    header = struct.pack('<IiiHHIIiiII', 40, w, h, 1, 32, 0, w * h * 4,
                         0, 0, 0, 0)
    px = bytearray()
    for y in range(h - 1, -1, -1):
        row = rows[y]
        for x in range(0, stride, bpp):
            r, g, b = row[x], row[x + 1], row[x + 2]
            a = row[x + 3] if bpp == 4 else 255
            px += bytes((b, g, r, a))
    return bytes(header) + bytes(px), w, h


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
