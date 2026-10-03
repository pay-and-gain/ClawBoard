# -*- coding: utf-8 -*-
"""QA-2 边界与错误路径。

Part 1（纯单元，直接调用 dib_to_png）：
  - 极端尺寸 1x1 / 1xN / Nx1 / 宽度非 4 倍数（24 位与 32 位）
  - 16 位 / 8 位 / 4 位 / 1 位 → 必须 ValueError，且不崩溃
  - 负高度 1xN 等
  - 尺寸自洽：用 QA-2 独立解码器回读
Part 2（活体应用，错误路径不误记/不崩溃）：
  - 剪贴板写纯文本 → 应用应记为 text（非 image），且进程存活
  - 剪贴板写 16 位 DIB → 应用不得崩溃、不得新增 image
"""
import ctypes
import ctypes.wintypes as w
import json
import os
import struct
import subprocess
import sys
import time
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clawboard.image import dib_to_png   # noqa

DESKTOP = r'C:\Users\pay and gain\Desktop'
EXE222 = os.path.join(DESKTOP, 'ClawBoard-2.2.2.exe')
DATA = os.path.join(DESKTOP, 'ClawBoard数据.json')

FAIL = []


def log(*a):
    print(*a, flush=True)


def check(name, cond, extra=''):
    if not cond:
        FAIL.append(name)
    log('%s %s%s' % ('OK  ' if cond else 'FAIL', name, ('  ' + extra) if extra else ''))


# ---------- 独立解码器（复用于尺寸自洽，与本仓库无关） ----------
def parse_png_size(png):
    assert png[:8] == b'\x89PNG\r\n\x1a\n'
    pos = 8
    while pos < len(png):
        ln = struct.unpack_from('>I', png, pos)[0]
        typ = png[pos + 4:pos + 8]
        if typ == b'IHDR':
            wpx, hpx = struct.unpack_from('>II', png, pos + 8)
            return wpx, hpx
        pos += 12 + ln
    raise AssertionError('no IHDR')


def parse_png_rows(png):
    pos = 8
    width = height = bd = ct = 0
    idat = b''
    while pos < len(png):
        ln = struct.unpack_from('>I', png, pos)[0]
        typ = png[pos + 4:pos + 8]
        data = png[pos + 8:pos + 8 + ln]
        if typ == b'IHDR':
            width, height, bd, ct = struct.unpack_from('>IIBB', data, 0)
        elif typ == b'IDAT':
            idat += data
        elif typ == b'IEND':
            break
        pos += 12 + ln
    ch = 3 if ct == 2 else 4
    stride = width * ch
    raw = zlib.decompress(idat)
    rows = []
    prev = bytearray(stride)
    i = 0
    for _ in range(height):
        ft = raw[i]; i += 1
        cur = bytearray(raw[i:i + stride]); i += stride
        for x in range(stride):
            a = cur[x - ch] if x >= ch else 0
            b = prev[x]
            c = prev[x - ch] if x >= ch else 0
            if ft == 1:
                cur[x] = (cur[x] + a) & 0xFF
            elif ft == 2:
                cur[x] = (cur[x] + b) & 0xFF
            elif ft == 3:
                cur[x] = (cur[x] + ((a + b) >> 1)) & 0xFF
            elif ft == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                cur[x] = (cur[x] + pr) & 0xFF
        rows.append([tuple(cur[x:x + ch]) for x in range(0, stride, ch)])
        prev = cur
    return width, height, rows


def make_dib(w, h, bitcount=24, topdown=False):
    bpp = bitcount // 8
    stride = ((w * bpp) + 3) & ~3
    biHeight = -h if topdown else h
    header = struct.pack('<IiiHHIIiiII', 40, w, biHeight, 1, bitcount, 0, stride * h, 0, 0, 0, 0)
    rows = []
    for y in range(h):
        row = bytearray()
        for x in range(w):
            r, g, b = (x * 5 % 256), (y * 7 % 256), 128
            row += bytes((b, g, r)) if bpp == 3 else bytes((b, g, r, 255))
        row += b'\x00' * (stride - len(row))
        rows.append(bytes(row))
    return header + b''.join(rows if topdown else rows[::-1])


# ============ Part 1：极端尺寸 ============
log('=== Part1 极端尺寸 ===')
size_cases = [(1, 1), (1, 9), (9, 1), (3, 17), (5, 1), (5, 3), (7, 5), (53, 17), (24, 1)]
for bc in (24, 32):
    for (wq, hq) in size_cases:
        dib = make_dib(wq, hq, bitcount=bc)
        png, gw, gh = dib_to_png(dib)
        check('%d位 %dx%d 返回尺寸' % (bc, wq, hq), (gw, gh) == (wq, hq), 'got %dx%d' % (gw, gh))
        sw, sh = parse_png_size(png)
        check('%d位 %dx%d IHDR 尺寸' % (bc, wq, hq), (sw, sh) == (wq, hq), 'got %dx%d' % (sw, sh))
        rw, rh, rows = parse_png_rows(png)
        ok = (rw, rh) == (wq, hq) and len(rows) == hq and all(len(r) == wq for r in rows)
        check('%d位 %dx%d 像素矩阵形状' % (bc, wq, hq), ok)
        # 逐点颜色（24位 alpha=255）
        bad = 0
        for y in range(hq):
            for x in range(wq):
                exp = (x * 5 % 256, y * 7 % 256, 128)
                g = rows[y][x]
                if g[:3] != exp:
                    bad += 1
        check('%d位 %dx%d 全像素颜色' % (bc, wq, hq), bad == 0, 'bad=%d' % bad)

# 负高度极端
for bc in (24, 32):
    for (wq, hq) in [(1, 1), (1, 4), (5, 1), (7, 3)]:
        dib = make_dib(wq, hq, bitcount=bc, topdown=True)
        png, gw, gh = dib_to_png(dib)
        sw, sh = parse_png_size(png)
        check('%d位 顶向下 %dx%d' % (bc, wq, hq), (gw, gh) == (wq, hq) == (sw, sh))

log('\n=== Part1 非法位深必须 ValueError 且不崩溃 ===')
for bc in (1, 4, 8, 16, 15, 0, 30):
    try:
        dib = make_dib(4, 4, bitcount=bc) if bc in (8, 16) else struct.pack(
            '<IiiHHIIiiII', 40, 4, 4, 1, bc, 0, 0, 0, 0, 0, 0)
        dib_to_png(dib)
        check('%d 位应 ValueError' % bc, False, '未抛异常')
    except ValueError:
        check('%d 位抛 ValueError' % bc, True)
    except Exception as e:
        check('%d 位抛 ValueError（非其他异常）' % bc, False, '%s: %s' % (type(e).__name__, e))


# ============ Part 2：活体错误路径 ============
log('\n=== Part2 活体错误路径 ===')
u32 = ctypes.WinDLL('user32', use_last_error=True)
k32 = ctypes.WinDLL('kernel32', use_last_error=True)
u32.OpenClipboard.argtypes = [w.HWND]; u32.OpenClipboard.restype = w.BOOL
u32.CloseClipboard.restype = w.BOOL
u32.EmptyClipboard.restype = w.BOOL
u32.SetClipboardData.argtypes = [w.UINT, w.HANDLE]; u32.SetClipboardData.restype = w.HANDLE
k32.GlobalAlloc.argtypes = [w.UINT, ctypes.c_size_t]; k32.GlobalAlloc.restype = w.HANDLE
k32.GlobalLock.argtypes = [w.HANDLE]; k32.GlobalLock.restype = ctypes.c_void_p
k32.GlobalUnlock.argtypes = [w.HANDLE]; k32.GlobalUnlock.restype = w.BOOL


class PE32(ctypes.Structure):
    _fields_ = [('dwSize', w.DWORD), ('u', w.DWORD), ('pid', w.DWORD),
                ('p', ctypes.POINTER(ctypes.c_ulong)), ('m1', w.DWORD), ('c', w.DWORD),
                ('m2', w.DWORD), ('base', ctypes.c_long), ('f', w.DWORD), ('exe', ctypes.c_char * 260)]


k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p


def enum_cb():
    snap = k32.CreateToolhelp32Snapshot(2, 0)
    pe = PE32(); pe.dwSize = ctypes.sizeof(PE32); out = []
    ok = k32.Process32First(snap, ctypes.byref(pe))
    while ok:
        n = pe.exe.decode('utf-8', 'ignore')
        if 'lawboard' in n.lower():
            out.append((pe.pid, n))
        ok = k32.Process32Next(snap, ctypes.byref(pe))
    k32.CloseHandle(ctypes.c_void_p(snap))
    return out


def kill(pid):
    h = k32.OpenProcess(0x0001 | 0x00100000, False, pid)
    if not h:
        return False
    r = k32.TerminateProcess(h, 0)
    k32.WaitForSingleObject(h, 3000)
    k32.CloseHandle(h)
    return bool(r)


def set_clip(fmt, data):
    if not u32.OpenClipboard(None):
        return False
    try:
        u32.EmptyClipboard()
        if fmt == 1:   # CF_TEXT
            h = k32.GlobalAlloc(0x0002, len(data))
            p = k32.GlobalLock(h)
            ctypes.memmove(p, data, len(data))
            k32.GlobalUnlock(h)
            return bool(u32.SetClipboardData(1, h))
        h = k32.GlobalAlloc(0x0002, len(data))
        p = k32.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        k32.GlobalUnlock(h)
        return bool(u32.SetClipboardData(8, h))   # CF_DIB
    finally:
        u32.CloseClipboard()


def data_images():
    try:
        d = json.load(open(DATA, encoding='utf-8'))
        return [it for it in d.get('clip', []) if it.get('content_type') == 'image']
    except Exception:
        return []


for pid, name in enum_cb():
    kill(pid)
time.sleep(0.5)

proc = subprocess.Popen([EXE222], cwd=DESKTOP)
time.sleep(5)
check('2.2.2 启动存活', any(p[1] == 'ClawBoard-2.2.2.exe' for p in enum_cb()))

# C-a: 纯文本
img0 = len(data_images())
set_clip(1, 'this is plain text 纯文本测试'.encode('utf-16-le') + b'\x00\x00')
time.sleep(2.5)
alive = any(p[1] == 'ClawBoard-2.2.2.exe' for p in enum_cb())
check('写入纯文本后进程存活', alive)
check('纯文本未误记为 image', len(data_images()) == img0, 'before=%d after=%d' % (img0, len(data_images())))

# C-b: 16 位 DIB（非法）
dib16 = struct.pack('<IiiHHIIiiII', 40, 8, 8, 1, 16, 0, 0, 0, 0, 0, 0)
img1 = len(data_images())
set_clip(8, dib16)
time.sleep(2.5)
alive2 = any(p[1] == 'ClawBoard-2.2.2.exe' for p in enum_cb())
check('写入 16 位 DIB 后进程存活（未崩溃）', alive2)
check('16 位 DIB 未新增 image', len(data_images()) == img1, 'before=%d after=%d' % (img1, len(data_images())))

# 检查 crash.log 是否在本轮新增
for pid, name in enum_cb():
    if name == 'ClawBoard-2.2.2.exe':
        kill(pid)
time.sleep(0.5)

log('\n=== 汇总 ===')
if FAIL:
    log('失败项 %d: %s' % (len(FAIL), FAIL))
else:
    log('全部通过')
