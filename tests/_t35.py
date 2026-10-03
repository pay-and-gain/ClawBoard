# -*- coding: utf-8 -*-
"""CF_HDROP 文件复制自测：clip_read_files() 读取资源管理器复制的文件路径。

覆盖：
1. 单元：把一组路径（含中文、多条）以 CF_HDROP 写入剪贴板，clip_read_files() 取回一致。
2. 单条路径往返一致。
3. 无 CF_HDROP 时 clip_read_files() 返回 []。
4. 回归：原有文本剪贴板 clip_read() 不受影响（clip_read_files 返回 []）。

写 CF_HDROP 的剪贴板数据构造（社区标准做法）：
DROPFILES + 宽字符路径序列（每条以 \\0 结尾，整个列表再以一个 \\0 收尾）。
DROPFILES 结构：pFiles(4) + pt.x(4) + pt.y(4) + fNC(4) + fWide(4) = 20 字节，
fWide=1 表示后面是 UTF-16 宽字符。GlobalAlloc(GMEM_MOVEABLE) 后
SetClipboardData(CF_HDROP, h) 把所有权交给剪贴板。

注意：本机可能开着 ClawBoard 实例（持续轮询剪贴板），会短暂占用剪贴板导致
EmptyClipboard 失败。因此写入用「重试 + 回读校验」的方式，确保断言基于真实生效的
剪贴板状态，避免把环境占用误判成代码缺陷。
"""
import ctypes
import os
import struct
import sys
import time
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clawboard.clipboard import clip_read_files, clip_read, clip_write
from clawboard.win32 import u32, k32, CF_HDROP, CF_UNICODETEXT, GMEM_MOVEABLE

OK = True
LOG = []


def check(name, cond, extra=''):
    global OK
    if not cond:
        OK = False
    LOG.append('%s  %s%s' % ('OK  ' if cond else 'FAIL', name,
                             ('  ' + extra) if extra else ''))


def make_dropfiles(paths):
    """构造 CF_HDROP 数据：DROPFILES 头 + 宽字符路径（每条 \\0 结尾）+ 结尾 \\0。"""
    # pFiles=20 表示路径数据相对 DROPFILES 起始的偏移；fWide=1 用 UTF-16。
    head = struct.pack('<IiiII', 20, 0, 0, 0, 1)
    body = ''.join(p + '\x00' for p in paths) + '\x00'
    return head + body.encode('utf-16-le')


def _raw_set_dropfiles(paths):
    """单次尝试把 CF_HDROP 写进剪贴板。返回是否成功。"""
    data = make_dropfiles(paths)
    if not u32.OpenClipboard(None):
        return False
    try:
        if not u32.EmptyClipboard():
            return False
        h = k32.GlobalAlloc(GMEM_MOVEABLE, len(data) + 2)
        if not h:
            return False
        p = k32.GlobalLock(h)
        if not p:
            return False
        ctypes.memmove(p, data, len(data))
        k32.GlobalUnlock(h)
        if not u32.SetClipboardData(CF_HDROP, h):
            return False
    finally:
        u32.CloseClipboard()
    return True


def set_and_confirm(paths, tries=40):
    """写入 CF_HDROP 并回读确认（应对在场 ClawBoard 实例的剪贴板占用）。"""
    expect_norm = [p.replace('/', '\\') for p in paths]  # DragQueryFile 返回反斜杠路径
    for _ in range(tries):
        if _raw_set_dropfiles(paths):
            got = clip_read_files()
            if [g.replace('/', '\\') for g in got] == expect_norm:
                return True, got
        time.sleep(0.05)
    return False, clip_read_files()


def norm(ps):
    return [p.replace('/', '\\') for p in ps]


# 1. 多条路径（含中文）→ clip_read_files() 取回一致
paths = [r'C:\Users\pay and gain\Desktop\剪切板\clawboard\clipboard.py',
         r'C:\Windows\notepad.exe',
         r'D:\资料\图片\示例.png']
try:
    ok, got = set_and_confirm(paths)
    check('CF_HDROP 多条路径（含中文）往返一致', ok and norm(got) == norm(paths),
          'got=%r' % (got,))
except Exception as e:
    check('CF_HDROP 多条路径往返', False, repr(e))

# 2. 单条路径
try:
    single = [r'C:\Temp\a b c\单文件.txt']
    ok, got1 = set_and_confirm(single)
    check('CF_HDROP 单条路径往返一致', ok and norm(got1) == norm(single),
          'got=%r' % (got1,))
except Exception as e:
    check('CF_HDROP 单条路径往返', False, repr(e))

# 3. 无 CF_HDROP（写普通文本）→ 应返回 []
try:
    text_written = False
    for _ in range(40):
        if clip_write('hello 这是一段普通文本'):
            if clip_read() == 'hello 这是一段普通文本':
                text_written = True
                break
        time.sleep(0.05)
    got_none = clip_read_files()
    check('无 CF_HDROP（文本）时返回 []', text_written and got_none == [],
          'written=%s got=%r' % (text_written, got_none))
except Exception as e:
    check('无 CF_HDROP（文本）时返回 []', False, repr(e))

# 4. 回归：文本路径不受影响
try:
    got_txt = clip_read()
    check('回归-文本剪贴板 clip_read 正常', got_txt == 'hello 这是一段普通文本',
          'got=%r' % (got_txt,))
except Exception as e:
    check('回归-文本剪贴板 clip_read 正常', False, repr(e))

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '_t35.out'),
          'w', encoding='utf-8') as f:
    f.write('\n'.join(LOG) + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))
os._exit(0)
