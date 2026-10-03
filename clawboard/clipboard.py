# -*- coding: utf-8 -*-
"""剪贴板读写 + 隐私标记 + 敏感内容识别。

clip_seq/read/write 只操作 CF_UNICODETEXT；clip_is_private 遵守 Windows 官方
「别记录我」标记；scan_sensitive/mask_text 负责敏感词识别与打码。
"""
import ctypes
import re

from clawboard import runtime
from clawboard.win32 import (
    u32, k32, CF_UNICODETEXT, CF_HDROP, GMEM_MOVEABLE,
    CF_NAME_EXCLUDE, CF_NAME_INCLUDE_HISTORY, shell32,
)


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


def clip_write(text):
    """写入剪贴板。成功后同步 LAST_SEQ，避免自己的回写被监听重复入库。"""
    data = text.encode('utf-16-le') + b'\x00\x00'
    if not u32.OpenClipboard(None):
        return False
    try:
        u32.EmptyClipboard()
        h = k32.GlobalAlloc(GMEM_MOVEABLE, len(data) + 2)
        if not h:
            return False
        p = k32.GlobalLock(h)
        if not p:
            return False
        ctypes.memmove(p, data, len(data))
        k32.GlobalUnlock(h)
        if not u32.SetClipboardData(CF_UNICODETEXT, h):
            return False
    finally:
        u32.CloseClipboard()
    runtime.LAST_SEQ = clip_seq()
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

SENS_PATTERNS = [
    ('身份证', re.compile(r'(?<!\d)\d{17}[\dXx](?!\d)')),
    ('银行卡', re.compile(r'(?<!\d)\d{16,19}(?!\d)')),
    ('手机号', re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)')),
    ('邮箱', re.compile(r'[\w.+-]+@[\w-]+\.[\w.]{2,}')),
    ('Token', re.compile(r'(?:sk-|ghp_|xox[baprs]-|Bearer\s+)[A-Za-z0-9_\-]{8,}')),
    ('密码', re.compile(r'(?i)(password|passwd|pwd|密码|口令)\s*[:：=]\s*\S{4,}')),
]


def scan_sensitive(text):
    try:
        return [name for name, pat in SENS_PATTERNS if pat.search(text or '')]
    except Exception:
        return []


def mask_text(text, hits):
    def rep(m):
        s = m.group(0)
        return s[:3] + '*' * max(3, len(s) - 5) + s[-2:]
    out = text
    for name, pat in SENS_PATTERNS:
        if name in hits:
            out = pat.sub(rep, out)
    return out
