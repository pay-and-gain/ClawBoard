# -*- coding: utf-8 -*-
"""看剪贴板：列出 Windows 系统剪贴板当前所有格式，判断里面有没有图片。

用法（双击或命令行）：
    python 看剪贴板.py

零依赖，仅用 ctypes 直调 Win32 API。
"""
import ctypes
from ctypes import wintypes as w

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# 常用剪贴板格式
FORMATS = {
    1:  'CF_TEXT',
    2:  'CF_BITMAP      ← 有它说明剪贴板里有位图',
    3:  'CF_METAFILEPICT',
    8:  'CF_DIB         ← 有它说明剪贴板里有图像数据（设备无关位图）',
    13: 'CF_UNICODETEXT ← 有它说明是文本',
    14: 'CF_ENHMETAFILE',
    15: 'CF_HDROP       ← 有它说明复制的是「文件」（路径，不是图片本身）',
    17: 'CF_DIBV5       ← DIB 的 V5 版，也是图像',
}

user32.OpenClipboard.argtypes = [w.HWND]
user32.OpenClipboard.restype = w.BOOL
user32.CloseClipboard.restype = w.BOOL
user32.EnumClipboardFormats.argtypes = [w.UINT]
user32.EnumClipboardFormats.restype = w.UINT
user32.GetClipboardFormatNameW.argtypes = [w.UINT, w.LPWSTR, ctypes.c_int]
user32.GetClipboardFormatNameW.restype = ctypes.c_int
user32.RegisterClipboardFormatW.argtypes = [w.LPCWSTR]
user32.RegisterClipboardFormatW.restype = w.UINT


def name_of(fmt):
    if fmt in FORMATS:
        return FORMATS[fmt]
    buf = ctypes.create_unicode_buffer(256)
    n = user32.GetClipboardFormatNameW(fmt, buf, 256)
    if n > 0:
        return '注册格式: %s' % buf.value
    return '格式 %d' % fmt


def main():
    if not user32.OpenClipboard(None):
        print('打不开剪贴板（可能被别的程序占用，稍后再试）')
        return
    try:
        fmts = []
        f = 0
        while True:
            f = user32.EnumClipboardFormats(f)
            if f == 0:
                break
            fmts.append(f)
    finally:
        user32.CloseClipboard()

    if not fmts:
        print('剪贴板是空的。')
        return

    print('剪贴板当前包含 %d 种格式：' % len(fmts))
    for f in fmts:
        print('  -', name_of(f))

    has_img = any(f in (2, 8, 17) for f in fmts)
    has_hdrop = 15 in fmts
    has_text = 13 in fmts or 1 in fmts

    print()
    if has_img:
        print('✅ 剪贴板里有图片 —— 可以粘贴到 ClawBoard / 画图 / 聊天窗口。')
        if has_hdrop:
            print('   注意：同时也含「文件」格式，说明可能是从文件夹复制的图片文件。')
    elif has_hdrop:
        print('⚠️  剪贴板里是「文件」（路径），不是图像数据。')
        print('   → 在资源管理器里 Ctrl+C 一张图，复制的是路径，不是图片本身。')
        print('   → 要复制图片本身：用截图工具，或在浏览器/看图软件里右键「复制图像」。')
    elif has_text:
        print('❌ 剪贴板里是纯文本，没有图片。')
    else:
        print('❓ 剪贴板里有内容，但没有图片也没有可识别的文本。')


if __name__ == '__main__':
    main()
