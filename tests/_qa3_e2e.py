# -*- coding: utf-8 -*-
"""C. 真实源码端到端：完整 ClawBoard 实例链路验证 CF_HDROP 记录。

说明（为什么不是独立 subprocess）：
- 本机已有 2 个用户手动启动的 ClawBoard-2.2.2.exe 实例，占用了命名互斥体
  ClawBoard_SingleInstance_Mutex。此时 `python ClawBoard.py` 会在 single_instance()
  处直接 sys.exit(0)，根本无法进入轮询；且这两个 exe 是旧构建、是用户进程，不能杀。
- 因此在「同一进程内」构造真实 ClawBoard 实例（走完整 __init__ → build_ui →
  setup_system → poll_clip），只把 DATA_FILE 重定向到临时文件，避免污染真实存档。
  这是真实产品代码 + 真实 GUI + 真实 ingest/save 全链路，等价于源码直跑的应用逻辑，
  差别仅在于没有独立进程边界（受 job object 回收限制，无法在本环境后台常驻）。
"""
import ctypes
import json
import os
import struct
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TMP_DATA = os.path.join(ROOT, 'tests', '_qa3_tmpdata.json')
if os.path.exists(TMP_DATA):
    os.remove(TMP_DATA)

import clawboard.app_services as S
S.DATA_FILE = TMP_DATA          # 关键：把落盘重定向到临时文件
S.CRASH_LOG = os.path.join(ROOT, 'tests', '_qa3_tmpdata.crash.log')

from clawboard import runtime
runtime.NO_SAVE = False         # 允许落盘（写到临时文件）

import tkinter as tk
import ClawBoard as C

from clawboard.win32 import u32, k32, CF_HDROP, GMEM_MOVEABLE


def build(ps):
    header = struct.pack('<IiiII', 20, 0, 0, 0, 1)
    body = b''
    for p in ps:
        body += p.encode('utf-16-le') + b'\x00\x00'
    return header + body + b'\x00\x00'


def put(paths, tries=60):
    d = build(paths)
    for _ in range(tries):
        if not u32.OpenClipboard(None):
            time.sleep(0.05)
            continue
        try:
            u32.EmptyClipboard()
            h = k32.GlobalAlloc(GMEM_MOVEABLE, len(d))
            p = k32.GlobalLock(h)
            ctypes.memmove(p, d, len(d))
            k32.GlobalUnlock(h)
            if u32.SetClipboardData(CF_HDROP, h):
                from clawboard.clipboard import clip_read_files
                if [x.replace('/', '\\') for x in clip_read_files()] == \
                   [x.replace('/', '\\') for x in paths]:
                    return True
        finally:
            u32.CloseClipboard()
        time.sleep(0.05)
    return False


print('1) 构造真实 ClawBoard 实例...', flush=True)
init = C.init_dpi_awareness
root = tk.Tk()
root.withdraw()
C.init_dpi_awareness()
app = C.ClawBoard(root)
print('   实例已建，DATA_FILE =', TMP_DATA, flush=True)

# 确保监听开启、无忽略规则干扰
app.st['listen'] = True
app.st['ignore_apps'] = ''
app.st['ignore_titles'] = ''
app.st['record_title'] = False
app.st['skip_sensitive'] = False
app.st['min_len'] = 1

paths = [r'C:\E2E\photo one.jpg',
         r'D:\E2E\中文目录\图片.png',
         r'E:\E2E\emoji😀\shot.jpg']
expect = '\n'.join(paths)

print('2) 写入 CF_HDROP（3 条真实图片路径）...', flush=True)
wrote = put(paths)
print('   写入并回读校验:', wrote, flush=True)

print('3) 驱动真实 poll_clip（模拟序列号变化；对在场实例造成的剪贴板占用做重试）...',
      flush=True)
recorded = None
tries = 0
for tries in range(1, 13):
    wrote = put(paths)
    runtime.LAST_SEQ = -1
    app.poll_clip()
    root.update()
    time.sleep(0.6)
    root.update()
    if os.path.exists(TMP_DATA):
        with open(TMP_DATA, 'r', encoding='utf-8') as f:
            d = json.load(f)
        for it in d.get('clip', []):
            if it.get('text') == expect:
                recorded = it
                break
    if recorded:
        break
print('   尝试次数: %d，首次写入成功: %s' % (tries, wrote), flush=True)

# 4) 读取重定向后的数据文件（已在重试循环内完成）
print('4) 读取临时数据文件...', flush=True)
print('   DATA_FILE 存在:', os.path.exists(TMP_DATA), flush=True)
print('   命中条目:', json.dumps(recorded, ensure_ascii=False) if recorded else None, flush=True)

# 5) 精确断言
ok = bool(wrote and recorded and recorded.get('text') == expect)
print('C 端到端结果:', 'PASS' if ok else 'FAIL', flush=True)

# 6) 清理：销毁 GUI 实例（不调用 quit_app 以免触发真实存档逻辑）
try:
    app.hw.unreg_hotkey()
    app.hw.tray_del()
    app.hw.stop()
except Exception:
    pass
try:
    root.destroy()
except Exception:
    pass

sys.stdout.flush()
os._exit(0 if ok else 1)
