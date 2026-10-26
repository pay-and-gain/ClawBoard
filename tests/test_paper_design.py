"""Pure paper-theme and original-resource contracts; no Tk or clipboard use."""
import json
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clawboard.image import png_to_dib
from clawboard.theme import DARK, LIGHT, T, apply_theme, set_theme
from clawboard.ui_icons import ICON_NAMES, asset_directory, render_icon_png


def luminance(color):
    values = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
    values = [v / 12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in values]
    return sum(v * weight for v, weight in zip(values, (.2126, .7152, .0722)))


class PaperDesignTests(unittest.TestCase):
    def setUp(self):
        self.original = dict(T)

    def tearDown(self):
        T.clear()
        T.update(self.original)

    def test_theme_updates_keep_shared_identity_and_custom_color(self):
        identity = id(T)
        for name, palette in (('light', LIGHT), ('dark', DARK)):
            set_theme(name)
            self.assertEqual(id(T), identity)
            self.assertEqual(T, palette)
        settings = {'theme': 'light', 'bg_color': '#faf3e6', 'future': 'retained'}
        apply_theme(settings)
        self.assertEqual(T['bg'], '#faf3e6')
        self.assertEqual(settings, {'theme': 'light', 'bg_color': '#faf3e6', 'future': 'retained'})

    def test_readable_body_selection_flash_and_action_labels(self):
        for palette in (DARK, LIGHT):
            for foreground, background in (('fg', 'bg'), ('fg2', 'bg'), ('fg', 'card_s'),
                                           ('fg', 'flash'), ('on_acc', 'acc'), ('on_danger', 'danger')):
                low, high = sorted((luminance(palette[foreground]), luminance(palette[background])))
                self.assertGreaterEqual((high+.05)/(low+.05), 4.5, (foreground, background))

    def test_all_action_masks_resize_and_tint_with_transparency(self):
        for name in ICON_NAMES:
            with self.subTest(name=name):
                dib, width, height = png_to_dib(render_icon_png(name, 20, '#235b50'))
                self.assertEqual((width, height), (20, 20))
                visible = [dib[offset:offset+4] for offset in range(40, len(dib), 4)
                           if dib[offset+3] > 20]
                self.assertTrue(visible)
                self.assertLess(len(visible), 20 * 20)
                self.assertTrue(all(pixel[:3] == b'\x50\x5b\x23' for pixel in visible))

    def test_ico_has_exact_multisize_png_payloads(self):
        directory = asset_directory()
        manifest = json.loads((directory / 'manifest.json').read_text())
        for name, sizes in [('app.ico', manifest['application_ico_sizes']),
                            ('tray-light.ico', [16, 20, 24, 32, 40, 48, 64]),
                            ('tray-dark-paused.ico', [16, 20, 24, 32, 40, 48, 64])]:
            data = (directory / name).read_bytes()
            self.assertEqual(struct.unpack_from('<HHH', data), (0, 1, len(sizes)))
            for index, size in enumerate(sizes):
                _, _, _, _, _, depth, length, offset = struct.unpack_from('<BBBBHHII', data, 6+16*index)
                self.assertEqual(depth, 32)
                self.assertEqual(png_to_dib(data[offset:offset+length])[1:], (size, size))
        self.assertNotEqual((directory / 'tray-light.ico').read_bytes(),
                            (directory / 'tray-light-paused.ico').read_bytes())

    def test_invalid_icon_or_size_rejected_without_arbitrary_path_reads(self):
        for name, size, color in (('../config', 16, '#235b50'), ('add', 0, '#235b50'),
                                  ('add', 257, '#235b50'), ('add', 16, 'invalid')):
            with self.assertRaises(ValueError):
                render_icon_png(name, size, color)


if __name__ == '__main__':
    unittest.main(verbosity=2)
