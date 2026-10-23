"""Preview decoding stays bounded while complete image bytes remain untouched."""
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clawboard.image import dib_to_png, png_to_dib
from clawboard.media import ImageStore
from clawboard.thumbnails import ThumbnailCache, make_thumbnail


def png(width=64, height=32):
    data = bytes((2, 70, 180, 255)) * width * height
    header = struct.pack('<IiiHHIIiiII', 40, width, height, 1, 32, 0, len(data), 0, 0, 0, 0)
    return dib_to_png(header + data)[0]


class ThumbnailTests(unittest.TestCase):
    def test_large_image_fits_box_and_preserves_original(self):
        original = png(640, 360)
        before = bytes(original)
        result = make_thumbnail(original, 100, 80)
        _, width, height = png_to_dib(result)
        self.assertLessEqual(width, 100)
        self.assertLessEqual(height, 80)
        self.assertEqual(original, before)
        self.assertAlmostEqual(width / height, 640 / 360, delta=0.05)

    def test_small_image_returns_original_without_reencoding(self):
        original = png()
        self.assertIs(make_thumbnail(original, 100, 100), original)

    def test_preview_cache_is_bounded_and_refreshes_replaced_file(self):
        with tempfile.TemporaryDirectory(prefix='clawboard-thumbnail-') as temp:
            store = ImageStore(Path(temp) / 'images')
            cache = ThumbnailCache(store, max_entries=1)
            a, b = store.write(png()), store.write(png(32, 64))
            import clawboard.thumbnails as module
            with patch.object(module, 'make_thumbnail', wraps=make_thumbnail) as render:
                first = cache.get(a)
                self.assertIs(cache.get(a), first)
                self.assertEqual(render.call_count, 1)
                cache.get(b)
                cache.get(a)
                self.assertEqual(render.call_count, 3)
                store.path(a).write_bytes(png(31, 17))
                self.assertEqual(png_to_dib(cache.get(a))[1:], (31, 17))
                self.assertEqual(render.call_count, 4)
            self.assertEqual(len(cache._cache), 1)

    def test_image_path_escape_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix='clawboard-image-path-') as temp:
            store = ImageStore(temp)
            for name in ('../private.png', '/outside.png', '..\\outside.png', ''):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    store.read(name)

    def test_invalid_preview_size_is_explicit(self):
        with self.assertRaises(ValueError):
            make_thumbnail(png(), 0, 10)


if __name__ == '__main__':
    unittest.main()
