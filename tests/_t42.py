"""Windows Tk catch-up regression for the asynchronous application bridge.

Synthetic snapshots only. Temporary config and NO_SAVE precede app imports.
"""
import hashlib
import os
from pathlib import Path
import struct
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.windows_test_guard import acquire_desktop_test_lease
acquire_desktop_test_lease()
TEMP = tempfile.TemporaryDirectory(prefix='cb-catchup-')
from clawboard import config, runtime
config.BASE_DIR = TEMP.name
config.DATA_FILE = str(Path(TEMP.name) / 'ClawBoard数据.json')
config.CRASH_LOG = str(Path(TEMP.name) / 'crash.log')
runtime.NO_SAVE = True
runtime.LAST_WRITE_SEQ = -1

import tkinter as tk
import ClawBoard as C
C.NO_SAVE = True
from clawboard.services import CaptureResult, ClipboardSnapshot
from clawboard.image import dib_to_png
from clawboard.onboard import is_empty_data
from clawboard.privacy import scan_sensitive
from clawboard.tag import detect_tags


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


REAL_DATA = [ROOT / 'ClawBoard数据.json',
             Path.home() / 'Desktop' / 'cut' / 'ClawBoard数据.json',
             Path(os.environ['APPDATA']) / 'ClawBoard' / 'ClawBoard数据.json']
BEFORE = {path: digest(path) for path in REAL_DATA}


class CatchupTests(unittest.TestCase):
    def setUp(self):
        self.seq = 1000
        self.sample = CaptureResult('empty')
        self.patches = [
            patch('clawboard.tk_bridge.clip_seq', lambda: self.seq),
            patch('clawboard.tk_bridge.read_snapshot', lambda *a, **k: self.sample),
            patch.object(C.ClawBoard, 'setup_system',
                         lambda app: setattr(app, 'hw', SimpleNamespace(clipboard_listener=False))),
        ]
        for p in self.patches:
            p.start()
        self.root = tk.Tk()
        self.app = C.ClawBoard(self.root)
        self.app.st.update(listen=True, smart_private=True, skip_sensitive=False,
                           sound_copy=True, show_toast=False)
        self.played = patch('clawboard.sound.play_copy').start()
        self.addCleanup(patch.stopall)
        self.root.update()
        self.seed('existing')

    def tearDown(self):
        try:
            self.wait()
            self.app.bridge.close()
        finally:
            for timer in self.root.tk.splitlist(self.root.tk.call('after', 'info')):
                self.root.after_cancel(timer)
            self.root.destroy()
            for p in reversed(self.patches):
                p.stop()
        self.assertFalse(Path(config.DATA_FILE).exists())
        self.assertEqual({p: digest(p) for p in REAL_DATA}, BEFORE)

    def seed(self, text=None):
        self.app.data['clip'] = [] if text is None else [dict(
            id='seed', text=text, seq=1, created_at=1000, updated_at=1000,
            content_type='text', copy_count=1, fav=0)]
        self.app.data['groups'] = [{'name': '默认', 'items': []}]

    def wait(self):
        end = time.monotonic() + 3
        while self.app.application.pending and time.monotonic() < end:
            self.root.update()
            self.app.application.drain()
            time.sleep(.002)
        self.assertFalse(self.app.application.pending, 'capture did not settle')

    def sample_text(self, text):
        self.seq += 1
        self.sample = CaptureResult('captured', ClipboardSnapshot(
            self.seq, 'text', text=text, source_app='synthetic.exe'))

    def catchup(self, text):
        self.sample_text(text)
        accepted = self.app.catchup_clipboard()
        self.wait()
        return accepted

    def test_empty_library_preserves_first_run(self):
        self.seed()
        self.assertFalse(self.catchup('new copy'))
        self.assertTrue(is_empty_data(self.app.data))

    def test_new_text_once_and_quiet(self):
        self.assertTrue(self.catchup('new copy'))
        self.assertEqual(len(self.app.data['clip']), 2)
        self.assertEqual(self.app.data['clip'][0]['text'], 'new copy')
        self.assertTrue(self.app.catchup_clipboard())
        self.wait()
        self.assertEqual(len(self.app.data['clip']), 2)
        self.played.assert_not_called()

    def test_duplicate_empty_private_and_sensitive(self):
        self.catchup('existing')
        self.assertEqual(len(self.app.data['clip']), 1)
        for status in ('empty', 'private'):
            self.seq += 1
            self.sample = CaptureResult(status)
            self.app.catchup_clipboard()
            self.wait()
            self.assertEqual(len(self.app.data['clip']), 1)
        self.app.st['skip_sensitive'] = True
        self.catchup('phone 13800138000')
        self.assertEqual(len(self.app.data['clip']), 1)

    def test_disabled_and_resume(self):
        self.app.st['listen'] = False
        self.assertFalse(self.catchup('while paused'))
        self.app.toggle_listen()
        self.wait()
        self.assertTrue(self.app.st['listen'])
        self.assertEqual(self.app.data['clip'][0]['text'], 'while paused')

    def test_length_filters_and_manual_override(self):
        self.app.st['min_len'] = 5
        self.catchup('ab')
        self.assertEqual(len(self.app.data['clip']), 1)
        self.catchup('abcdef')
        self.assertEqual(len(self.app.data['clip']), 2)
        self.app.st['max_len'] = 3
        self.catchup('another long copy')
        self.assertEqual(len(self.app.data['clip']), 2)
        self.assertTrue(self.app.ingest('ab', manual=True))
        self.assertEqual(self.app.data['clip'][0]['text'], 'ab')
        self.played.assert_not_called()

    def test_image_catchup_deduplicates_and_no_save_blocks_files(self):
        dib = struct.pack('<IiiHHIIiiII', 40, 1, 1, 1, 32, 0, 4, 0, 0, 0, 0)
        dib += bytes((10, 20, 30, 255))
        png, _, _ = dib_to_png(dib)
        image_dir = Path(TEMP.name) / 'images'
        image_dir.mkdir(exist_ok=True)
        (image_dir / 'fixture.png').write_bytes(png)
        self.seed('[图片]')
        self.app.data['clip'][0].update(content_type='image', image_path='fixture.png')
        self.seq += 1
        self.sample = CaptureResult('captured', ClipboardSnapshot(
            self.seq, 'image', payload=dib, source_app='synthetic.exe'))
        self.app.catchup_clipboard()
        self.wait()
        self.assertEqual(len(self.app.data['clip']), 1)
        self.seed('text before image')
        self.app.catchup_clipboard()
        self.wait()
        self.assertEqual(len(self.app.data['clip']), 2)
        self.assertEqual(self.app.data['clip'][0]['content_type'], 'image')
        self.assertNotIn('image_path', self.app.data['clip'][0])
        self.assertEqual(sorted(p.name for p in image_dir.iterdir()), ['fixture.png'])
        self.played.assert_not_called()

    def test_manual_and_regular_sound(self):
        self.app.ingest('manual synthetic', manual=True)
        self.played.assert_not_called()
        self.app.ingest('regular synthetic')
        self.played.assert_called_once()

    def test_long_text_and_email_recognition(self):
        for size in (60000, 200000):
            start = time.perf_counter()
            scan_sensitive('a' * size)
            detect_tags('a' * size)
            self.assertLess(time.perf_counter() - start, 1)
        self.assertIn('邮箱', scan_sensitive('alice@example.com'))
        self.assertIn('email', detect_tags('alice@example.com'))

    def test_catchup_tip_autostart(self):
        with patch('clawboard.system.get_autostart', return_value=(False, '')):
            self.assertIn('开机自启', self.app._catchup_tip())
        with patch('clawboard.system.get_autostart', return_value=(True, '')):
            self.assertNotIn('开机自启', self.app._catchup_tip())


if __name__ == '__main__':
    try:
        unittest.main()
    finally:
        TEMP.cleanup()
