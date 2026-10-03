# -*- coding: utf-8 -*-
"""v2.0.0 自测：图片剪贴板核心（DIB → PNG 转换，24/32 位 + 正负高度）"""
import io
import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clawboard.image import dib_to_png, png_to_dib

OK = True
LOG = []


def check(name, cond, extra=''):
    global OK
    if not cond:
        OK = False
    LOG.append('%s  %s%s' % ('OK  ' if cond else 'FAIL', name,
                             ('  ' + extra) if extra else ''))


def make_dib(w, h, bitcount=32, topdown=False):
    """构造 DIB：bitcount 24(BGR)/32(BGRA)；topdown=True 用负 biHeight。

    像素颜色按图像行序生成（G 通道 = 图像行号），再按 DIB 存储顺序写入，
    这样解码后能反查行序是否被正确翻转。
    """
    bpp = bitcount // 8
    stride = ((w * bpp) + 3) & ~3
    biHeight = -h if topdown else h
    header = struct.pack('<IiiHHIIiiII', 40, w, biHeight, 1, bitcount, 0,
                         stride * h, 0, 0, 0, 0)
    image_rows = []
    for y in range(h):
        row = bytearray()
        for x in range(w):
            px = (x & 0xFF, y & 0xFF, 128)          # (B, G, R)
            if bpp == 4:
                px = px + (255,)
            row += bytes(px)
        row += b'\x00' * (stride - len(row))
        image_rows.append(bytes(row))
    order = image_rows if topdown else image_rows[::-1]
    return header + b''.join(order)


def decode_dib(dib):
    """解码任意受支持 DIB → 自顶向下 (r,g,b) 行列表（测试用）。"""
    biSize = struct.unpack_from('<I', dib, 0)[0]
    w = struct.unpack_from('<i', dib, 4)[0]
    h = struct.unpack_from('<i', dib, 8)[0]
    bitcount = struct.unpack_from('<H', dib, 14)[0]
    bpp = bitcount // 8
    topdown = h < 0
    h = abs(h)
    stride = ((w * bpp) + 3) & ~3
    px = dib[biSize:]
    rows = []
    for i in range(h):
        row = px[i * stride:i * stride + w * bpp]
        rows.append([(row[j + 2], row[j + 1], row[j])
                     for j in range(0, len(row), bpp)])   # r,g,b
    return rows if topdown else rows[::-1]


def expected_pixels(w, h):
    # make_dib 写入的像素是 (B, G, R) = (x&0xFF, y&0xFF, 128)，
    # decode_dib 返回 (R, G, B)，所以这里还原为 (128, y&0xFF, x&0xFF)。
    return [[(128, y & 0xFF, x & 0xFF) for x in range(w)] for y in range(h)]


def roundtrip_pixels(dib):
    """dib → PNG → 32 位 DIB → 解码出自顶向下像素，用于校验颜色与行序。"""
    png, w, h = dib_to_png(dib)
    dib2, w2, h2 = png_to_dib(png)
    return decode_dib(dib2), (w, h), (w2, h2)


# 1. 正常 32 位 DIB（自底向上）→ PNG，尺寸正确
dib = make_dib(40, 30)
png, w, h = dib_to_png(dib)
check('32 位 DIB → PNG 尺寸正确', (w, h) == (40, 30), '%dx%d' % (w, h))
check('PNG 签名正确', png[:8] == b'\x89PNG\r\n\x1a\n')
check('PNG 非空且已压缩', 0 < len(png) < len(dib), 'png=%d dib=%d' % (len(png), len(dib)))

# 2. 不支持的位深（16 位）仍抛 ValueError
dib16 = struct.pack('<IiiHHIIiiII', 40, 10, 10, 1, 16, 0, 0, 0, 0, 0, 0)
try:
    dib_to_png(dib16)
    check('16 位 DIB 应抛 ValueError', False)
except ValueError:
    check('16 位 DIB 抛 ValueError', True)

# 3. 24 位 DIB → PNG，尺寸正确且颜色/行序往返一致
dib24 = make_dib(24, 18, bitcount=24)
png24, w24, h24 = dib_to_png(dib24)
check('24 位 DIB → PNG 尺寸正确', (w24, h24) == (24, 18), '%dx%d' % (w24, h24))
pix24, sz24, sz24b = roundtrip_pixels(dib24)
check('24 位往返尺寸正确', sz24 == (24, 18) and sz24b == (24, 18))
check('24 位往返颜色/行序一致', pix24 == expected_pixels(24, 18))

# 4. 负高度（自顶向下）32 位 DIB → PNG，尺寸正确且颜色/行序往返一致
dib_top = make_dib(16, 12, bitcount=32, topdown=True)
pngt, wt, ht = dib_to_png(dib_top)
check('负高度 32 位 DIB → PNG 尺寸正确', (wt, ht) == (16, 12), '%dx%d' % (wt, ht))
pixt, szt, sztb = roundtrip_pixels(dib_top)
check('负高度 32 位往返尺寸正确', szt == (16, 12) and sztb == (16, 12))
check('负高度 32 位颜色/行序一致', pixt == expected_pixels(16, 12))

# 5. 负高度（自顶向下）24 位 DIB → PNG
dib24t = make_dib(8, 6, bitcount=24, topdown=True)
png24t, w24t, h24t = dib_to_png(dib24t)
check('负高度 24 位 DIB → PNG 尺寸正确', (w24t, h24t) == (8, 6), '%dx%d' % (w24t, h24t))
pix24t, sz24t, sz24tb = roundtrip_pixels(dib24t)
check('负高度 24 位颜色/行序一致', pix24t == expected_pixels(8, 6))

# 6. PNG 能被 Tk PhotoImage 加载（证明预览可行）
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

# 7. PNG → DIB 反向（粘贴图片用）：32 位自底向上往返字节一致
dib2, w2, h2 = png_to_dib(png)
check('PNG → DIB 尺寸正确', (w2, h2) == (40, 30))
check('DIB → PNG → DIB 往返一致', dib2 == dib)

with io.open(os.path.join(tempfile.gettempdir(), '_t33.out'), 'w',
             encoding='utf-8') as f:
    f.write('\n'.join(LOG) + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))
os._exit(0)
