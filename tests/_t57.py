"""Real Tk grouped-settings regression; synthetic stub, no App/system writes."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
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
    before = {str(path): digest(path) for path in paths}
    with tempfile.TemporaryDirectory(prefix='cb-settings-sections-') as temp:
        config.BASE_DIR = temp
        config.DATA_FILE = str(Path(temp) / 'ClawBoard数据.json')
        config.CRASH_LOG = str(Path(temp) / 'crash.log')
        runtime.NO_SAVE = True
        from clawboard.settings_dialog import SettingsWindow
        from clawboard.settings_layout import SECTION_SETTINGS, SECTIONS
        from clawboard.windows_geometry import monitors, top_hwnd
        from clawboard.windows_api import u32
        from clawboard.win32 import init_dpi_awareness
        init_dpi_awareness()
        root = tk.Tk()
        root.title('ClawBoard synthetic grouped settings')
        errors, samples = [], []
        root.report_callback_exception = lambda kind, error, trace: errors.append(repr(error))

        def pump(seconds=.08):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                root.update()
                time.sleep(.004)

        expected = set().union(*map(set, SECTION_SETTINGS.values()))
        assert len(expected) == sum(len(keys) for keys in SECTION_SETTINGS.values())
        app = SimpleNamespace(root=root, data={'clip': [], 'groups': []},
                              application=SimpleNamespace(tasks=SimpleNamespace(invalidate=lambda *a: None)))

        def check_footer(dialog):
            left, top = dialog.win.winfo_rootx(), dialog.win.winfo_rooty()
            right, bottom = left + dialog.win.winfo_width(), top + dialog.win.winfo_height()
            for widget in (dialog.layout.close_button, dialog.layout.quit_button,
                           *dialog.layout.navigation.values()):
                assert widget.winfo_ismapped(), widget.cget('text')
                x, y = widget.winfo_rootx(), widget.winfo_rooty()
                assert left <= x < right and top <= y < bottom, widget.cget('text')
                assert x + widget.winfo_width() <= right, widget.cget('text')
                assert y + widget.winfo_height() <= bottom, widget.cget('text')

        def children(widget):
            for child in widget.winfo_children():
                yield child
                yield from children(child)

        try:
            with patch('clawboard.settings_dialog.get_autostart', return_value=(False, '')), \
                    patch('clawboard.settings_dialog.set_autostart', side_effect=AssertionError('registry write')):
                for area in monitors():
                    left, top, _, _ = area
                    root.geometry('500x500%+d%+d' % (left + 60, top + 60))
                    pump()
                    dpi = int(u32.GetDpiForWindow(top_hwnd(root)))
                    for level in (.5, .75, 1.0, 1.25, 1.5):
                        config.DPI_SCALE, config.UI_SCALE = dpi / 96, level
                        root.tk.call('tk', 'scaling', dpi / 72 * level)
                        calls, invalidated = [], []
                        app.st = dict(config.DEFAULT_SETTINGS, future_setting='keep')
                        initial = deepcopy(app.st)
                        app.save = lambda *a: calls.append(('save', deepcopy(app.st)))
                        app.render = lambda: calls.append(('render',))
                        app.tip = lambda text: calls.append(('tip', text))
                        app.apply_effects = lambda: calls.append(('effects',))
                        app.apply_trigger_setting = lambda: calls.append(('trigger',))
                        app.open_releases = lambda: calls.append(('releases',))
                        app.apply_hotkey = lambda: calls.append(('hotkey',))
                        app.rebuild = lambda: calls.append(('rebuild',))
                        app.set_ui_scale = lambda value: app.st.update(ui_scale=value)
                        app.quit_app = lambda: calls.append(('quit',))
                        app.confirm = lambda *a: (_ for _ in ()).throw(AssertionError('NO_SAVE confirmation'))
                        app.application.tasks.invalidate = invalidated.append
                        app.toggle_listen = lambda: app.st.update(listen=not app.st['listen'])
                        dialog = SettingsWindow(app)
                        pump()
                        assert app.st == initial, 'construction changed settings'
                        assert set(dialog.layout.pages) == {key for key, _, _ in SECTIONS}
                        for section, _, _ in SECTIONS:
                            dialog.layout.navigation[section].invoke()
                            pump()
                            assert dialog.section == section
                            assert dialog.sc is dialog.layout.pages[section]
                            assert all(bool(page.winfo_ismapped()) == (key == section)
                                       for key, page in dialog.layout.pages.items())
                            minimum = dialog.win.minsize()
                            dialog.win.geometry('%dx%d' % minimum)
                            pump()
                            check_footer(dialog)
                        dialog.select_section('appearance')
                        source = dialog._switches['show_source']
                        dialog.win.focus_force()
                        source.focus_set()
                        pump()
                        assert source.winfo_class() == 'Button'
                        source.event_generate('<KeyPress-space>')
                        source.event_generate('<KeyRelease-space>')
                        pump(.15)  # Tk's native ButtonInvoke completes after 100 ms.
                        assert app.st['show_source'] is True, (str(dialog.win.focus_get()),
                            str(source), source.bindtags(), calls)
                        source.event_generate('<Return>')
                        pump()
                        assert app.st['show_source'] is False
                        assert sum(call[0] == 'render' for call in calls) == 2
                        canvas = dialog.sc.canvas
                        assert canvas.winfo_rooty() <= source.winfo_rooty()
                        assert source.winfo_rooty() + source.winfo_height() <= (
                            canvas.winfo_rooty() + canvas.winfo_height()), (
                                'focused switch not revealed', dpi, level, source.winfo_rooty(),
                                source.winfo_height(), canvas.winfo_rooty(), canvas.winfo_height(),
                                canvas.yview(), canvas.bbox('all'))

                        dialog.select_section('general')
                        pump()
                        autostart = next(widget for widget in children(dialog.sc.inner)
                                         if isinstance(widget, tk.Button) and any(
                                             isinstance(peer, tk.Label) and '开机自启' in peer.cget('text')
                                             for peer in widget.master.winfo_children()))
                        autostart.invoke()  # NO_SAVE must block even explicit activation.
                        dialog.select_section('data')
                        pump()
                        dialog.layout.export_button.invoke()
                        dialog.layout.wipe_button.invoke()
                        assert not any(call[0] == 'quit' for call in calls)
                        dialog._inputs['max_items'].delete(0, 'end')
                        dialog._inputs['max_items'].insert(0, '632')
                        dialog.save_and_close()
                        pump()
                        assert app.st['max_items'] == 632
                        assert app.st['future_setting'] == 'keep'
                        assert dialog._export_cancel.is_set() and invalidated
                        assert not dialog.win.winfo_exists()
                        samples.append(dict(dpi=dpi, ui_scale=level, sections=5))
                assert not errors, errors
                assert not Path(config.DATA_FILE).exists()
        finally:
            root.destroy()
    assert {str(path): digest(path) for path in paths} == before, 'real data changed'
    print(json.dumps(dict(passed=True, samples=samples, keyboard=True,
                          fixed_footer=True, no_save_guards=True, real_hashes_unchanged=True)))


if __name__ == '__main__':
    run()
