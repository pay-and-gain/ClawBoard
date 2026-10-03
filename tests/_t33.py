# -*- coding: utf-8 -*-
"""v2.0.0 自测：图片剪贴板核心（DIB → PNG 转换）"""
import io
import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clawboard.image import dib_to_png

OK = True
LOG = []


def check(name, cond, extra=''):
    global OK
    if not cond:
        OK = False
    LOG.append('%s  %s%s' % ('OK  ' if cond else 'FAIL', name,
                             ('  ' + extra) if extra else ''))


def make_dib(w, h, bitcount=32):
    bpp = bitcount // 8
    stride = ((w * bpp) + 3) & ~3
    header = struct.pack('<IiiHHIIiiII', 40, w, h, 1, bitcount, 0,
                         stride * h, 0, 0, 0, 0)
    px = b''
    for y in range(h):
        row = bytearray()
        for x in range(w):
            row += bytes((x & 0xFF, y & 0xFF, 128, 255))  # BGRA
        row += b'\x00' * (stride - len(row))
        px += bytes(row)
    return header + px


# 1. 正常 32 位 DIB → PNG，尺寸正确
dib = make_dib(40, 30)
png, w, h = dib_to_png(dib)
check('32 位 DIB → PNG 尺寸正确', (w, h) == (40, 30), '%dx%d' % (w, h))
check('PNG 签名正确', png[:8] == b'\x89PNG\r\n\x1a\n')
check('PNG 非空且已压缩', 0 < len(png) < len(dib), 'png=%d dib=%d' % (len(png), len(dib)))

# 2. 非 32 位 DIB 抛 ValueError
dib24 = make_dib(10, 10, bitcount=24)
try:
    dib_to_png(dib24)
    check('非 32 位 DIB 应抛 ValueError', False)
except ValueError:
    check('非 32 位 DIB 抛 ValueError', True)

# 3. PNG 能被 Tk PhotoImage 加载（证明预览可行）
import tkinter as tk
tmp_png = os.path.join(tempfile.gettempdir(), '_t33_img.png')
io.open(tmp_png, 'wb').write(png)
root = tk.Tk()
root.withdraw()
try:
    img = tk.PhotoImage(file=tmp_png)
    check('PhotoImage 加载 PNG 成功', (img.width(), img.height()) == (40, 30))
except Exception as e:
    check('PhotoImage 加载 PNG 成功', False, str(e))
root.destroy()

with io.open(os.path.join(tempfile.gettempdir(), '_t33.out'), 'w',
             encoding='utf-8') as f:
    f.write('\n'.join(LOG) + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))
os._exit(0)
