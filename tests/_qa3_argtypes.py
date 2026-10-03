# -*- coding: utf-8 -*-
"""D: 验证 DragQueryFileW 的 argtypes/restype 声明的必要性（原理复现，不改产品源码）。

同一剪贴板 HDROP 句柄，分别用「已声明版」与「未声明版」DragQueryFileW 读取，
对比结果，证明 64 位句柄被截断的危害。"""
import ctypes
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clawboard.win32 import u32, k32, CF_HDROP, GMEM_MOVEABLE, shell32
from clawboard.clipboard import clip_read_files

raw = ctypes.WinDLL('shell32', use_last_error=True)
raw.DragQueryFileW.restype = ctypes.c_int  # 未声明版：默认 c_int（有符号 32 位）

paths = [r'C:\aa\bb.jpg', r'D:\cc\dd.png']


def build(ps):
    header = struct.pack('<IiiII', 20, 0, 0, 0, 1)
    body = b''
    for p in ps:
        body += p.encode('utf-16-le') + b'\x00\x00'
    return header + body + b'\x00\x00'


d = build(paths)
placed = False
for _ in range(50):
    if not u32.OpenClipboard(None):
        time.sleep(0.05)
        continue
    try:
        u32.EmptyClipboard()
        h = k32.GlobalAlloc(GMEM_MOVEABLE, len(d))
        p = k32.GlobalLock(h)
        ctypes.memmove(p, d, len(d))
        k32.GlobalUnlock(h)
        u32.SetClipboardData(CF_HDROP, h)
        placed = True
    finally:
        u32.CloseClipboard()
    if placed:
        break

print('placed CF_HDROP:', placed)
print('声明版 clip_read_files():', clip_read_files())

opened = False
for _ in range(20):
    if u32.OpenClipboard(None):
        opened = True
        break
    time.sleep(0.05)
print('2nd open ok:', opened, flush=True)
if opened:
    try:
        h = u32.GetClipboardData(CF_HDROP)
        hi = bool(int(h or 0) >> 32)
        print('HDROP 句柄 int 值:', int(h or 0), ' 高 32 位非零 =', hi, flush=True)
        try:
            cnt_raw = raw.DragQueryFileW(h, 0xFFFFFFFF, None, 0)  # 未声明
        except Exception as e:
            cnt_raw = 'EXC:%r' % e
        print('未声明版 DragQueryFileW 文件数 =', cnt_raw, flush=True)
    finally:
        u32.CloseClipboard()
print('=> 声明版应得 2；未声明版若异常/错误即证明声明必要', flush=True)
