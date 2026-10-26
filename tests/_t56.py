"""Paper controls: real isolated widgets, no App, clipboard or real-data writes."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def run():
    from clawboard import config, runtime
    paths = [ROOT / 'ClawBoard数据.json', Path.home() / 'Desktop/cut/ClawBoard数据.json',
             Path(os.environ.get('APPDATA', '')) / 'ClawBoard/ClawBoard数据.json']
    before = {str(path): digest(path) for path in paths}
    with tempfile.TemporaryDirectory(prefix='cb-paper-controls-') as temp:
        config.BASE_DIR, config.DATA_FILE = temp, str(Path(temp) / 'ClawBoard数据.json')
        config.CRASH_LOG = str(Path(temp) / 'crash.log')
        runtime.NO_SAVE = True
        import tkinter as tk
        from clawboard.theme import T, set_theme
        from clawboard.ui_controls import UIActionButton
        from clawboard.ui_icons import get_icon, clear_icon_cache, MAX_TK_IMAGES
        root = tk.Tk()
        root.title('ClawBoard synthetic paper controls')
        root.geometry('600x220')
        calls, errors, bubbled = [], [], []
        root.report_callback_exception = lambda kind, error, trace: errors.append(str(error))
        root.bind('<Return>', lambda event: bubbled.append('return'))
        root.bind('<space>', lambda event: bubbled.append('space'))
        samples = []
        try:
            for name in ('light', 'dark'):
                set_theme(name)
                root.configure(bg=T['bg'])
                for dpi in (1.25, 1.5):
                    config.DPI_SCALE = dpi
                    for scale in config.UI_SCALE_LEVELS:
                        config.UI_SCALE = scale
                        frame = tk.Frame(root, bg=T['bg'])
                        frame.pack(fill='x')
                        button = UIActionButton(frame, text='⚙', icon='settings', command=lambda: calls.append('action'))
                        button.pack(side='left')
                        root.update()
                        geometry = button.winfo_reqwidth(), button.winfo_reqheight()
                        self_expected = config.scaled(24)
                        assert geometry == (self_expected, self_expected), (dpi, scale, geometry)
                        assert button._image.width() == config.scaled(16)
                        button.event_generate('<Enter>'); button.event_generate('<Leave>')
                        button.focus_force(); root.update()
                        assert geometry == (button.winfo_reqwidth(), button.winfo_reqheight())
                        previous = len(calls)
                        button.event_generate('<Return>')
                        button.event_generate('<KeyPress-space>')
                        button.event_generate('<KeyRelease-space>')
                        root.update()
                        assert len(calls) == previous+2, (dpi, scale, calls)
                        assert not bubbled, bubbled
                        button.configure(state='disabled')
                        button.invoke(); button.event_generate('<Return>'); root.update()
                        assert len(calls) == previous+2
                        button.configure(state='normal', fg=T['danger'])
                        assert button.cget('text') == '⚙'
                        samples.append(dict(theme=name, dpi=dpi, scale=scale, size=self_expected))
                        frame.destroy()
            first = get_icon(root, 'add', 16)
            assert first is get_icon(root, 'add', 16)
            for i in range(MAX_TK_IMAGES+20):
                get_icon(root, 'add', 16, '#%02x7060' % i)
            assert len(root._clawboard_icon_cache) == MAX_TK_IMAGES
            assert first.width() == 16
            rejected = []
            def wrong_thread():
                try:
                    get_icon(root, 'add')
                except RuntimeError:
                    rejected.append(True)
            worker = threading.Thread(target=wrong_thread)
            worker.start(); worker.join(timeout=1)
            assert rejected == [True] and not worker.is_alive()
            second = tk.Tk()
            second.withdraw()
            other = get_icon(second, 'add', 16)
            assert other is not first and other.tk is not first.tk
            second.destroy()
            clear_icon_cache(root)
            assert len(root._clawboard_icon_cache) == 0 and first.width() == 16
            assert not errors, errors
        finally:
            root.destroy()
    assert {str(path): digest(path) for path in paths} == before, 'real data changed'
    print(json.dumps(dict(passed=True, widget_samples=len(samples), root_shortcuts_not_bubbled=True,
                          bounded_interpreter_cache=True, real_data_unchanged=True)))


if __name__ == '__main__':
    run()
