"""Opt-in real Windows/Tk mixed-DPI regression; temporary synthetic data only.

Run separately from _t44 and other desktop tests. Does not write the clipboard,
register triggers or start another product instance; the real App owns its usual
message window/tray/hotkey until the test closes it.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.windows_test_guard import acquire_desktop_test_lease
acquire_desktop_test_lease()
TEMP = tempfile.TemporaryDirectory(prefix='cb-dpi-')

from clawboard import config, runtime
config.BASE_DIR = TEMP.name
config.DATA_FILE = str(Path(TEMP.name) / 'ClawBoard数据.json')
config.CRASH_LOG = str(Path(TEMP.name) / 'crash.log')
runtime.NO_SAVE = True

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None

DATA_PATHS = [ROOT / 'ClawBoard数据.json',
              Path.home() / 'Desktop' / 'cut' / 'ClawBoard数据.json',
              Path(os.environ.get('APPDATA', TEMP.name)) / 'ClawBoard' / 'ClawBoard数据.json']
BEFORE = {path: digest(path) for path in DATA_PATHS}

import ClawBoard as C
C.NO_SAVE = True
import tkinter as tk
import tkinter.font as tkfont
from unittest.mock import patch
from clawboard.win32 import monitors, u32, top_hwnd, init_dpi_awareness


class MixedDpi(unittest.TestCase):
    def pump(self, duration=.65):
        end = time.monotonic() + duration
        while time.monotonic() < end:
            self.root.update()
            time.sleep(.01)

    def snapshot(self):
        return dict(dpi=int(u32.GetDpiForWindow(top_hwnd(self.root))),
                    scaling=float(self.root.tk.call('tk', 'scaling')),
                    minimum=self.root.minsize(),
                    size=(self.root.winfo_width(), self.root.winfo_height()),
                    bar=self.app.bar.winfo_height(),
                    row=config.scaled(config.ITEM_H),
                    font=tkfont.Font(root=self.root, font=self.app.title_lb.cget('font')).metrics('linespace'))

    def move(self, monitor, visible=True):
        l, t, r, b = monitor
        w, h = self.root.winfo_width(), self.root.winfo_height()
        self.root.geometry('%dx%d+%d+%d' % (w, h, (l + r - w) // 2, (t + b - h) // 2))
        self.pump()
        record = self.snapshot()
        print('DPI sample:', record, flush=True)
        if visible:
            self.assertAlmostEqual(self.app._dpi_scale, record['dpi'] / 96, places=3)
            self.assertAlmostEqual(record['scaling'], record['dpi'] / 72 * 1.25, delta=.02)
        self.assertEqual(config.UI_SCALE, 1.25)
        self.assertEqual(self.app.st['ui_scale'], 1.25)
        self.assertEqual(self.app.search.get(), 'sample')
        self.assertEqual(self.app.sel_clip, 'item-20')
        self.assertEqual(self.app.vlist.multi, {'item-20', 'item-22'})
        self.assertEqual((self.app.search_entry.index('sel.first'),
                          self.app.search_entry.index('sel.last')), (1, 4))
        self.assertTrue(self.dialog.winfo_exists(), 'DPI refresh destroyed another editor')
        bar = self.app.bar
        self.pump(.3)
        self.assertIs(self.app.bar, bar, 'stable DPI kept rebuilding the panel')
        return record

    def test_actual_monitors_roundtrip_preserves_view_collapsed_and_hidden(self):
        if sys.platform != 'win32':
            self.skipTest('Windows desktop required')
        actual = monitors()
        if len(actual) < 2:
            self.skipTest('two monitors required')
        init_dpi_awareness()
        settings = dict(config.DEFAULT_SETTINGS, listen=False, update_check=False,
                        ui_scale=1.25, collapsed=False, show_toast=False, show_preview=False)
        fixture = dict(schema_version=3, settings=settings, groups=[], gi=0,
                       geom='520x640+100+100', clip=[
                           dict(id='item-%d' % i, text='sample synthetic %d' % i,
                                seq=80 - i, content_type='text') for i in range(80)])
        Path(config.DATA_FILE).write_text(json.dumps(fixture), encoding='utf-8')
        fixture_hash = digest(Path(config.DATA_FILE))
        self.root = tk.Tk()
        self.addCleanup(self.close)
        # Capture is independent of DPI; do not consume a user's existing clipboard.
        with patch.object(C.ClawBoard, 'catchup_clipboard', lambda app: None):
            self.app = C.ClawBoard(self.root)
        self.pump()
        self.app.search.set('sample')
        self.pump()
        self.app.sel_clip = 'item-20'
        self.app.render()
        self.app.vlist.multi = {'item-20', 'item-22'}
        self.app.vlist.scroll_to_index(20)
        self.app.search_entry.icursor(4)
        self.app.search_entry.selection_range(1, 4)
        self.dialog = tk.Toplevel(self.root)
        tk.Entry(self.dialog).insert(0, 'independent editor')
        base = self.move(actual[0])
        top = self.app.vlist.canvas.canvasy(0) / config.scaled(config.ITEM_H)
        samples = [base]
        for monitor in actual[1:] + actual[:1]:
            record = self.move(monitor)
            samples.append(record)
            scale = record['dpi'] / base['dpi']
            self.assertAlmostEqual(record['size'][0], base['size'][0] * scale, delta=2)
            self.assertAlmostEqual(record['size'][1], base['size'][1] * scale, delta=2)
            self.assertAlmostEqual(record['font'], base['font'] * scale, delta=3)
            self.assertAlmostEqual(record['bar'], base['bar'] * scale, delta=2)
            self.assertAlmostEqual(record['row'], base['row'] * scale, delta=2)
            self.assertAlmostEqual(self.app.vlist.canvas.canvasy(0) / config.scaled(config.ITEM_H), top, delta=.1)
            expected = (int(config.MIN_W * record['dpi'] / 96 * 1.25),
                        int(config.MIN_H * record['dpi'] / 96 * 1.25))
            self.assertEqual(record['minimum'], expected)
        self.app.toggle_collapse()
        self.pump(.2)
        for monitor in actual[1:] + actual[:1]:
            self.move(monitor)
            self.assertTrue(self.app.collapsed)
            self.assertEqual(self.root.winfo_height(), config.scaled(config.BAR_H))
            self.assertFalse(self.app.body.winfo_ismapped())
        self.app._told_tray = True
        self.app.hide()
        for monitor in actual[1:] + actual[:1]:
            self.move(monitor, visible=False)
            self.assertTrue(self.app.hidden)
            self.assertEqual(self.root.state(), 'withdrawn')
        self.move(actual[1], visible=False)
        self.app.toggle_show()
        self.pump()
        record = self.snapshot()
        self.assertAlmostEqual(self.app._dpi_scale, record['dpi'] / 96, places=3)
        self.assertAlmostEqual(record['scaling'], record['dpi'] / 72 * 1.25, delta=.02)
        self.assertTrue(self.app.collapsed)
        self.assertEqual(digest(Path(config.DATA_FILE)), fixture_hash, 'NO_SAVE fixture changed')
        if len({record['dpi'] for record in samples}) < 2:
            print('SKIP mixed-density evidence: monitor DPIs are equal; moves still checked', flush=True)

    def close(self):
        if hasattr(self, 'app'):
            self.app.bridge.close()
            self.app.hw.stop()
            self.app.hw.join(3)
        self.root.destroy()


if __name__ == '__main__':
    try:
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    finally:
        unchanged = all(digest(path) == value for path, value in BEFORE.items())
        print('Real data hashes unchanged:', unchanged)
        TEMP.cleanup()
    sys.exit(0 if result.wasSuccessful() and unchanged else 1)
