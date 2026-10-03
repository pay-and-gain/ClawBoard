# -*- coding: utf-8 -*-
"""QA-2 独立端到端复核：53x17 四角纯色 + 中心十字（24 位 & 32 位）。

与工程师的 _t_gui_image_e2e.py 的关键差异：
  - 全新尺寸 53x17（宽非 4 倍数 -> stride padding 生效：53*3=159 -> stride 160）；
  - 图案可肉眼/数值双判定：四角各一纯色，正中十字；
  - PNG 解码器为 QA-2 自己重写（不 import clawboard.image）；
  - 额外跑 32 位带 alpha 的 DIB。
单条 python 进程内完成：启进程 -> 写剪贴板 -> 轮询 -> 取证 -> 杀进程。
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

DESKTOP = r'C:\Users\pay and gain\Desktop'
EXE222 = os.path.join(DESKTOP, 'ClawBoard-2.2.2.exe')
DATA = os.path.join(DESKTOP, 'ClawBoard数据.json')

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
u32 = ctypes.WinDLL('user32', use_last_error=True)
PROCESS_QUERY_LIMITED = 0x1000
PROCESS_TERMINATE = 0x0001
SYNCHRONIZE = 0x00100000
CF_DIB = 8
GMEM_MOVEABLE = 0x0002

u32.OpenClipboard.argtypes = [w.HWND]; u32.OpenClipboard.restype = w.BOOL
u32.CloseClipboard.restype = w.BOOL
u32.EmptyClipboard.restype = w.BOOL
u32.SetClipboardData.argtypes = [w.UINT, w.HANDLE]; u32.SetClipboardData.restype = w.HANDLE
u32.GetClipboardData.argtypes = [w.UINT]; u32.GetClipboardData.restype = w.HANDLE
k32.GlobalSize.argtypes = [w.HANDLE]; k32.GlobalSize.restype = ctypes.c_size_t
k32.GlobalAlloc.argtypes = [w.UINT, ctypes.c_size_t]; k32.GlobalAlloc.restype = w.HANDLE
k32.GlobalLock.argtypes = [w.HANDLE]; k32.GlobalLock.restype = ctypes.c_void_p
k32.GlobalUnlock.argtypes = [w.HANDLE]; k32.GlobalUnlock.restype = w.BOOL

FAIL = []


def log(*a):
    print(*a, flush=True)


def check(name, cond, extra=''):
    if not cond:
        FAIL.append(name)
    log('%s %s%s' % ('OK  ' if cond else 'FAIL', name, ('  ' + extra) if extra else ''))


class PE32(ctypes.Structure):
    _fields_ = [('dwSize', w.DWORD), ('cntUsage', w.DWORD), ('th32ProcessID', w.DWORD),
                ('th32DefaultHeapID', ctypes.POINTER(ctypes.c_ulong)), ('th32ModuleID', w.DWORD),
                ('cntThreads', w.DWORD), ('th32ParentProcessID', w.DWORD),
                ('pcPriClassBase', ctypes.c_long), ('dwFlags', w.DWORD),
                ('szExeFile', ctypes.c_char * 260)]


k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p


def enum_cb():
    snap = k32.CreateToolhelp32Snapshot(2, 0)
    pe = PE32(); pe.dwSize = ctypes.sizeof(PE32); out = []
    ok = k32.Process32First(snap, ctypes.byref(pe))
    while ok:
        n = pe.szExeFile.decode('utf-8', 'ignore')
        if 'lawboard' in n.lower():
            out.append((pe.th32ProcessID, n))
        ok = k32.Process32Next(snap, ctypes.byref(pe))
    k32.CloseHandle(ctypes.c_void_p(snap))
    return out


def kill(pid):
    h = k32.OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, False, pid)
    if not h:
        return False
    r = k32.TerminateProcess(h, 0)
    k32.WaitForSingleObject(h, 3000)
    k32.CloseHandle(h)
    return bool(r)


# ---------------- 图案定义（图像坐标 x 右、y 下） ----------------
W, H = 53, 17
CROSS_X, CROSS_Y = W // 2, H // 2   # 26, 8


def pattern_rgb(x, y):
    """四角纯色 + 中心十字。返回 (R,G,B)。24 位 alpha 补 255；32 位沿用写入 alpha。"""
    if x == CROSS_X or y == CROSS_Y:
        return (255, 255, 0)               # 十字：纯黄
    if x == 0 and y == 0:
        return (255, 0, 0)                 # 左上 红
    if x == W - 1 and y == 0:
        return (0, 255, 0)                 # 右上 绿
    if x == 0 and y == H - 1:
        return (0, 0, 255)                 # 左下 蓝
    if x == W - 1 and y == H - 1:
        return (255, 0, 255)               # 右下 品红
    return (16, 32, 48)                    # 背景 深灰（R/G/B 互不相同 -> 可检出串位）


def pattern(x, y):
    return pattern_rgb(x, y) + (255,)


def make_dib(bitcount, topdown=False, w=W, h=H, alpha=255):
    bpp = bitcount // 8
    stride = ((w * bpp) + 3) & ~3
    biHeight = -h if topdown else h
    header = struct.pack('<IiiHHIIiiII', 40, w, biHeight, 1, bitcount, 0, stride * h, 0, 0, 0, 0)
    rows = []
    for y in range(h):
        row = bytearray()
        for x in range(w):
            r, g, b = pattern_rgb(x, y)
            if bitcount == 32:
                row += bytes((b, g, r, alpha))
            else:
                row += bytes((b, g, r))
        row += b'\x00' * (stride - len(row))
        rows.append(bytes(row))
    order = rows if topdown else rows[::-1]   # DIB 自底向上默认
    return header + b''.join(order)


# ---------------- QA-2 自己的 PNG 解码器 ----------------
def qa2_parse_png(png):
    """极度独立：解析签名/IHDR/IDAT/IEND，校验 CRC，逐行反 filter。"""
    assert png[:8] == b'\x89PNG\r\n\x1a\n', 'sig'
    pos = 8
    width = height = bd = ct = 0
    idat = b''
    order = []
    while pos < len(png):
        ln = struct.unpack_from('>I', png, pos)[0]
        typ = png[pos + 4:pos + 8]
        data = png[pos + 8:pos + 8 + ln]
        crc = struct.unpack_from('>I', png, pos + 8 + ln)[0]
        assert crc == (zlib.crc32(typ + data) & 0xFFFFFFFF), 'CRC %s' % typ
        if typ == b'IHDR':
            width, height, bd, ct = struct.unpack_from('>IIBB', data, 0)
        elif typ == b'IDAT':
            idat += data
        elif typ == b'IEND':
            break
        pos += 12 + ln
    assert bd == 8 and ct in (2, 6), 'unsupported png %d/%d' % (bd, ct)
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


# ---------------- 剪贴板写入 ----------------
def write_clip_dib(dib):
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
    finally:
        u32.CloseClipboard()


def read_clip():
    if not u32.OpenClipboard(None):
        log('  [clip] OpenClipboard 失败')
        return None
    try:
        h = u32.GetClipboardData(CF_DIB)
        if h:
            size = k32.GlobalSize(h)
            p = k32.GlobalLock(h)
            if p:
                try:
                    b = ctypes.string_at(p, size)
                finally:
                    k32.GlobalUnlock(h)
                return b
        return None
    finally:
        u32.CloseClipboard()


def load_data():
    with open(DATA, encoding='utf-8') as f:
        return json.load(f)


def img_count():
    try:
        return sum(1 for it in load_data().get('clip', []) if it.get('content_type') == 'image')
    except Exception:
        return -1


def run_case(bitcount, alpha=255):
    log('\n========== CASE %d 位 (alpha=%d) ==========' % (bitcount, alpha))
    before = img_count()
    log('启动前 image 记录数=%d' % before)

    # 清理可能存在的 2.2.2
    for pid, name in enum_cb():
        log('  kill 残留 pid=%d %s -> %s' % (pid, name, kill(pid)))
    time.sleep(0.5)

    proc = subprocess.Popen([EXE222], cwd=DESKTOP)
    log('启动 2.2.2 Popen pid=%d' % proc.pid)
    time.sleep(5)
    alive = [p for p in enum_cb() if p[1] == 'ClawBoard-2.2.2.exe']
    check('2.2.2 进程存活', len(alive) >= 1, str(alive))

    dib = make_dib(bitcount, topdown=False, alpha=alpha)
    log('写入 CF_DIB %dx%d bitcount=%d len=%d' % (W, H, bitcount, len(dib)))
    check('写剪贴板成功', write_clip_dib(dib))
    # 回读校验剪贴板内容与写入一致（排除写入阶段污染）
    back = read_clip()
    check('剪贴板回读字节一致', back == dib, 'len back=%s' % (len(back) if back else None))

    # 轮询等待（应用 poll 周期 400ms；给足 8s）
    got_path = None
    for i in range(16):
        time.sleep(0.5)
        n = img_count()
        if n > before:
            d = load_data()
            rec = [it for it in d['clip'] if it.get('content_type') == 'image'][0]
            got_path = rec.get('image_path')
            log('捕获成功 @%.1fs 新增 image，image_path=%s w=%s h=%s'
                % (i * 0.5 + 0.5, got_path, rec.get('image_w'), rec.get('image_h')))
            check('记录尺寸 %dx%d' % (W, H),
                  rec.get('image_w') == W and rec.get('image_h') == H,
                  'got %sx%s' % (rec.get('image_w'), rec.get('image_h')))
            break
    check('%d 位：应用捕获新 image 记录' % bitcount, got_path is not None)
    if not got_path:
        for pid, name in enum_cb():
            if name == 'ClawBoard-2.2.2.exe':
                kill(pid)
        return

    # 独立解码落盘 PNG
    fp = os.path.join(DESKTOP, 'images', got_path)
    check('落盘 PNG 存在', os.path.exists(fp), fp)
    png = open(fp, 'rb').read()
    pw, ph, rows = qa2_parse_png(png)
    check('PNG 尺寸', (pw, ph) == (W, H), '%dx%d' % (pw, ph))

    # 逐点比对（含四角与十字）
    exp_alpha = alpha if bitcount == 32 else 255
    diff = 0
    first_bad = None
    for y in range(H):
        for x in range(W):
            exp = pattern_rgb(x, y) + (exp_alpha,)
            got = rows[y][x]
            if len(got) == 3:
                got = (got[0], got[1], got[2], 255)
            if got != exp:
                diff += 1
                if first_bad is None:
                    first_bad = (x, y, exp, got)
    log('  逐点比对：%d 点，差异 %d 点' % (W * H, diff))
    check('%d 位：%d 点全等' % (bitcount, W * H), diff == 0,
          'first_bad=%s' % (first_bad,))
    # 四角显式
    corners = [(0, 0, (255, 0, 0, exp_alpha), '左上红'), (W - 1, 0, (0, 255, 0, exp_alpha), '右上绿'),
               (0, H - 1, (0, 0, 255, exp_alpha), '左下蓝'), (W - 1, H - 1, (255, 0, 255, exp_alpha), '右下品红')]
    for cx, cy, ce, nm in corners:
        g = rows[cy][cx]
        g = (g[0], g[1], g[2], 255) if len(g) == 3 else g
        check('  角 %s' % nm, g == ce, 'got=%s exp=%s' % (g, ce))
    # 十字
    check('  中心十字横', all((rows[CROSS_Y][x] + (255,) if len(rows[CROSS_Y][x]) == 3 else rows[CROSS_Y][x])[:3] == (255, 255, 0) for x in range(2, W - 2)))
    check('  中心十字竖', all((rows[y][CROSS_X] + (255,) if len(rows[y][CROSS_X]) == 3 else rows[y][CROSS_X])[:3] == (255, 255, 0) for y in range(2, H - 2)))

    # 收尾
    for pid, name in enum_cb():
        if name == 'ClawBoard-2.2.2.exe':
            log('  收尾 kill pid=%d -> %s' % (pid, kill(pid)))
    time.sleep(0.5)


# ---------------- 主流程 ----------------
log('=== QA-2 独立 E2E：图案 四角+十字，尺寸 %dx%d，宽非4倍数(stride padding) ===' % (W, H))
run_case(24)
run_case(32, alpha=200)   # 32 位带非 255 alpha：验证 alpha 是否透传

log('\n=== 汇总 ===')
if FAIL:
    log('失败项 %d: %s' % (len(FAIL), FAIL))
else:
    log('全部通过')
