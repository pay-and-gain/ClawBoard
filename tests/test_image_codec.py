"""Pure codec and injected Win32 ownership tests; no App or real clipboard."""
import ctypes
import importlib.util
import pathlib
import struct
import sys
import unittest
import zlib
from unittest.mock import MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clawboard import image, runtime


def chunk(kind, data):
    return (struct.pack('>I', len(data)) + kind + data
            + struct.pack('>I', zlib.crc32(kind + data) & 0xFFFFFFFF))


def make_png(width, height, raw, color=6, interlace=0):
    header = struct.pack('>IIBBBBB', width, height, 8, color, 0, 0, interlace)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header)
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def make_dib(rows, width, depth=32, top_down=False):
    bpp = depth // 8
    pad = bytes((-width * bpp) % 4)
    stored = rows if top_down else rows[::-1]
    pixels = b''.join(row + pad for row in stored)
    header = struct.pack('<IiiHHIIiiII', 40, width,
                         -len(rows) if top_down else len(rows), 1, depth,
                         0, len(pixels), 0, 0, 0, 0)
    return header + pixels


class CodecTests(unittest.TestCase):
    def test_import_is_platform_independent(self):
        self.assertNotIn('clawboard.image_win32', sys.modules)

    def test_rgba_roundtrip_preserves_pixels_and_alpha(self):
        rows = [bytes((9, 37, 201, 89, 213, 8, 71, 255)),
                bytes((44, 99, 3, 0, 18, 175, 240, 135))]
        for top_down in (False, True):
            with self.subTest(top_down=top_down):
                png, w, h = image.dib_to_png(make_dib(rows, 2, top_down=top_down))
                dib, w2, h2 = image.png_to_dib(png)
                self.assertEqual((w, h, w2, h2), (2, 2, 2, 2))
                self.assertEqual(dib[40:], b''.join(rows[::-1]))

    def test_24bit_padding_and_top_down(self):
        rows = [bytes((3, 8, 217, 111, 61, 4, 251, 2, 56)),
                bytes((79, 143, 9, 17, 234, 34, 107, 52, 199))]
        for top_down in (False, True):
            png, _, _ = image.dib_to_png(make_dib(rows, 3, 24, top_down))
            decoded, _, _ = image.png_to_dib(png)
            expected = b''.join(row[i:i + 3] + b'\xff'
                                for row in rows[::-1] for i in range(0, len(row), 3))
            self.assertEqual(decoded[40:], expected)

    def test_standard_bitfield_header(self):
        row = bytes((3, 90, 231, 177))
        dib = bytearray(make_dib([row], 1))
        struct.pack_into('<I', dib, 16, 3)
        dib[40:40] = struct.pack('<III', 0x00FF0000, 0x0000FF00, 0x000000FF)
        decoded, _, _ = image.png_to_dib(image.dib_to_png(dib)[0])
        self.assertEqual(decoded[40:], row)

    def test_png_filters_rgb_and_rgba(self):
        for bpp, color in ((3, 2), (4, 6)):
            rows = [bytes((i * 37 + y * 29) % 256 for i in range(3 * bpp))
                    for y in range(3)]
            expected = b''.join(bytes((row[i + 2], row[i + 1], row[i],
                                       row[i + 3] if bpp == 4 else 255))
                                for row in rows[::-1] for i in range(0, len(row), bpp))
            for kind in range(5):
                with self.subTest(bpp=bpp, filter=kind):
                    encoded = bytearray()
                    previous = bytes(len(rows[0]))
                    for row in rows:
                        encoded.append(kind)
                        for i, value in enumerate(row):
                            a = row[i - bpp] if i >= bpp else 0
                            b = previous[i]
                            c = previous[i - bpp] if i >= bpp else 0
                            estimate = a + b - c
                            distances = (abs(estimate - a), abs(estimate - b), abs(estimate - c))
                            paeth = (a, b, c)[distances.index(min(distances))]
                            predictor = (0, a, b, (a + b) // 2, paeth)[kind]
                            encoded.append((value - predictor) & 255)
                        previous = row
                    dib, w, h = image.png_to_dib(make_png(3, 3, encoded, color))
                    self.assertEqual((w, h), (3, 3))
                    self.assertEqual(dib[40:], expected)

    def test_multiple_idat_chunks(self):
        raw = b'\x00\x01\x02\x03\x04'
        compressed = zlib.compress(raw)
        png = (b'\x89PNG\r\n\x1a\n'
               + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0))
               + chunk(b'IDAT', compressed[:4]) + chunk(b'IDAT', compressed[4:])
               + chunk(b'IEND', b''))
        self.assertEqual(image.png_to_dib(png)[0][40:], b'\x03\x02\x01\x04')

    def test_bad_dib_lengths_and_dimensions(self):
        good = make_dib([b'\x01\x02\x03\xff'], 1)
        bad = [b'', good[:39], good[:-1]]
        for offset, format_, value in ((0, '<I', 400), (4, '<i', 0),
                                       (8, '<i', 0), (12, '<H', 2),
                                       (14, '<H', 16), (16, '<I', 1),
                                       (4, '<i', image.MAX_IMAGE_DIMENSION + 1)):
            altered = bytearray(good)
            struct.pack_into(format_, altered, offset, value)
            bad.append(altered)
        for data in bad:
            with self.subTest(data=bytes(data[:20])):
                with self.assertRaises(ValueError):
                    image.dib_to_png(data)

    def test_bad_png_checksums_and_truncation(self):
        good = make_png(1, 1, b'\x00\x01\x02\x03\xff')
        corrupt = bytearray(good)
        corrupt[30] ^= 1
        for data in (b'', good[:20], good[:-5], corrupt):
            with self.assertRaises(ValueError):
                image.png_to_dib(data)

    def test_invalid_row_filter_and_unbounded_inflate(self):
        for raw in (b'\x05\x01\x02\x03\xff', b'\x00', b'\x00' * 100000):
            with self.assertRaises(ValueError):
                image.png_to_dib(make_png(1, 1, raw))

    def test_oversized_or_interlaced_png_rejected_before_allocation(self):
        for width, height, interlace in ((0, 1, 0), (10000, 10000, 0), (1, 1, 1)):
            with self.assertRaises(ValueError):
                image.png_to_dib(make_png(width, height, b'\x00', interlace=interlace))


class Win32OwnershipTests(unittest.TestCase):
    def adapter(self):
        user = MagicMock()
        kernel = MagicMock()
        buffer = ctypes.create_string_buffer(128)
        user.OpenClipboard.return_value = True
        user.EmptyClipboard.return_value = True
        user.SetClipboardData.return_value = 77
        user.GetClipboardSequenceNumber.return_value = 123
        kernel.GlobalAlloc.return_value = 77
        kernel.GlobalLock.return_value = ctypes.addressof(buffer)
        spec = importlib.util.spec_from_file_location('image_adapter_test',
                    ROOT / 'clawboard/image_win32.py')
        module = importlib.util.module_from_spec(spec)
        with patch.object(ctypes, 'WinDLL',
                          lambda name, **kw: user if name == 'user32' else kernel,
                          create=True):
            spec.loader.exec_module(module)
        return module, user, kernel, buffer

    def test_success_transfers_memory_and_marks_own_sequence(self):
        module, user, kernel, buffer = self.adapter()
        old = runtime.LAST_SEQ
        old_write = runtime.LAST_WRITE_SEQ
        try:
            self.assertTrue(module.write_clipboard_dib(bytes(40)))
            self.assertEqual(runtime.LAST_SEQ, 123)
            self.assertEqual(runtime.LAST_WRITE_SEQ, 123)
            kernel.GlobalFree.assert_not_called()
            kernel.GlobalUnlock.assert_called_once_with(77)
            user.CloseClipboard.assert_called_once()
        finally:
            runtime.LAST_SEQ = old
            runtime.LAST_WRITE_SEQ = old_write

    def test_failed_transfer_frees_allocated_memory(self):
        module, user, kernel, buffer = self.adapter()
        user.SetClipboardData.return_value = 0
        old = runtime.LAST_SEQ
        self.assertFalse(module.write_clipboard_dib(bytes(40)))
        self.assertEqual(runtime.LAST_SEQ, old)
        kernel.GlobalFree.assert_called_once_with(77)
        user.CloseClipboard.assert_called_once()

    def test_failed_lock_frees_handle_without_unlocking(self):
        module, user, kernel, buffer = self.adapter()
        kernel.GlobalLock.return_value = None
        self.assertFalse(module.write_clipboard_dib(bytes(40)))
        kernel.GlobalFree.assert_called_once_with(77)
        kernel.GlobalUnlock.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
