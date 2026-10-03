# -*- coding: utf-8 -*-
"""独立校验：clawboard.image.dib_to_png 的颜色/行序/尺寸正确性。

与 _t33.py 不同，本脚本：
  1. 不调用被测代码的 png_to_dib 做自证；
  2. 用完全独立的 PNG 解析器（zlib 解 IDAT + 逐行反 filter）读回像素；
  3. 覆盖 24/32 位 × 正/负高度 × 奇数宽度（触发 stride 4 字节 padding）。

判断标准：
  - 颜色正确：PNG 里 (R,G,B,A) 必须等于构造 DIB 时写入的 (R,G,B) + alpha；
    重点检测 R/B 是否串位。
  - 行序正确：PNG 第 0 行必须对应 DIB 的「图像顶部」行（G 通道 = 0），不被镜像。
  - 尺寸正确：IHDR 的 width/height 与构造一致（负高度取绝对值）。
"""
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clawboard.image import dib_to_png   # noqa: E402

OK = True
LOG = []


def check(name, cond, extra=''):
    global OK
    if not cond:
        OK = False
    LOG.append('%s  %s%s' % ('OK  ' if cond else 'FAIL', name,
                             ('  ' + extra) if extra else ''))


# --------------------------------------------------------------------------
# 独立 PNG 解析器（只用于本测试，绝不复用被测代码）
# --------------------------------------------------------------------------
def parse_png(png):
    """独立解析 PNG → (w, h, colortype, rows)。

    rows 为自顶向下列表，每个元素是 [(r,g,b,a), ...]。
    仅支持 8 位 colortype 2(RGB)/6(RGBA)，正是 dib_to_png 的输出。
    """
    assert png[:8] == b'\x89PNG\r\n\x1a\n', 'PNG 签名错误'
    pos = 8
    w = h = bitdepth = colortype = 0
    idat = b''
    while pos < len(png):
        length = struct.unpack_from('>I', png, pos)[0]
        typ = png[pos + 4:pos + 8]
        data = png[pos + 8:pos + 8 + length]
        crc_expected = struct.unpack_from('>I', png, pos + 8 + length)[0]
        crc_actual = zlib.crc32(typ + data) & 0xFFFFFFFF
        assert crc_expected == crc_actual, '%s CRC 错误' % typ
        if typ == b'IHDR':
            w, h, bitdepth, colortype = struct.unpack_from('>IIBB', data, 0)
        elif typ == b'IDAT':
            idat += data
        elif typ == b'IEND':
            break
        pos += 12 + length

    ch = {2: 3, 6: 4}[colortype]
    stride = w * ch
    raw = zlib.decompress(idat)

    # 逐行反 filter（独立实现：仅用 None/Sub/Up/Average/Paeth 标准算法）
    rows = []
    prev = bytearray(stride)
    i = 0
    for _y in range(h):
        ft = raw[i]
        i += 1
        row = bytearray(raw[i:i + stride])
        i += stride
        for x in range(stride):
            a = row[x - ch] if x >= ch else 0
            b = prev[x]
            c = prev[x - ch] if x >= ch else 0
            if ft == 1:
                row[x] = (row[x] + a) & 0xFF
            elif ft == 2:
                row[x] = (row[x] + b) & 0xFF
            elif ft == 3:
                row[x] = (row[x] + ((a + b) >> 1)) & 0xFF
            elif ft == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                row[x] = (row[x] + pr) & 0xFF
            # ft==0：None，保持原值
        px = []
        for x in range(0, stride, ch):
            if ch == 4:
                px.append((row[x], row[x + 1], row[x + 2], row[x + 3]))
            else:
                px.append((row[x], row[x + 1], row[x + 2], 255))
        rows.append(px)
        prev = row
    return w, h, rows


# --------------------------------------------------------------------------
# DIB 构造：按「图像坐标」生成像素，再按 DIB 存储顺序落盘。
# 像素颜色编码：R = x*8 % 256, G = y*8 % 256, B = (x+y)*4 % 256,
#              A = 255 (32bpp)；这样 R/B 明显不同、便于检出串位；
#              G 随行号变化，便于检出上下镜像。
# --------------------------------------------------------------------------
def make_dib(w, h, bitcount, topdown):
    bpp = bitcount // 8
    stride = ((w * bpp) + 3) & ~3
    biHeight = -h if topdown else h
    header = struct.pack('<IiiHHIIiiII', 40, w, biHeight, 1, bitcount, 0,
                         stride * h, 0, 0, 0, 0)

    def img_px(x, y):
        return (x * 8 % 256, y * 8 % 256, (x + y) * 4 % 256)   # R,G,B

    stored_rows = []
    for y in range(h):
        row = bytearray()
        for x in range(w):
            r, g, b = img_px(x, y)
            if bpp == 4:
                row += bytes((b, g, r, 255))     # BGRA（DIB 存储序）
            else:
                row += bytes((b, g, r))          # BGR
        row += b'\x00' * (stride - len(row))
        stored_rows.append(bytes(row))
    order = stored_rows if topdown else stored_rows[::-1]
    return header + b''.join(order), img_px


def expected_topdown(w, h, bitcount):
    """期望的 PNG 自顶向下像素（RGBA）。"""
    bpp = 4 if bitcount == 32 else 3
    out = []
    for y in range(h):
        row = []
        for x in range(w):
            r = x * 8 % 256
            g = y * 8 % 256
            b = (x + y) * 4 % 256
            row.append((r, g, b, 255) if bpp == 4 else (r, g, b, 255))
        out.append(row)
    return out


cases = []
for bitcount in (24, 32):
    for topdown in (False, True):
        for w in (3, 5, 7, 24):
            cases.append((bitcount, topdown, w, 6))

for bitcount, topdown, w, h in cases:
    tag = '%2d位 %s 宽%d' % (bitcount,
                             '自顶向下' if topdown else '自底向上', w)
    dib, _ = make_dib(w, h, bitcount, topdown)
    png, gw, gh = dib_to_png(dib)

    check('%s 尺寸' % tag, (gw, gh) == (w, h), 'got %dx%d' % (gw, gh))

    pw, ph, rows = parse_png(png)
    check('%s IHDR 尺寸' % tag, (pw, ph) == (w, h), 'got %dx%d' % (pw, ph))

    exp = expected_topdown(w, h, bitcount)
    check('%s 全像素(颜色+行序)一致' % tag, rows == exp,
          '首行首/末像素 got=%s exp=%s' % (
              rows[0][0] if rows else None, exp[0][0]))

    # 显式 R/B 串位检查：取一个 R 与 B 不同的像素
    r_pix = rows[0][1] if w > 1 else rows[0][0]
    check('%s R!=B 说明未串位' % tag,
          r_pix[0] != r_pix[2], 'px=%s' % (r_pix,))

    # 显式行序检查：PNG 第一行 G 应为 0，最后一行 G 应为 (h-1)*8
    check('%s 未上下镜像' % tag,
          rows[0][0][1] == 0 and rows[h - 1][0][1] == (h - 1) * 8 % 256,
          'top G=%d bottom G=%d' % (rows[0][0][1], rows[h - 1][0][1]))

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       '_t33_independent.out'), 'w', encoding='utf-8') as f:
    f.write('\n'.join(LOG) + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))
print('\n'.join(LOG))
print('\n全部通过' if OK else '\n有失败项')
