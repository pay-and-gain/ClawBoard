# -*- coding: utf-8 -*-
"""v2.2.2 图片剪贴板端到端实测（单进程内完成，避免 GUI 被 job object 回收）。

流程：
  1. 枚举并结束 ClawBoard-1.6.4.exe 进程；
  2. 备份桌面数据文件；
  3. 把 ClawBoard-1.6.4.exe.old 移到项目下 _trash/；
  4. subprocess 启动 ClawBoard-2.2.2.exe；
  5. 等待轮询，向剪贴板写入一张 CF_DIB 测试图；
  6. 等待 poll_clip 周期，读数据文件，断言出现 content_type=='image'；
  7. 收尾：杀 2.2.2 进程。

所有关键信息写入 stdout（本脚本由一条 bash 命令运行，输出不会被吞）。
"""
import ctypes
import ctypes.wintypes as w
import json
import os
import shutil
import struct
import subprocess
import sys
import time

DESKTOP = r'C:\Users\pay and gain\Desktop'
PROJ = r'C:\Users\pay and gain\Desktop\剪切板'
EXE222 = os.path.join(DESKTOP, 'ClawBoard-2.2.2.exe')
EXE164 = os.path.join(DESKTOP, 'ClawBoard-1.6.4.exe.old')
DATA = os.path.join(DESKTOP, 'ClawBoard数据.json')
TRASH = os.path.join(PROJ, '_trash')

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
u32 = ctypes.WinDLL('user32', use_last_error=True)
PROCESS_QUERY_LIMITED = 0x1000
PROCESS_TERMINATE = 0x0001
SYNCHRONIZE = 0x00100000
WAIT_TIMEOUT = 0x102
CF_DIB = 8
GMEM_MOVEABLE = 0x0002
INFINITE = 0xFFFFFFFF

# 关键：必须声明 argtypes/restype，否则 GlobalLock 返回指针会被截断为 int，
# memmove 会写到错误地址（access violation）。参见 clawboard/image.py 声明方式。
u32.OpenClipboard.argtypes = [w.HWND]
u32.OpenClipboard.restype = w.BOOL
u32.CloseClipboard.restype = w.BOOL
u32.EmptyClipboard.restype = w.BOOL
u32.SetClipboardData.argtypes = [w.UINT, w.HANDLE]
u32.SetClipboardData.restype = w.HANDLE
k32.GlobalAlloc.argtypes = [w.UINT, ctypes.c_size_t]
k32.GlobalAlloc.restype = w.HANDLE
k32.GlobalLock.argtypes = [w.HANDLE]
k32.GlobalLock.restype = ctypes.c_void_p
k32.GlobalUnlock.argtypes = [w.HANDLE]
k32.GlobalUnlock.restype = w.BOOL


def log(*a):
    print(*a, flush=True)


class PE32(ctypes.Structure):
    _fields_ = [('dwSize', w.DWORD), ('cntUsage', w.DWORD),
                ('th32ProcessID', w.DWORD),
                ('th32DefaultHeapID', ctypes.POINTER(ctypes.c_ulong)),
                ('th32ModuleID', w.DWORD), ('cntThreads', w.DWORD),
                ('th32ParentProcessID', w.DWORD), ('pcPriClassBase', ctypes.c_long),
                ('dwFlags', w.DWORD), ('szExeFile', ctypes.c_char * 260)]


k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p


def enum_clawboard():
    snap = k32.CreateToolhelp32Snapshot(2, 0)
    pe = PE32()
    pe.dwSize = ctypes.sizeof(PE32)
    out = []
    ok = k32.Process32First(snap, ctypes.byref(pe))
    while ok:
        if 'lawboard' in pe.szExeFile.decode('utf-8', 'ignore').lower():
            out.append((pe.th32ProcessID, pe.szExeFile.decode('utf-8', 'ignore')))
        ok = k32.Process32Next(snap, ctypes.byref(pe))
    k32.CloseHandle(ctypes.c_void_p(snap))
    return out


def exe_path(pid):
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
    if not h:
        return '?'
    buf = ctypes.create_unicode_buffer(1024)
    sz = w.DWORD(1024)
    ok = k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(sz))
    k32.CloseHandle(h)
    return buf.value if ok else '?'


def kill(pid):
    h = k32.OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, False, pid)
    if not h:
        return False
    r = k32.TerminateProcess(h, 0)
    k32.WaitForSingleObject(h, 3000)
    k32.CloseHandle(h)
    return bool(r)


def make_24bpp_dib(w, h):
    """构造 24 位自底向上 DIB（BGR + stride 4 字节对齐）。"""
    stride = ((w * 3) + 3) & ~3
    header = struct.pack('<IiiHHIIiiII', 40, w, h, 1, 24, 0, stride * h,
                         0, 0, 0, 0)
    rows = []
    for y in range(h):
        row = bytearray()
        for x in range(w):
            row += bytes(((x + y) % 256, (y * 9) % 256, (x * 7) % 256))  # BGR
        row += b'\x00' * (stride - len(row))
        rows.append(bytes(row))
    return header + b''.join(rows[::-1])


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


log('=== STEP 3: ClawBoard 2.2.2 图片剪贴板端到端实测 ===')

# 1. 结束旧版 1.6.4 进程
log('[1] 结束 ClawBoard-1.6.4.exe 进程（旧版，无图片功能；仅结束进程，不动数据归档）')
before = enum_clawboard()
for pid, name in before:
    log('    found pid=%d %s -> %s' % (pid, name, exe_path(pid)))
for pid, name in before:
    log('    kill pid=%d -> %s' % (pid, kill(pid)))
time.sleep(1)
after = enum_clawboard()
log('    remaining clawboard procs after kill: %s' % after)

# 2. 备份数据文件
bak = DATA + '.bak-' + time.strftime('%Y%m%d-%H%M%S')
shutil.copy2(DATA, bak)
log('[2] 数据文件已备份 -> %s' % bak)

# 3. 把 1.6.4.exe.old 移出桌面
os.makedirs(TRASH, exist_ok=True)
dst = os.path.join(TRASH, 'ClawBoard-1.6.4.exe.old')
try:
    if os.path.exists(dst):
        os.remove(dst)
    shutil.move(EXE164, dst)
    log('[3] 已移动 %s -> %s' % (EXE164, dst))
except Exception as e:
    log('[3] 移动失败：%s' % e)
log('    桌面剩余 ClawBoard exe: %s' % [
    f for f in os.listdir(DESKTOP) if f.lower().startswith('clawboard')])

# 记录启动前数据文件里的图片记录数
try:
    with open(DATA, 'r', encoding='utf-8') as f:
        d0 = json.load(f)
    img_before = sum(1 for it in d0.get('clip', [])
                     if it.get('content_type') == 'image')
    log('[4] 启动前 clip 条数=%d，其中 image=%d，schema_version=%s' % (
        len(d0.get('clip', [])), img_before, d0.get('schema_version')))
except Exception as e:
    img_before = -1
    log('[4] 读启动前数据失败：%s' % e)

# 5. 启动 2.2.2
log('[5] 启动 %s' % EXE222)
proc = subprocess.Popen([EXE222], cwd=DESKTOP)
log('    2.2.2 Popen pid=%d' % proc.pid)
time.sleep(5)
procs = enum_clawboard()
log('    启动后 clawboard 进程:')
for pid, name in procs:
    log('      pid=%d %s -> %s' % (pid, name, exe_path(pid)))
alive222 = [p for p in procs if p[1] == 'ClawBoard-2.2.2.exe']
log('    2.2.2 存活进程数=%d' % len(alive222))

# 6. 写剪贴板图片
W, H = 37, 21
dib = make_24bpp_dib(W, H)
ok_clip = write_clip_dib(dib)
log('[6] 写入 CF_DIB 测试图 %dx%d len=%d -> %s' % (W, H, len(dib), ok_clip))

# 7. 等待 poll_clip 周期
time.sleep(6)

# 8. 读数据文件断言
try:
    with open(DATA, 'r', encoding='utf-8') as f:
        d1 = json.load(f)
    clip = d1.get('clip', [])
    imgs = [it for it in clip if it.get('content_type') == 'image']
    log('[8] 轮询后 clip 条数=%d，其中 image=%d' % (len(clip), len(imgs)))
    for it in imgs[:3]:
        log('    IMAGE REC: id=%s text=%s image_path=%s image_w=%s image_h=%s'
            % (it.get('id'), it.get('text'), it.get('image_path'),
               it.get('image_w'), it.get('image_h')))
        ip = os.path.join(DESKTOP, 'images', it.get('image_path') or '')
        log('      file exists=%s size=%s' % (
            os.path.exists(ip), os.path.getsize(ip) if os.path.exists(ip) else 0))
    verdict = 'PASS' if len(imgs) > img_before else 'FAIL'
    log('[VERDICT] 图片记录新增 %d 条 -> %s' % (len(imgs) - img_before, verdict))
except Exception as e:
    log('[8] 读数据失败：%s' % e)

# 9. 收尾：杀 2.2.2
for pid, name in enum_clawboard():
    if name == 'ClawBoard-2.2.2.exe':
        log('[9] 收尾 kill pid=%d -> %s' % (pid, kill(pid)))
time.sleep(0.5)
log('[9] 收尾后 clawboard 进程: %s' % enum_clawboard())
log('=== END STEP 3 ===')
