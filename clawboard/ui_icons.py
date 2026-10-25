"""Small original PNG resources with bounded, interpreter-local Tk image caches.

The build-time rasterizer is a development tool. Runtime recoloring/resizing uses
the existing standard-library PNG codec, so assets do not add a PIL dependency.
"""
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path
import struct
import sys
import threading
import zlib

from clawboard.image import png_to_dib
from clawboard.theme import T

ICON_NAMES = frozenset(('add', 'delete', 'split', 'clear', 'transform', 'settings',
                        'more', 'pin', 'collapse', 'close', 'workbench', 'filter',
                        'text', 'link', 'image', 'file', 'code', 'search', 'copy',
                        'edit', 'folder', 'check', 'back', 'next', 'restore', 'clock'))
MAX_TK_IMAGES = 128


def asset_directory():
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'ui-assets'
    return Path(__file__).resolve().parents[1] / 'packaging/ui-assets'


def _chunk(kind, data):
    payload = kind + data
    return struct.pack('>I', len(data)) + payload + struct.pack('>I', zlib.crc32(payload) & 0xffffffff)


@lru_cache(maxsize=32)
def _pixels(path):
    dib, width, height = png_to_dib(Path(path).read_bytes())
    stride = width * 4
    rows = []
    for y in range(height):
        start = 40 + (height - 1 - y) * stride
        row = dib[start:start + stride]
        rgba = bytearray(stride)
        rgba[0::4], rgba[1::4], rgba[2::4], rgba[3::4] = row[2::4], row[1::4], row[0::4], row[3::4]
        rows.append(bytes(rgba))
    return width, height, rows


def render_icon_png(name, size=16, color='#5c6d61'):
    """Return a tinted RGBA PNG without constructing Tk or reading user data.

    `size` is an actual pixel size. Logo tint is intentionally ignored; it keeps
    its original paper/paw colors and has exact build-time small-size variants.
    """
    if name not in ICON_NAMES and name != 'logo':
        raise ValueError('unknown UI icon')
    if type(size) is not int or not 1 <= size <= 256:
        raise ValueError('UI icon size must be 1..256 pixels')
    directory = asset_directory()
    if name == 'logo':
        exact = directory / ('logo-%d.png' % size)
        if exact.exists():
            return exact.read_bytes()
        path, tint = directory / 'logo-128.png', None
    else:
        if (not isinstance(color, str) or len(color) != 7 or not color.startswith('#')):
            raise ValueError('UI icon color must be #rrggbb')
        try:
            tint = tuple(int(color[i:i+2], 16) for i in (1, 3, 5))
        except ValueError as error:
            raise ValueError('UI icon color must be #rrggbb') from error
        path = directory / (name + '.png')
    width, height, rows = _pixels(str(path))
    raw = bytearray((size * 4 + 1) * size)
    for y in range(size):
        sy = max(0.0, min(height - 1.0, (y + .5) * height / size - .5))
        y0, fy = int(sy), sy - int(sy)
        row0, row1 = rows[y0], rows[min(height-1, y0+1)]
        for x in range(size):
            sx = max(0.0, min(width - 1.0, (x + .5) * width / size - .5))
            x0, fx = int(sx), sx - int(sx)
            a, b = x0*4, min(width-1, x0+1)*4
            target = y * (size * 4 + 1) + 1 + x * 4
            for channel in range(4):
                if tint is not None and channel < 3:
                    raw[target+channel] = tint[channel]
                else:
                    top = row0[a+channel] * (1-fx) + row0[b+channel] * fx
                    bottom = row1[a+channel] * (1-fx) + row1[b+channel] * fx
                    raw[target+channel] = round(top * (1-fy) + bottom * fy)
    return (b'\x89PNG\r\n\x1a\n' + _chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0))
            + _chunk(b'IDAT', zlib.compress(raw, 6)) + _chunk(b'IEND', b''))


def _cache(master):
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('Tk images must stay on their interpreter owner thread')
    root = master._root()
    ident = threading.get_ident()
    owner = getattr(root, '_clawboard_icon_owner', ident)
    if owner != ident:
        raise RuntimeError('Tk images must stay on their interpreter owner thread')
    root._clawboard_icon_owner = owner
    if not hasattr(root, '_clawboard_icon_cache'):
        root._clawboard_icon_cache = OrderedDict()
    return root._clawboard_icon_cache


def get_icon(master, name, size=16, color=None):
    """Get a PhotoImage retained by this Tk interpreter; size is actual pixels."""
    import tkinter as tk
    cache = _cache(master)
    if color is None:
        color = T['fg2']
    rgb = master.winfo_rgb(color)
    color = '#%02x%02x%02x' % tuple(value // 257 for value in rgb)
    key = (name, int(size), color if name != 'logo' else None)
    image = cache.get(key)
    if image is not None:
        cache.move_to_end(key)
        return image
    image = tk.PhotoImage(master=master, data=render_icon_png(name, int(size), color), format='png')
    cache[key] = image
    while len(cache) > MAX_TK_IMAGES:
        cache.popitem(last=False)
    return image


def clear_icon_cache(master):
    """DPI/theme rebuild drops shared references; live buttons retain theirs."""
    _cache(master).clear()
