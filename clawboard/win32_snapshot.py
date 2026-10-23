"""Capture one consistent Windows clipboard snapshot; never touch Tk.

Opening once keeps privacy markers and the data they describe in the same
transaction. A busy clipboard is retryable instead of being mistaken for empty.
"""
import ctypes
from ctypes import wintypes

from clawboard.clipboard import _clip_fmt_id
from clawboard.services import CaptureResult, ClipboardSnapshot
from clawboard.win32 import (
    u32, k32, shell32, CF_UNICODETEXT, CF_HDROP, capture_source, window_title_of,
    CF_NAME_EXCLUDE, CF_NAME_INCLUDE_HISTORY,
)

CF_DIB = 8
MAX_CAPTURE_BYTES = 128 * 1024 * 1024
k32.GlobalSize.argtypes = [wintypes.HANDLE]
k32.GlobalSize.restype = ctypes.c_size_t


def _bytes(format_id):
    handle = u32.GetClipboardData(format_id)
    if not handle:
        raise OSError('clipboard data unavailable')
    size = k32.GlobalSize(handle)
    if size > MAX_CAPTURE_BYTES:
        raise ValueError('clipboard item exceeds capture limit')
    pointer = k32.GlobalLock(handle)
    if not pointer:
        raise OSError('clipboard data locked')
    try:
        return ctypes.string_at(pointer, size)
    finally:
        k32.GlobalUnlock(handle)


def read_snapshot(sequence, *, private=True, own_hwnd=0, include_title=False):
    if not u32.OpenClipboard(None):
        return CaptureResult('retry')
    try:
        if private:
            exclude = _clip_fmt_id(CF_NAME_EXCLUDE)
            include = _clip_fmt_id(CF_NAME_INCLUDE_HISTORY)
            if exclude and u32.IsClipboardFormatAvailable(exclude):
                return CaptureResult('private')
            if include and u32.IsClipboardFormatAvailable(include):
                raw = _bytes(include)
                if len(raw) >= 4 and int.from_bytes(raw[:4], 'little') == 0:
                    return CaptureResult('private')
        if u32.IsClipboardFormatAvailable(CF_DIB):
            snapshot = ClipboardSnapshot(sequence, 'image', payload=_bytes(CF_DIB))
        elif u32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            raw = _bytes(CF_UNICODETEXT)
            text = raw[:len(raw) // 2 * 2].decode('utf-16-le').split('\0', 1)[0]
            snapshot = ClipboardSnapshot(sequence, 'text', text=text)
        elif u32.IsClipboardFormatAvailable(CF_HDROP):
            handle = u32.GetClipboardData(CF_HDROP)
            if not handle:
                return CaptureResult('retry')
            count = shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
            paths = []
            for index in range(min(count, 4096)):
                length = shell32.DragQueryFileW(handle, index, None, 0)
                buffer = ctypes.create_unicode_buffer(length + 1)
                if shell32.DragQueryFileW(handle, index, buffer, length + 1):
                    paths.append(buffer.value)
            snapshot = ClipboardSnapshot(sequence, 'files', text='\n'.join(paths), paths=tuple(paths))
        else:
            return CaptureResult('empty')
        if int(u32.GetClipboardSequenceNumber()) != sequence:
            return CaptureResult('retry')
    except (OSError, UnicodeError) as error:
        return CaptureResult('retry', detail=type(error).__name__)
    except ValueError:
        return CaptureResult('unsupported', detail='clipboard format exceeds supported limits')
    finally:
        u32.CloseClipboard()
    source, hwnd = capture_source(own_hwnd, delay_retry=False)
    title = window_title_of(hwnd) if include_title and hwnd else None
    from dataclasses import replace
    return CaptureResult('captured', replace(snapshot, source_app=source,
                                             source_title=title, source_hwnd=hwnd))
