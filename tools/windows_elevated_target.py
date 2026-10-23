"""开发工具，不参与产品运行：仅显示合成文本的管理员输入验收靶。

本工具不提权、不导入产品、不执行输入内容。调用方须预建 TEMP 直属的
ClawBoard-elevated-* 目录及 target-request.json（内容为 {"token": nonce}），
再自行经 UAC 以高完整性启动。状态文件也须由普通权限驱动预建，双方
用偏移 0、长度 1 的文件锁保护原位状态读写，保留原文件权限和所有者；
正文不落文件。关闭或十分钟到期只销毁本进程自己的测试窗口。
"""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time

ADMIN_TEXT = 'ClawBoard 管理员验收 ABC-123 😀'
INITIAL_TEXT = 'KEEP| '
HIGH_INTEGRITY = 0x3000
TARGET_LIFETIME_MS = 10 * 60 * 1000
_NONCE = re.compile(r'[A-Za-z0-9_-]{8,128}\Z')


def _not_reparse(path):
    info = path.lstat()
    return not (stat.S_ISLNK(info.st_mode)
                or getattr(info, 'st_file_attributes', 0) & 0x400)


def validate_session(session, token):
    """Reject paths outside the marked, direct child of this user's TEMP."""
    if not isinstance(token, str) or not _NONCE.fullmatch(token):
        raise ValueError('invalid acceptance token')
    candidate = Path(session)
    if not candidate.is_absolute() or not _not_reparse(candidate):
        raise ValueError('session must be an absolute, ordinary directory')
    directory = candidate.resolve(strict=True)
    temporary_root = Path(tempfile.gettempdir()).resolve(strict=True)
    if (not directory.is_dir() or directory.parent != temporary_root
            or not directory.name.startswith('ClawBoard-elevated-')
            or directory.name == 'ClawBoard-elevated-'):
        raise ValueError('session must be a ClawBoard-elevated-* child of TEMP')
    marker = directory / 'target-request.json'
    if not _not_reparse(marker) or not marker.is_file() or marker.stat().st_size > 2048:
        raise ValueError('invalid acceptance marker')
    request = json.loads(marker.read_text(encoding='utf-8'))
    if not isinstance(request, dict) or request.get('token') != token:
        raise ValueError('acceptance marker token does not match')
    status = directory / 'target-status.json'
    if os.path.lexists(status) and (not _not_reparse(status) or not status.is_file()):
        raise ValueError('status must be an ordinary file')
    return directory


def read_integrity_level():
    """Read only this process's TokenIntegrityLevel; raise on unknown state."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    security = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    security.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                         ctypes.POINTER(wintypes.HANDLE)]
    security.OpenProcessToken.restype = wintypes.BOOL
    security.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                           ctypes.c_void_p, wintypes.DWORD,
                                           ctypes.POINTER(wintypes.DWORD)]
    security.GetTokenInformation.restype = wintypes.BOOL
    security.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
    security.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    security.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    security.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)
    token = wintypes.HANDLE()
    if not security.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        required = wintypes.DWORD()
        security.GetTokenInformation(token, 25, None, 0, ctypes.byref(required))
        if not 0 < required.value <= 65536:
            raise RuntimeError('invalid token integrity buffer size')
        buffer = ctypes.create_string_buffer(required.value)
        if not security.GetTokenInformation(token, 25, buffer, len(buffer), ctypes.byref(required)):
            raise ctypes.WinError(ctypes.get_last_error())
        # TOKEN_MANDATORY_LABEL starts with SID_AND_ATTRIBUTES; its first field
        # is a pointer, so use pointer width even on a 64-bit Python build.
        sid = ctypes.c_void_p.from_buffer(buffer).value
        if not sid:
            raise RuntimeError('token has no integrity SID')
        count = security.GetSidSubAuthorityCount(sid)
        if not count or not 1 <= count[0] <= 15:
            raise RuntimeError('invalid integrity SID')
        rid = security.GetSidSubAuthority(sid, count[0] - 1)
        if not rid:
            raise RuntimeError('token has no integrity RID')
        return int(rid[0])
    finally:
        kernel.CloseHandle(token)


def _write_status(session, token, report):
    import msvcrt

    # Recheck the marker during the heartbeat too; replacing the session path
    # or changing the request must not redirect a privileged status write.
    directory = validate_session(session, token)
    target = directory / 'target-status.json'
    report = dict(report, updated_at=time.time())
    payload = (json.dumps(report, ensure_ascii=False) + '\n').encode('utf-8')
    # A new file made by an elevated token may be owned by Administrators.
    # Replacing the medium-created status would then make OWNER RIGHTS deny
    # the ordinary driver. Opening the existing file preserves owner and label.
    with target.open('r+b', buffering=0) as stream:
        deadline = time.monotonic() + 0.5
        while True:
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.02)
        try:
            validate_session(session, token)
            stream.seek(0)
            remaining = memoryview(payload)
            while remaining:
                written = stream.write(remaining)
                if not written:
                    raise OSError('incomplete target status write')
                remaining = remaining[written:]
            stream.truncate()
            stream.flush()
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def run_target(session, token):
    if os.name != 'nt':
        raise RuntimeError('Windows is required')
    directory = validate_session(session, token)
    integrity = read_integrity_level()
    if integrity < HIGH_INTEGRITY:
        raise PermissionError('high integrity is required; no window was created')
    import tkinter as tk

    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    graphics = ctypes.WinDLL('gdi32', use_last_error=True)
    user.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
        wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
    user.CreateWindowExW.restype = wintypes.HWND
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user.GetWindowTextLengthW.restype = ctypes.c_int
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetWindowTextW.restype = ctypes.c_int
    user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.SendMessageW.restype = ctypes.c_ssize_t
    user.SetFocus.argtypes = [wintypes.HWND]
    user.SetFocus.restype = wintypes.HWND
    user.MoveWindow.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, wintypes.BOOL]
    user.MoveWindow.restype = wintypes.BOOL
    kernel.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel.GetModuleHandleW.restype = wintypes.HMODULE
    graphics.GetStockObject.argtypes = [ctypes.c_int]
    graphics.GetStockObject.restype = wintypes.HGDIOBJ

    report = dict(pid=os.getpid(), hwnd=0, edit_hwnd=0, token=token, integrity=integrity,
                  ready=False, closed=False, initial_matches=False, expected_matches=False,
                  length=0, length_units='utf16')
    _write_status(directory, token, report)
    root = None
    edit = 0
    closed = False
    try:
        root = tk.Tk()
        root.withdraw()
        root.title('ClawBoard Admin Acceptance - ' + token)
        root.geometry('720x280+150+150')
        root.minsize(520, 240)
        tk.Label(root, text='管理员输入验收靶 · 仅合成文本，不执行命令',
                 font=('Microsoft YaHei UI', 12)).pack(anchor='w', padx=20, pady=(18, 6))
        tk.Label(root, text='请等待指导。自动粘贴被拒绝后，再在下方输入框手动按 Ctrl+V。',
                 font=('Microsoft YaHei UI', 10)).pack(anchor='w', padx=20)
        tk.Label(root, text='权限 RID: 0x%04X · PID: %d · 最长保留十分钟' % (integrity, os.getpid()),
                 font=('Microsoft YaHei UI', 9)).pack(side='bottom', anchor='w', padx=20, pady=12)
        root.update_idletasks()
        host = int(root.winfo_id())
        top = int(user.GetAncestor(host, 2) or host)
        # A real multiline EDIT accepts physical Ctrl+V and cannot execute its
        # contents. No process-wide hooks or clipboard listener are needed.
        style = 0x40000000 | 0x10000000 | 0x00800000 | 0x00200000 | 0x00010000 | 0x0044 | 0x1000
        edit = int(user.CreateWindowExW(0, 'EDIT', INITIAL_TEXT, style,
                       20, 92, 680, 130, host, None, kernel.GetModuleHandleW(None), None) or 0)
        if not edit:
            raise ctypes.WinError(ctypes.get_last_error())
        user.SendMessageW(edit, 0x0030, graphics.GetStockObject(17), True)
        user.SendMessageW(edit, 0x00B1, len(INITIAL_TEXT), len(INITIAL_TEXT))
        report.update(hwnd=top, edit_hwnd=edit)

        def snapshot():
            length = max(0, int(user.GetWindowTextLengthW(edit)))
            # The driver sends one small fixture. Bound accidental large input
            # without storing any of its text in the evidence file.
            buffer = ctypes.create_unicode_buffer(min(length, 8192) + 1)
            user.GetWindowTextW(edit, buffer, len(buffer))
            text = buffer.value
            report.update(length=length, initial_matches=text == INITIAL_TEXT and length < 8193,
                          expected_matches=text == INITIAL_TEXT + ADMIN_TEXT and length < 8193)

        def close():
            nonlocal closed
            if closed:
                return
            closed = True
            snapshot()
            report.update(ready=False, closed=True)
            try:
                _write_status(directory, token, report)
            finally:
                root.destroy()

        def heartbeat():
            if closed:
                return
            try:
                snapshot()
                _write_status(directory, token, report)
            except Exception:
                close()
                return
            root.after(200, heartbeat)

        def resize(event):
            if event.widget is root:
                user.MoveWindow(edit, 20, 92, max(100, event.width - 40),
                                max(65, event.height - 145), True)

        root.protocol('WM_DELETE_WINDOW', close)
        root.bind('<Configure>', resize)
        root.deiconify()
        root.update()
        root.focus_force()
        user.SetFocus(edit)
        report['ready'] = True
        heartbeat()
        root.after(TARGET_LIFETIME_MS, close)
        root.mainloop()
    finally:
        if not closed:
            try:
                if edit:
                    length = max(0, int(user.GetWindowTextLengthW(edit)))
                    report['length'] = length
                report.update(ready=False, closed=True)
                _write_status(directory, token, report)
            finally:
                if root is not None:
                    root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Synthetic administrator EDIT target; does not request elevation.')
    parser.add_argument('--session', required=True)
    parser.add_argument('--token', required=True)
    arguments = parser.parse_args(argv)
    run_target(arguments.session, arguments.token)


if __name__ == '__main__':
    main()
