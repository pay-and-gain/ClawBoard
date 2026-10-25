"""Real Tk display-switch regression; synthetic widgets, no App or clipboard."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def run():
    import tkinter as tk
    from clawboard import config, runtime
    paths = [ROOT / 'ClawBoard数据.json', Path.home() / 'Desktop/cut/ClawBoard数据.json',
             Path(os.environ['APPDATA']) / 'ClawBoard/ClawBoard数据.json']
    before = {str(p): digest(p) for p in paths}
    with tempfile.TemporaryDirectory(prefix='cb-display-switches-') as temp:
        config.BASE_DIR = temp
        config.DATA_FILE = str(Path(temp) / 'ClawBoard数据.json')
        config.CRASH_LOG = str(Path(temp) / 'crash.log')
        runtime.NO_SAVE = True
        from clawboard.settings_dialog import SettingsWindow
        from clawboard.viewmodels import ViewProjection
        from clawboard.vlist import VirtualList
        from clawboard.win32 import init_dpi_awareness
        init_dpi_awareness()
        root = tk.Tk()
        root.title('ClawBoard synthetic display switches')
        root.geometry('480x300')
        errors, saves = [], []
        root.report_callback_exception = lambda kind, error, trace: errors.append(str(error))
        st = dict(config.DEFAULT_SETTINGS)
        records = [dict(id=str(i), text='Synthetic body %d' % i, source_app='SyntheticApp',
                        content_size=93, created_at=1700000000000) for i in range(100)]
        projection = ViewProjection()
        vlist = VirtualList(root, lambda *a: None, lambda *a: None, lambda *a: None)
        vlist.pack(fill='both', expand=True)

        def render():
            vlist.set_data(projection.project(records, 'clip', st), None, '')

        app = SimpleNamespace(root=root, st=st, render=render,
                              save=lambda *a: saves.append(dict(st)),
                              apply_effects=lambda: None, apply_trigger_setting=lambda: None,
                              application=SimpleNamespace(tasks=SimpleNamespace(invalidate=lambda *a: None)))
        switches = {}

        class HarnessSettings(SettingsWindow):
            def row_switch(self, master, text, key, after=None):
                super().row_switch(master, text, key, after)
                switches[key] = master.winfo_children()[-1].winfo_children()[-1]

        # Keep the real settings constructor and requested switches; skip
        # unrelated controls so this regression never reads system settings.
        methods = ('row_autostart_switch', 'row_close_action', 'row_theme', 'row_bgcolor',
                   'row_ui_scale', 'row_hotkey', 'row_int', 'row_text', 'row_update')
        from contextlib import ExitStack
        try:
            render()
            root.update()
            with ExitStack() as stack:
                for name in methods:
                    stack.enter_context(patch.object(HarnessSettings, name, lambda *a, **k: None))
                settings = HarnessSettings(app)
            root.update()
            for key in ('show_source', 'show_size'):
                assert switches[key].cget('text') == '关'

            def click(key):
                settings.sc.canvas.yview_moveto(0)
                root.update()
                switches[key].event_generate('<Button-1>', x=3, y=3)
                root.update()
                assert switches[key].cget('text') == ('开' if st[key] else '关')

            def first():
                return vlist.pool[min(vlist.pool)]

            hidden_width = first()._row.winfo_width()
            assert not first()._badge.winfo_ismapped()
            assert first()._l2.cget('text') == ''
            click('show_source')
            assert first()._l2.cget('text') == 'SyntheticApp'
            assert not first()._badge.winfo_ismapped()
            click('show_size')
            assert first()._badge.winfo_ismapped()
            assert '93 B' in first()._badge.cget('text')
            assert first()._row.winfo_width() < hidden_width
            click('show_source')
            assert first()._l2.cget('text') == ''
            assert first()._badge.winfo_ismapped()
            click('show_size')
            assert not first()._badge.winfo_ismapped()
            assert first()._row.winfo_width() == hidden_width
            # Row recycling at an unchanged viewport must not retain an old badge.
            for visible in (True, False, True, False):
                click('show_size')
                vlist.canvas.yview_moveto(.75 if visible else 0)
                vlist.update_view()
                root.update()
                for frame in vlist.pool.values():
                    assert (frame._badge.winfo_manager() == 'place') == visible
                    if frame.winfo_ismapped():
                        assert bool(frame._badge.winfo_ismapped()) == visible
            assert len(saves) == 8
            assert not st['show_source'] and not st['show_size']
            assert all(r['source_app'] == 'SyntheticApp' and r['content_size'] == 93 for r in records)
            assert not errors, errors
        finally:
            root.destroy()
    assert {str(p): digest(p) for p in paths} == before, 'real data changed during regression'
    print('PASS: independent settings bindings, immediate source/size refresh, reclaimed width, recycling; real data unchanged')


if __name__ == '__main__':
    run()
