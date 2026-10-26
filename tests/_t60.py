"""Native two-monitor dialog regression; temporary data, no App or clipboard."""
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
    real = [ROOT / 'ClawBoard数据.json', Path.home() / 'Desktop/cut/ClawBoard数据.json',
            Path(os.environ['APPDATA']) / 'ClawBoard/ClawBoard数据.json']
    before = {str(path): digest(path) for path in real}
    with tempfile.TemporaryDirectory(prefix='cb-dialog-native-dpi-') as temporary:
        config.BASE_DIR = temporary
        config.DATA_FILE = str(Path(temporary) / 'ClawBoard数据.json')
        config.CRASH_LOG = str(Path(temporary) / 'crash.log')
        runtime.NO_SAVE = True
        from clawboard.settings_dialog import SettingsWindow
        from clawboard.workbench import WorkbenchWindow
        from clawboard.windows_geometry import monitors, top_hwnd
        from clawboard.windows_api import u32
        from clawboard.win32 import init_dpi_awareness
        init_dpi_awareness()
        root = tk.Tk()
        root.title('ClawBoard synthetic independent-screen regression')
        errors, samples, live_samples = [], [], []
        root.report_callback_exception = lambda kind, error, trace: errors.append(repr(error))

        def pump(seconds=.45):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                root.update()
                time.sleep(.004)

        def move(window, area):
            left, top, right, bottom = area
            width = min(window.winfo_width(), (right - left) // 2)
            height = min(window.winfo_height(), bottom - top - 120)
            window.geometry('%dx%d%+d%+d' % (width, height, left + 50, top + 50))
            pump(.8)
            return int(u32.GetDpiForWindow(top_hwnd(window)))

        def footer_inside(dialog):
            win = dialog.win
            x, y = win.winfo_rootx(), win.winfo_rooty()
            right, bottom = x + win.winfo_width(), y + win.winfo_height()
            for button in (dialog.layout.close_button, dialog.layout.quit_button,
                           *dialog.layout.navigation.values()):
                assert button.winfo_ismapped()
                assert x <= button.winfo_rootx() < right
                assert y <= button.winfo_rooty() < bottom
                assert button.winfo_rootx() + button.winfo_width() <= right
                assert button.winfo_rooty() + button.winfo_height() <= bottom

        try:
            areas = monitors()
            root.geometry('300x300%+d%+d' % (areas[0][0] + 30, areas[0][1] + 30))
            pump()
            base_dpi = int(u32.GetDpiForWindow(top_hwnd(root)))
            for level in (.75, 1.0, 1.5):
                config.DPI_SCALE, config.UI_SCALE = base_dpi / 96, level
                root.tk.call('tk', 'scaling', base_dpi / 72 * level)
                original_scaling = float(root.tk.call('tk', 'scaling'))
                saved = []
                settings = dict(config.DEFAULT_SETTINGS, ui_scale=level,
                                future_key={'keep': True})
                app = SimpleNamespace(root=root, st=settings,
                                      data={'clip': [dict(id='synthetic-1', text='Synthetic complete text',
                                                        content_type='text')], 'groups': []},
                                      application=SimpleNamespace(tasks=None, data_revision=0))
                for name in ('save', 'render', 'tip', 'apply_effects', 'apply_trigger_setting',
                             'open_releases', 'apply_hotkey', 'rebuild', 'quit_app', 'toggle_listen'):
                    setattr(app, name, lambda *args, n=name: saved.append(n))
                def set_ui_scale(value):
                    config.UI_SCALE = value
                    settings['ui_scale'] = value
                app.set_ui_scale = set_ui_scale
                workbench = WorkbenchWindow(app)
                app.application.tasks = SimpleNamespace(invalidate=lambda *args: None)
                with patch('clawboard.settings_dialog.get_autostart', return_value=(False, '')):
                    dialog = SettingsWindow(app)
                pump()
                dialog.select_section('data')
                draft = dialog._inputs['max_items']
                draft.delete(0, 'end')
                draft.insert(0, '632')
                draft.icursor(2)
                draft.focus_force()
                original_settings = deepcopy(settings)
                workbench.query.set('Synthetic')
                pump()
                selected = workbench._selected
                for area in [*areas, areas[0]]:
                    dpi = move(dialog.win, area)
                    # Copying Font(font=...) converts pixel fonts back to points.
                    # Inspect the existing named font to verify its pixel size.
                    heading_size = int(root.tk.call('font', 'configure',
                                       dialog.layout.heading.cget('font'), '-size'))
                    expected_font = round(abs(config.FONT_B[1]) * 96 / 72 * dpi / 96 * level)
                    assert abs(heading_size) == expected_font, (
                        'settings font did not follow its own monitor', dpi, level,
                        heading_size, expected_font)
                    assert heading_size < 0, 'settings must use per-window pixel fonts'
                    assert dialog.section == 'data'
                    assert dialog._inputs['max_items'].get() == '632', 'cross-screen lost draft'
                    assert dialog._inputs['max_items'].index('insert') == 2
                    assert settings == original_settings and not saved, 'cross-screen saved draft'
                    footer_inside(dialog)
                    wb_dpi = move(workbench.win, area)
                    assert abs(workbench._scale - wb_dpi / 96 * level) < .001
                    assert workbench.query.get() == 'Synthetic' and workbench._selected == selected
                    assert config.DPI_SCALE == base_dpi / 96
                    assert abs(float(root.tk.call('tk', 'scaling')) - original_scaling) < .001
                    assert int(u32.GetDpiForWindow(top_hwnd(root))) == base_dpi
                    samples.append(dict(ui_scale=level, settings_dpi=dpi, workbench_dpi=wb_dpi))
                workbench.close()
                # Keep the same controls and a draft alive while the panel's
                # shortcut notification changes the user's scale preference.
                original_binding = dialog._scale_binding
                for changed_level in (1.25, .75, level):
                    set_ui_scale(changed_level)
                    root.event_generate('<<ClawBoardUIScaleChanged>>', when='tail')
                    pump()
                    assert abs(dialog._scale - dpi / 96 * changed_level) < .001
                    assert dialog._inputs['max_items'] is draft
                    assert draft.get() == '632' and draft.index('insert') == 2
                    assert dialog.win.focus_get() is draft, 'scale notification lost input focus'
                    assert dialog.section == 'data' and not saved
                    assert settings == dict(original_settings, ui_scale=changed_level)
                    footer_inside(dialog)
                    live_samples.append(dict(source='panel-event', ui_scale=changed_level))
                # Invoking the existing settings control must also work when
                # its parent adapter does not emit the panel notification.
                for row in dialog.layout.pages['appearance'].inner.winfo_children():
                    children = row.winfo_children()
                    if any(isinstance(child, tk.Label) and child.cget('text').startswith('界面缩放')
                           for child in children):
                        scale_button = next(child for child in children if isinstance(child, tk.Button))
                        break
                else:
                    raise AssertionError('settings scale control missing')
                scale_button.invoke()
                pump()
                assert abs(dialog._scale - dpi / 96 * config.UI_SCALE) < .001
                assert dialog._inputs['max_items'] is draft and draft.get() == '632'
                assert draft.index('insert') == 2 and dialog.win.focus_get() is draft
                assert dialog.section == 'data' and not saved
                assert settings == dict(original_settings, ui_scale=config.UI_SCALE)
                assert abs(float(root.tk.call('tk', 'scaling')) - original_scaling) < .001
                live_samples.append(dict(source='settings-button', ui_scale=config.UI_SCALE))
                # Close while a deferred update is pending, then broadcast
                # again to catch dangling root bindings and destroyed callbacks.
                dialog._configured()
                pending = dialog._scale_job
                dialog.close()
                assert dialog._scale_job is None and dialog._scale_binding is None
                assert original_binding not in root.bind('<<ClawBoardUIScaleChanged>>')
                assert pending not in root.tk.splitlist(root.tk.call('after', 'info'))
                root.event_generate('<<ClawBoardUIScaleChanged>>', when='tail')
                pump(.2)
            assert not errors, errors
            assert not Path(config.DATA_FILE).exists(), 'standalone harness wrote a data file'
        finally:
            root.destroy()
    assert {str(path): digest(path) for path in real} == before, 'real data changed during regression'
    native_dpis = sorted({sample['settings_dpi'] for sample in samples})
    print(json.dumps(dict(passed=True, native_dpis=native_dpis, samples=samples,
                          live_scale_samples=live_samples,
                          two_dpi_monitors_verified=len(native_dpis) > 1,
                          real_hashes_unchanged=True)))


if __name__ == '__main__':
    run()
