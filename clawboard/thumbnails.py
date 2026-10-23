"""Bounded image previews, prepared outside the Tk thread."""
from collections import OrderedDict
import math
import struct
from threading import Lock

from clawboard.image import dib_to_png, png_to_dib


def make_thumbnail(png, max_width=440, max_height=280):
    if max_width < 1 or max_height < 1:
        raise ValueError('thumbnail dimensions must be positive')
    dib, width, height = png_to_dib(png)
    step = max(1, math.ceil(max(width / max_width, height / max_height)))
    if step == 1:
        return png
    stride = width * 4
    pixels = memoryview(dib)[40:]
    new_width, new_height = math.ceil(width / step), math.ceil(height / step)
    rows = []
    for y in range(0, height, step):
        row = bytes(pixels[y * stride:(y + 1) * stride])
        target = bytearray(new_width * 4)
        for channel in range(4):
            target[channel::4] = row[channel::4][::step]
        rows.append(target)
    raw = b''.join(rows)
    header = struct.pack('<IiiHHIIiiII', 40, new_width, new_height, 1, 32, 0,
                         len(raw), 0, 0, 0, 0)
    return dib_to_png(header + raw)[0]


class ThumbnailCache:
    def __init__(self, image_store, *, max_entries=16, max_bytes=4 * 1024 * 1024):
        self.store = image_store
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self._cache = OrderedDict()
        self._size = 0
        self._lock = Lock()

    def get(self, name, max_width=440, max_height=280):
        path = self.store.path(name)
        stat = path.stat()
        key = (name, stat.st_size, stat.st_mtime_ns, max_width, max_height)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached
        result = make_thumbnail(self.store.read(name), max_width, max_height)
        with self._lock:
            # A concurrent request may already have cached this exact preview.
            previous = self._cache.pop(key, None)
            if previous is not None:
                self._size -= len(previous)
            if len(result) <= self.max_bytes and self.max_entries > 0:
                self._cache[key] = result
                self._size += len(result)
                while self._size > self.max_bytes or len(self._cache) > self.max_entries:
                    _, old = self._cache.popitem(last=False)
                    self._size -= len(old)
        return result

    def clear(self):
        with self._lock:
            self._cache.clear()
            self._size = 0
