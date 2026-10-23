# -*- coding: utf-8 -*-
"""开发工具，不参与产品运行：从临时合成数据的真实 Tk 窗口导出 README PNG。

仅用标准库与产品 PNG 编解码器；PrintWindow 只抓本工具自己的窗口，不抓桌面。
不启用采集、触发词、更新检查或热键；不读取真实库，只比较真实数据文件 hash。
用法：python tools/shots/capture_current.py [--output docs/images]
"""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.windows_test_guard import acquire_desktop_test_lease


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def fixtures(version):
    now = int(time.time() * 1000)
    rows = [
        ('https://github.com/pay-and-gain/ClawBoard', 'Edge', 'url', 1),
        ('项目笔记：把常用内容整理好，下一次粘贴更轻松。', '记事本', 'text', 0),
        ('def greet(name):\n    return f"Hello, {name}!"', 'VS Code', 'code', 0),
        ('{"app":"ClawBoard","version":"%s","runtime_deps":[]}' % version, 'VS Code', 'json', 0),
        ('Design for clarity. Keep the details that matter.', '记事本', 'text', 0),
        ('https://pay-and-gain.github.io/ClawBoard/', 'Edge', 'url', 0),
        ('收到，我会在确认后给你反馈。感谢耐心等待。', '聊天示例', 'text', 0),
        ('git status --short\ngit diff --check', 'Terminal', 'code', 0),
        ('https://github.com/pay-and-gain/ClawBoard/releases', 'Edge', 'url', 0),
    ]
    clips = [dict(id='shot-%d' % i, text=text, source_app=source, content_type=kind,
                  fav=fav, created_at=now - (i * 6 + 2) * 60_000, seq=len(rows) - i)
             for i, (text, source, kind, fav) in enumerate(rows)]
    phrases = [
        ('项目地址', 'https://github.com/pay-and-gain/ClawBoard', 'cbrepo'),
        ('工作回复', '收到，我会在确认后给你反馈。感谢耐心等待。', 'cbreply'),
        ('English reply', 'Thanks for the update. I will review it and get back to you.', 'cbthanks'),
        ('会议纪要', '会议主题：\n讨论要点：\n结论与待办：\n负责人：', 'cbmeet'),
        ('Python 调试', 'print(f"result={result!r}")', 'cbdebug'),
        ('检查改动', 'git status --short\ngit diff --check', 'cbcheck'),
        ('文档入口', 'https://pay-and-gain.github.io/ClawBoard/', 'cbdocs'),
    ]
    groups = [dict(name='日常与开发', items=[
        dict(id='phrase-%d' % i, name=name, text=text, trigger=trigger,
             created_at=now - i * 60_000, seq=20 - i)
        for i, (name, text, trigger) in enumerate(phrases)])]
    return clips, groups


def capture_window(root, destination, top_hwnd, dib_to_png):
    """与旧截图工具相同的 PrintWindow 路径，补全所有 64 位 GDI 句柄声明。"""
    user = ctypes.WinDLL('user32', use_last_error=True)
    gdi = ctypes.WinDLL('gdi32', use_last_error=True)
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetWindowRect.restype = wintypes.BOOL
    user.GetWindowDC.argtypes = [wintypes.HWND]
    user.GetWindowDC.restype = wintypes.HDC
    user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user.ReleaseDC.restype = ctypes.c_int
    user.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    user.PrintWindow.restype = wintypes.BOOL
    gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi.CreateCompatibleDC.restype = wintypes.HDC
    gdi.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
    gdi.SelectObject.restype = wintypes.HANDLE
    gdi.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT,
                             wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    gdi.GetDIBits.restype = ctypes.c_int
    gdi.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi.DeleteObject.restype = wintypes.BOOL
    gdi.DeleteDC.argtypes = [wintypes.HDC]
    gdi.DeleteDC.restype = wintypes.BOOL
    hwnd = top_hwnd(root)
    rectangle = wintypes.RECT()
    if not user.GetWindowRect(hwnd, ctypes.byref(rectangle)):
        raise ctypes.WinError(ctypes.get_last_error())
    width, height = rectangle.right - rectangle.left, rectangle.bottom - rectangle.top
    dc = user.GetWindowDC(hwnd)
    memory = bitmap = original = None
    try:
        memory = gdi.CreateCompatibleDC(dc)
        bitmap = gdi.CreateCompatibleBitmap(dc, width, height)
        if not memory or not bitmap:
            raise RuntimeError('cannot create screenshot bitmap')
        original = gdi.SelectObject(memory, bitmap)
        if not user.PrintWindow(hwnd, memory, 2):
            raise RuntimeError('PrintWindow failed')
        gdi.SelectObject(memory, original)
        original = None
        import struct
        header = struct.pack('<IiiHHIIiiII', 40, width, -height, 1, 32, 0,
                             width * height * 4, 0, 0, 0, 0)
        info = ctypes.create_string_buffer(header)
        pixels = ctypes.create_string_buffer(width * height * 4)
        if gdi.GetDIBits(dc, bitmap, 0, height, pixels, info, 0) != height:
            raise RuntimeError('GetDIBits failed')
        raw = bytearray(pixels.raw)
        # GDI 的 BI_RGB 高字节不是 alpha 通道；导出为不透明 PNG，保留原 RGB。
        raw[3::4] = b'\xff' * (width * height)
        png, _, _ = dib_to_png(header + raw)
        staged = destination.with_name('.%s.%s.tmp' % (destination.name, uuid.uuid4().hex))
        try:
            staged.write_bytes(png)
            staged.replace(destination)
        finally:
            staged.unlink(missing_ok=True)
        return dict(file=destination.name, width=width, height=height, bytes=len(png))
    finally:
        if original:
            gdi.SelectObject(memory, original)
        if bitmap:
            gdi.DeleteObject(bitmap)
        if memory:
            gdi.DeleteDC(memory)
        if dc:
            user.ReleaseDC(hwnd, dc)


def main():
    acquire_desktop_test_lease()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/images')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    real_paths = [ROOT / 'ClawBoard数据.json',
                  Path.home() / 'Desktop/cut/ClawBoard数据.json',
                  Path(os.environ['APPDATA']) / 'ClawBoard/ClawBoard数据.json']
    before = {path: digest(path) for path in real_paths}
    results = []
    with tempfile.TemporaryDirectory(prefix='cb-current-shots-') as directory:
        # 只在 config 叶子导入后设置路径；任何业务模块都只能看到临时目录。
        from clawboard import config, runtime
        config.BASE_DIR = directory
        config.DATA_FILE = str(Path(directory) / 'ClawBoard数据.json')
        config.CRASH_LOG = str(Path(directory) / 'crash.log')
        runtime.NO_SAVE = True
        settings = dict(config.DEFAULT_SETTINGS, listen=False, trigger_enabled=False,
                        update_check=False, sound_copy=False, sound_paste=False,
                        show_preview=False, show_toast=False, show_time=True,
                        collapsed=False, frosted=False, rounded=False, ui_scale=1.0,
                        edge_hide=False, theme='dark')
        clips, groups = fixtures(config.APP_VER)
        fixture = dict(schema_version=3, settings=settings, clip=clips, groups=groups,
                       gi=0, geom='600x780+160+160')
        path = Path(config.DATA_FILE)
        path.write_text(json.dumps(fixture, ensure_ascii=False), encoding='utf-8')
        fixture_hash = digest(path)

        import ClawBoard as C
        C.NO_SAVE = True
        import tkinter as tk
        from clawboard.win32 import top_hwnd, init_dpi_awareness
        from clawboard.image import dib_to_png
        init_dpi_awareness()
        root = tk.Tk()
        app = None
        def pump(seconds=.45):
            until = time.monotonic() + seconds
            while time.monotonic() < until:
                root.update()
                time.sleep(.01)
        def panel_shot(name):
            if app.tool.winfo_height() < config.scaled(config.TOOL_H):
                raise RuntimeError('screenshot would clip the toolbar')
            return capture_window(root, args.output / name, top_hwnd, dib_to_png)
        try:
            # 仅停用截图不需要的系统行为，真实 UI、渲染和异步搜索照常运行。
            with patch.object(C.ClawBoard, 'catchup_clipboard', lambda self: None), \
                    patch.object(C.ClawBoard, 'apply_hotkey', lambda self: None):
                app = C.ClawBoard(root)
                root.attributes('-alpha', 1.0)
                root.geometry('600x780+160+160')
                pump()
                app.sel_clip = 'shot-0'
                app.render()
                pump()
                results.append(panel_shot('main-window.png'))

                app.search.set('ClawBoard type:url')
                root.geometry('600x600+160+160')
                pump(.7)
                if app._filter_pending or len(app.vlist.items) != 3:
                    raise RuntimeError('asynchronous search did not produce three demo URLs')
                app.search_entry.icursor('end')
                results.append(panel_shot('search-highlight.png'))

                app.search.set('')
                app.tab = 'phrase'
                app.sel_phrase = 'phrase-1'
                root.geometry('600x660+160+160')
                app.render()
                pump(.6)
                results.append(panel_shot('phrases.png'))
        finally:
            if app is not None:
                app.close_preview()
                app.close_paste()
                app.bridge.close()
                app.hw.stop()
                app.hw.join(3)
            root.destroy()
            if digest(path) != fixture_hash:
                raise RuntimeError('NO_SAVE fixture changed')
            if any(digest(path) != value for path, value in before.items()):
                raise RuntimeError('real data hash changed')
    if any(digest(path) != value for path, value in before.items()):
        raise RuntimeError('real data hash changed')
    print(json.dumps(dict(screenshots=results, real_hashes_unchanged=True,
                          fixture_hash_unchanged=True), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
