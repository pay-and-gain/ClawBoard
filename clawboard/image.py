# -*- coding: utf-8 -*-
"""Pure DIB/PNG codecs with lazy compatibility wrappers for clipboard access.

Bulk bytearray slices convert pixel channels without a Python call per pixel.
Importing the codecs does not load Tk or any Windows library.
"""
import struct
import zlib

CF_DIB = 8
GMEM_MOVEABLE = 0x0002
MAX_IMAGE_PIXELS = 64_000_000
MAX_IMAGE_DIMENSION = 32768
MAX_DIB_BYTES = MAX_IMAGE_PIXELS * 4 + 4096
MAX_PNG_BYTES = MAX_IMAGE_PIXELS * 4 + 8 * 1024 * 1024
_PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'


def _dimensions(width, height):
    if (width <= 0 or height <= 0 or width > MAX_IMAGE_DIMENSION
            or height > MAX_IMAGE_DIMENSION or width * height > MAX_IMAGE_PIXELS):
        raise ValueError('图片尺寸无效或超过安全上限')


def _chunk(kind, data):
    body = kind + data
    return (struct.pack('>I', len(data)) + body
            + struct.pack('>I', zlib.crc32(body) & 0xFFFFFFFF))


def dib_to_png(dib):
    """Return (png_bytes, width, height) for 24/32-bit BGR(A) DIB data.

    Both row directions and standard-channel BI_BITFIELDS headers are supported.
    Unsupported masks are rejected rather than interpreted as pixel bytes.
    """
    if len(dib) < 40 or len(dib) > MAX_DIB_BYTES:
        raise ValueError('DIB 数据长度无效')
    size, width, signed_height, planes, depth, compression = struct.unpack_from(
        '<IiiHHI', dib, 0)
    if size < 40 or size > len(dib):
        raise ValueError('DIB 头部长度无效')
    height = abs(signed_height)
    _dimensions(width, height)
    if planes != 1 or depth not in (24, 32):
        raise ValueError('不支持的 DIB 位深（当前支持 24/32 位）')
    offset = size
    if compression == 3 and depth == 32:
        if size == 40:
            if len(dib) < 52:
                raise ValueError('DIB 缺少通道掩码')
            offset += 12
        elif size < 52:
            raise ValueError('DIB 通道掩码头部无效')
        if struct.unpack_from('<III', dib, 40) != (0x00FF0000, 0x0000FF00, 0x000000FF):
            raise ValueError('不支持的 DIB 通道掩码')
    elif compression != 0:
        raise ValueError('不支持的 DIB 压缩方式')
    offset += struct.unpack_from('<I', dib, 32)[0] * 4
    bpp = depth // 8
    row_bytes = width * bpp
    stride = (row_bytes + 3) & ~3
    if offset + stride * height > len(dib):
        raise ValueError('DIB 像素数据不完整')
    rgba_stride = width * 4
    raw_stride = rgba_stride + 1
    raw = bytearray(raw_stride * height)
    opaque = b'\xff' * width if bpp == 3 else None
    for y in range(height):
        source_y = y if signed_height < 0 else height - 1 - y
        start = offset + source_y * stride
        row = dib[start:start + row_bytes]
        target = y * raw_stride + 1
        end = target + rgba_stride
        raw[target:end:4] = row[2::bpp]
        raw[target + 1:end:4] = row[1::bpp]
        raw[target + 2:end:4] = row[0::bpp]
        raw[target + 3:end:4] = row[3::4] if bpp == 4 else opaque
    header = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
    return (_PNG_SIGNATURE + _chunk(b'IHDR', header)
            + _chunk(b'IDAT', zlib.compress(raw, 6)) + _chunk(b'IEND', b''),
            width, height)


def _png_data(png):
    if (len(png) < 8 or len(png) > MAX_PNG_BYTES
            or png[:8] != _PNG_SIGNATURE):
        raise ValueError('不是合法 PNG 或数据超过安全上限')
    pos = 8
    header = None
    idat = []
    ended = False
    while pos < len(png):
        if len(png) - pos < 12:
            raise ValueError('PNG 块头部不完整')
        length = struct.unpack_from('>I', png, pos)[0]
        end = pos + 12 + length
        if end > len(png):
            raise ValueError('PNG 块数据不完整')
        kind = png[pos + 4:pos + 8]
        data = png[pos + 8:pos + 8 + length]
        expected_crc = struct.unpack_from('>I', png, pos + 8 + length)[0]
        if zlib.crc32(kind + data) & 0xFFFFFFFF != expected_crc:
            raise ValueError('PNG 校验失败')
        if header is None and kind != b'IHDR':
            raise ValueError('PNG 缺少首个 IHDR')
        if kind == b'IHDR':
            if header is not None or length != 13:
                raise ValueError('PNG IHDR 无效')
            header = struct.unpack('>IIBBBBB', data)
            width, height, depth, color, compression, filtering, interlace = header
            _dimensions(width, height)
            if (depth != 8 or color not in (2, 6) or compression != 0
                    or filtering != 0 or interlace != 0):
                raise ValueError('只支持非交错的 8 位 RGB/RGBA PNG')
        elif kind == b'IDAT':
            idat.append(data)
        elif kind == b'IEND':
            if length or not idat:
                raise ValueError('PNG IEND 或图片数据无效')
            ended = True
            break
        elif kind != b'PLTE' and kind[:1].isupper():
            raise ValueError('不支持的 PNG 关键块')
        pos = end
    if header is None or not ended:
        raise ValueError('PNG 文件不完整')
    return header, b''.join(idat)


def _unfilter(row, previous, kind, bpp):
    if kind == 0:
        return row
    if kind == 1:
        for x in range(bpp, len(row)):
            row[x] = (row[x] + row[x - bpp]) & 0xFF
    elif kind == 2:
        for x in range(len(row)):
            row[x] = (row[x] + previous[x]) & 0xFF
    elif kind == 3:
        for x in range(len(row)):
            left = row[x - bpp] if x >= bpp else 0
            row[x] = (row[x] + ((left + previous[x]) >> 1)) & 0xFF
    elif kind == 4:
        for x in range(len(row)):
            left = row[x - bpp] if x >= bpp else 0
            above = previous[x]
            upper_left = previous[x - bpp] if x >= bpp else 0
            estimate = left + above - upper_left
            dl, da, du = (abs(estimate - left), abs(estimate - above),
                          abs(estimate - upper_left))
            predictor = left if dl <= da and dl <= du else (above if da <= du else upper_left)
            row[x] = (row[x] + predictor) & 0xFF
    else:
        raise ValueError('PNG 行过滤方式无效')
    return row


def png_to_dib(png):
    """Return (bottom_up_32bit_dib, width, height) for 8-bit RGB/RGBA PNG.

    All five row filters are decoded. The decompressor's output is capped by the
    validated dimensions before pixel allocation. Our filter-zero images take
    the fast bulk conversion path.
    """
    header, compressed = _png_data(png)
    width, height, _, color, _, _, _ = header
    bpp = 3 if color == 2 else 4
    stride = width * bpp
    raw_size = (stride + 1) * height
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(compressed, raw_size + 1)
    except zlib.error as error:
        raise ValueError('PNG 压缩数据无效') from error
    if (len(raw) != raw_size or not decoder.eof or decoder.unused_data
            or decoder.unconsumed_tail):
        raise ValueError('PNG 解压尺寸不匹配')
    dib_header = struct.pack('<IiiHHIIiiII', 40, width, height, 1, 32, 0,
                             width * height * 4, 0, 0, 0, 0)
    pixels = bytearray(width * height * 4)
    output_stride = width * 4
    opaque = b'\xff' * width if bpp == 3 else None
    previous = bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        row = _unfilter(bytearray(raw[start + 1:start + 1 + stride]),
                        previous, raw[start], bpp)
        target = (height - 1 - y) * output_stride
        end = target + output_stride
        pixels[target:end:4] = row[2::bpp]
        pixels[target + 1:end:4] = row[1::bpp]
        pixels[target + 2:end:4] = row[0::bpp]
        pixels[target + 3:end:4] = row[3::4] if bpp == 4 else opaque
        previous = row
    return dib_header + pixels, width, height


def clipboard_has_image():
    from clawboard.image_win32 import clipboard_has_image as read
    return read()


def read_clipboard_dib():
    from clawboard.image_win32 import read_clipboard_dib as read
    return read()


def write_clipboard_dib(dib):
    from clawboard.image_win32 import write_clipboard_dib as write
    return write(dib)


def __getattr__(name):
    if name in ('u32', 'k32'):
        from clawboard import image_win32
        return getattr(image_win32, name)
    raise AttributeError(name)
