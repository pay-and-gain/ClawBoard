"""ThinBar follows its actual canvas width; temporary paths, no App/clipboard."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def run():
    real = [ROOT / 'ClawBoard数据.json', Path.home() / 'Desktop/cut/ClawBoard数据.json',
            Path(os.environ['APPDATA']) / 'ClawBoard/ClawBoard数据.json']
    before = {str(path): digest(path) for path in real}
    with tempfile.TemporaryDirectory(prefix='cb-scrollbar-width-') as temporary:
        from clawboard import config, runtime
        config.BASE_DIR = temporary
        config.DATA_FILE = str(Path(temporary) / 'ClawBoard数据.json')
        config.CRASH_LOG = str(Path(temporary) / 'crash.log')
        runtime.NO_SAVE = True
        import tkinter as tk
        from clawboard.widgets import ThinBar
        root = tk.Tk()
        root.title('ClawBoard synthetic scrollbar width regression')
        root.geometry('240x240')
        bar = ThinBar(root, lambda fraction: None, width=8)
        bar.pack(side='right', fill='y')
        bar.set(.2, .5)

        def pump():
            end = time.monotonic() + .04
            while time.monotonic() < end:
                root.update()
                time.sleep(.002)

        try:
            for width in (8, 16, 24, 4, 1, 8):
                bar.configure(width=width)
                pump()
                for event in ('<Leave>', '<Enter>'):
                    bar.event_generate(event)
                    pump()
                    items = bar.find_all()
                    assert len(items) == 2
                    track, thumb = (bar.coords(item) for item in items)
                    actual = bar.winfo_width()
                    assert track[0] == 0 and track[2] == actual, (
                        'track retained initial width', width, actual, track)
                    assert 0 <= thumb[0] <= thumb[2] <= actual, (
                        'thumb exceeds resized canvas', width, actual, thumb)
            bar.set(0, 1)
            pump()
            assert len(bar.find_all()) == 1, 'full-page view must not show a thumb'
        finally:
            root.destroy()
        assert not list(Path(temporary).iterdir()), 'widget test wrote files'
    assert {str(path): digest(path) for path in real} == before, 'real data changed during test'
    print('PASS: six actual widths, hover/idle, narrow bounds and full-page track; real hashes unchanged')


if __name__ == '__main__':
    run()
