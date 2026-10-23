# -*- coding: utf-8 -*-
"""剪贴板读写 + 隐私标记 + 敏感内容识别。

clip_seq/read/write 只操作 CF_UNICODETEXT；clip_is_private 遵守 Windows 官方
「别记录我」标记；scan_sensitive/mask_text 负责敏感词识别与打码。
"""
import ctypes
import os
import re
import struct

from clawboard import runtime
from clawboard.config import EMAIL_SCAN_MAXLEN
from clawboard.win32 import (
    u32, k32, CF_UNICODETEXT, CF_HDROP, GMEM_MOVEABLE,
    CF_NAME_EXCLUDE, CF_NAME_INCLUDE_HISTORY, shell32,
)

k32.GlobalFree.argtypes = [ctypes.c_void_p]
k32.GlobalFree.restype = ctypes.c_void_p
k32.GlobalSize.argtypes = [ctypes.c_void_p]
k32.GlobalSize.restype = ctypes.c_size_t

# 这是自写确认元数据，不是 Windows 的隐私/历史排除标记。
_OWN_WRITE_FORMAT = 'ClawBoard.WriteToken.v1'


def clip_seq():
    try:
        return u32.GetClipboardSequenceNumber()
    except Exception:
        return 0


def clip_read():
    if not u32.OpenClipboard(None):
        return None
    try:
        h = u32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = k32.GlobalLock(h)
        if not p:
            return None
        try:
            return ctypes.wstring_at(p)
        finally:
            k32.GlobalUnlock(h)
    finally:
        u32.CloseClipboard()


def _write_own_marker():
    """在已有写事务中附加随机 token；失败不影响已写好的正文。"""
    handle = None
    transferred = False
    try:
        fmt = _clip_fmt_id(_OWN_WRITE_FORMAT)
        if not fmt:
            return None
        token = os.urandom(16)
        handle = k32.GlobalAlloc(GMEM_MOVEABLE, len(token))
        if not handle:
            return None
        pointer = k32.GlobalLock(handle)
        if not pointer:
            return None
        try:
            ctypes.memmove(pointer, token, len(token))
        finally:
            k32.GlobalUnlock(handle)
        transferred = bool(u32.SetClipboardData(fmt, handle))
        return (fmt, token) if transferred else None
    except Exception:
        return None
    finally:
        if handle and not transferred:
            try:
                k32.GlobalFree(handle)
            except Exception:
                pass


def _ack_own_write(sequence, marker):
    """只在读锁内核实 token 后接受 CloseClipboard 合成格式后的序列。

    关闭写事务后外部应用可能立刻复制；直接读当前序列会把它误当成自写。
    无法重新加锁或标记已变时，只确认写事务内取得的安全序列。
    """
    opened = False
    try:
        if marker and u32.OpenClipboard(None):
            opened = True
            fmt, token = marker
            handle = u32.GetClipboardData(fmt)
            if handle and k32.GlobalSize(handle) >= len(token):
                pointer = k32.GlobalLock(handle)
                if pointer:
                    try:
                        if ctypes.string_at(pointer, len(token)) == token:
                            sequence = clip_seq()
                    finally:
                        k32.GlobalUnlock(handle)
    except Exception:
        pass
    finally:
        if opened:
            try:
                u32.CloseClipboard()
            except Exception:
                pass
    runtime.LAST_SEQ = sequence
    runtime.LAST_WRITE_SEQ = sequence


# DragQueryFileW(hDrop, 0xFFFFFFFF, NULL, 0) 返回文件个数（不取路径）
_DRAGQUERY_COUNT = 0xFFFFFFFF


def clip_read_files():
    """读取剪贴板里的 CF_HDROP 文件列表（资源管理器 Ctrl+C 复制文件时）。

    Windows 在资源管理器里复制文件时不放 CF_UNICODETEXT，只放 CF_HDROP（格式 15），
    所以 clip_read() 会返回 None、上层看不到任何内容。这里用 shell32.DragQueryFileW
    把被复制文件的完整路径逐个取出来。返回 list[str]；无文件/失败返回 []。

    注意：DragQueryFileW 的第一个参数就是 GetClipboardData(CF_HDROP) 返回的 HDROP
    句柄本身（64 位），其 argtypes/restype 已在 win32 里声明，避免句柄被截断。
    本函数只在此处开一次剪贴板，不要在 OpenClipboard 期间嵌套调用别的开剪贴板的函数。
    """
    if not u32.IsClipboardFormatAvailable(CF_HDROP):
        return []
    if not u32.OpenClipboard(None):
        return []
    try:
        h = u32.GetClipboardData(CF_HDROP)
        if not h:
            return []
        n = shell32.DragQueryFileW(h, _DRAGQUERY_COUNT, None, 0)
        if not n:
            return []
        paths = []
        for i in range(int(n)):
            need = shell32.DragQueryFileW(h, i, None, 0)   # 该路径的字符数（不含结尾 NUL）
            if not need:
                continue
            buf = ctypes.create_unicode_buffer(need + 1)
            if shell32.DragQueryFileW(h, i, buf, need + 1):
                p = buf.value
                if p:
                    paths.append(p)
        return paths
    except Exception:
        return []
    finally:
        u32.CloseClipboard()


# ---- 反向：把路径列表写回剪贴板（CF_HDROP），让粘出去的是「真正的文件」 ----
_DROPFILES_SIZE = 20        # pFiles(4) + pt.x(4) + pt.y(4) + fNC(4) + fWide(4)


def build_hdrop(paths):
    """构造 CF_HDROP 内存块：DROPFILES 头 + 宽字符路径序列（逐条 \\0，列表尾再一个 \\0）。"""
    head = ctypes.create_string_buffer(_DROPFILES_SIZE)
    ctypes.memset(head, 0, _DROPFILES_SIZE)
    struct.pack_into('<I', head, 0, _DROPFILES_SIZE)   # pFiles：路径数据相对头部的偏移
    struct.pack_into('<I', head, 16, 1)                # fWide=1：后面是 UTF-16 宽字符
    body = b''
    for p in paths:
        body += p.encode('utf-16-le') + b'\x00\x00'
    body += b'\x00\x00'                                # 整个列表以双 NUL 结束
    return head.raw + body


def clip_write_files(paths):
    """把一组文件路径写进剪贴板（CF_HDROP）。

    与 clip_write 的区别：资源管理器复制文件时**只放 CF_HDROP、不放文本**，
    所以这里也保持文件格式、不附加文本 —— 粘贴到聊天窗口是「发送文件」、粘贴到资源管理器
    是「复制文件」，而不是粘出一串路径文字。
    """
    paths = [p for p in (paths or []) if p]
    if not paths:
        return False
    raw = build_hdrop(paths)
    if not u32.OpenClipboard(None):
        return False
    try:
        if not u32.EmptyClipboard():
            return False
        h = k32.GlobalAlloc(GMEM_MOVEABLE, len(raw))
        if not h:
            return False
        p = k32.GlobalLock(h)
        if not p:
            k32.GlobalFree(h)
            return False
        ctypes.memmove(p, raw, len(raw))
        k32.GlobalUnlock(h)
        if not u32.SetClipboardData(CF_HDROP, h):
            k32.GlobalFree(h)
            return False
        marker = _write_own_marker()
        sequence = clip_seq()
    finally:
        u32.CloseClipboard()
    _ack_own_write(sequence, marker)
    return True


_MAX_FILE_LINES = 50        # 超过这么多行就不按文件列表判断，省掉无谓的磁盘探测


def looks_like_file_list(text):
    """文本是否是一串「真实存在的本地路径」（每行一条）。

    资源管理器复制文件时，我们记录下来的正是这种多行路径文本（见 app_services.poll_clip）。
    粘贴时用它把「路径文字」还原成「真正的文件」—— 好处是**数据格式完全不用动**：
    老版本（包括共用一个数据文件的 C 版）读到的仍然只是普通文本，互不影响。

    判定刻意从严：行数有上限、每行必须是绝对路径、且必须真实存在。
    普通多行文本（日志、代码、清单）几乎不可能整段满足，所以不会误判。
    """
    if not text:
        return False
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines or len(lines) > _MAX_FILE_LINES:
        return False
    for ln in lines:
        is_drive = len(ln) > 2 and ln[1] == ':' and ln[0].isalpha()   # C:\...
        if not is_drive and not ln.startswith('\\\\'):                # \\server\share
            return False
        if not os.path.exists(ln):
            return False
    return True


def clip_write(text):
    """写入剪贴板。成功后同步 LAST_SEQ，避免自己的回写被监听重复入库。"""
    data = text.encode('utf-16-le') + b'\x00\x00'
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
            k32.GlobalFree(h)
            return False
        ctypes.memmove(p, data, len(data))
        k32.GlobalUnlock(h)
        if not u32.SetClipboardData(CF_UNICODETEXT, h):
            k32.GlobalFree(h)
            return False
        marker = _write_own_marker()
        sequence = clip_seq()
    finally:
        u32.CloseClipboard()
    _ack_own_write(sequence, marker)
    return True


# ---- 隐私标记：Windows 让应用声明「这条别记进历史」----
_priv_fmt_cache = {}


def _clip_fmt_id(name):
    if name not in _priv_fmt_cache:
        try:
            _priv_fmt_cache[name] = int(u32.RegisterClipboardFormatW(name) or 0)
        except Exception:
            _priv_fmt_cache[name] = 0
    return _priv_fmt_cache[name]


def clip_is_private():
    """剪贴板上带着官方「不要记录」标记时返回 True。
    CanIncludeInClipboardHistory 存在且前 4 字节为 0，或
    ExcludeClipboardContentFromMonitorProcessing 存在即忽略 —— 两项都是 Windows 给
    密码管理器用的信号（Ditto src/Clip.cpp:364 与 :400），比敏感词正则准得多。"""
    ex = _clip_fmt_id(CF_NAME_EXCLUDE)
    inc = _clip_fmt_id(CF_NAME_INCLUDE_HISTORY)
    if not ex and not inc:
        return False
    if not u32.OpenClipboard(None):
        return False
    try:
        if ex and u32.IsClipboardFormatAvailable(ex):
            return True
        if inc and u32.IsClipboardFormatAvailable(inc):
            h = u32.GetClipboardData(inc)
            if h:
                p = k32.GlobalLock(h)
                if p:
                    try:
                        if ctypes.c_uint32.from_address(p).value == 0:
                            return True
                    finally:
                        k32.GlobalUnlock(h)
    except Exception:
        return False
    finally:
        u32.CloseClipboard()
    return False


# 导入时把剪贴板序列号缓存初始化为当前值，避免启动后立刻把剪贴板旧内容重复入库。
runtime.LAST_SEQ = clip_seq()

# Compatibility exports; recognition itself has no Win32 dependency.
from clawboard.privacy import SENS_PATTERNS, scan_sensitive, mask_text
