"""Native merge-import acceptance: leased desktop, synthetic App, NO_SAVE."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def digest(path):
    if not path.is_file():
        return None
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def run():
    from tools import windows_test_guard as guard
    guard.acquire_desktop_test_lease()
    real = [ROOT / 'ClawBoard数据.json', Path.home() / 'Desktop/cut/ClawBoard数据.json',
            Path(os.environ.get('APPDATA', str(Path.home()))) / 'ClawBoard/ClawBoard数据.json']
    before = {str(path): digest(path) for path in real}
    result = dict(passed=False, no_save=True, lease_released=False)
    try:
        result.update(_run_temporary())
    finally:
        unchanged = {str(path): digest(path) for path in real} == before
        result['real_hashes_unchanged'] = unchanged
        guard._release()
        result['lease_released'] = True
        print(json.dumps(result, ensure_ascii=False), flush=True)
        assert unchanged, 'real library hash changed'


def _run_temporary():
    with tempfile.TemporaryDirectory(prefix='cb-real-import-acceptance-') as temporary:
        from clawboard import config, runtime
        base = Path(temporary)
        config.BASE_DIR = temporary
        config.DATA_FILE = str(base / 'ClawBoard数据.json')
        config.CRASH_LOG = str(base / 'crash.log')
        runtime.NO_SAVE = True
        from clawboard.models import default_data, normalize_item
        data = default_data()
        data['settings'].update(listen=False, trigger_enabled=False, update_check=False,
            hotkey='none', hotkey_enabled=False, onboarded=True, first_run=False,
            mask_sensitive=True, theme='light')
        data['clip'] = [normalize_item(dict(id='synthetic-current', text='Synthetic existing',
            content_type='text', created_at=1700000000000), 1)]
        fixture = Path(config.DATA_FILE)
        fixture.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        long_body = 'Synthetic complete long content 中文 😀\n' * 1100
        incoming = base / 'synthetic-export.json'
        incoming.write_text(json.dumps(dict(version=3, items=[
            dict(id='incoming-long', text=long_body, content_type='text'),
            dict(id='incoming-duplicate', text='Synthetic existing', content_type='text'),
            dict(id='incoming-phone', text='Synthetic phone 13812345678',
                 content_type='text', sens=[], mask_off=True),
            dict(id='incoming-missing-image', text='[图片]', content_type='image',
                 image_path='synthetic-missing.png')]), ensure_ascii=False), encoding='utf-8')
        fixture_before = {str(path): digest(path) for path in base.iterdir() if path.is_file()}
        import tkinter as tk
        import ClawBoard as C
        C.NO_SAVE = True
        C.init_dpi_awareness()
        from clawboard.import_dialog import ImportWindow
        from clawboard.import_service import ImportService
        from clawboard.settings_dialog import SettingsWindow
        from clawboard.windows_geometry import monitors, top_hwnd
        from clawboard.windows_api import u32
        root = tk.Tk()
        python_errors, tcl_errors, opened, samples, forbidden_calls = [], [], [], [], []
        root.report_callback_exception = lambda kind, error, trace: python_errors.append(type(error).__name__)
        root.tk.createcommand('cb_import_bgerror', lambda message: tcl_errors.append(str(message)))
        root.tk.eval('proc bgerror {message} {cb_import_bgerror $message}')
        app = C.ClawBoard(root)

        def pump(seconds=.25):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                root.update()
                time.sleep(.004)

        def forbidden(*args, **kwargs):
            forbidden_calls.append(True)
            raise AssertionError('NO_SAVE called picker, confirmation, helper or quit')

        def create_window(owner):
            window = ImportWindow(owner)
            opened.append(window)
            return window

        def inside(widget, window):
            x, y = window.winfo_rootx(), window.winfo_rooty()
            assert widget.winfo_ismapped(), 'unmapped control'
            assert x <= widget.winfo_rootx(), 'left edge clipped'
            assert y <= widget.winfo_rooty(), 'top edge clipped'
            assert widget.winfo_rootx() + widget.winfo_width() <= x + window.winfo_width(), 'right edge clipped'
            assert widget.winfo_rooty() + widget.winfo_height() <= y + window.winfo_height(), 'bottom edge clipped'
            assert widget.winfo_height() >= widget.winfo_reqheight(), 'control height clipped'

        def guards(window):
            with (patch('clawboard.import_dialog.filedialog.askopenfilename', forbidden),
                  patch('clawboard.import_dialog.messagebox.askyesno', forbidden),
                  patch('clawboard.import_dialog.prepare_import_job', forbidden),
                  patch('clawboard.import_dialog.launch_restore_job', forbidden),
                  patch.object(app, 'quit_app', forbidden)):
                window.choose_archive()
                window.inspect_archive()
                window.confirm_import()
                if window.preview:
                    window._start_import(window.preview, window._selection_keys())
            assert not forbidden_calls
            assert '自测' in window.status.cget('text')

        def check_disposed(window):
            binding = window._scale_binding
            window._schedule('dpi', window._sync_scale)
            pending = tuple(window._jobs.values())
            window.close()
            assert window._closed and not window._jobs
            assert window._scale_binding is None and not window.archive.trace_info()
            assert binding not in root.bind('<<ClawBoardUIScaleChanged>>')
            assert all(job not in root.tk.splitlist(root.tk.call('after', 'info')) for job in pending)
            pump(.16)

        try:
            pump()
            settings = SettingsWindow(app)
            settings.select_section('data')
            with patch('clawboard.import_dialog.ImportWindow', side_effect=create_window):
                settings.layout.import_button.invoke()
            pump()
            assert len(opened) == 1, 'settings import entry not wired'
            entry_window = opened[0]
            assert entry_window._service.data_file == fixture
            guards(entry_window)
            check_disposed(entry_window)
            settings.close()
            pump()
            areas = monitors()
            assert len(areas) >= 2, 'two-monitor acceptance requires two monitors'
            base_dpi = int(u32.GetDpiForWindow(top_hwnd(root)))
            preview = ImportService(fixture).inspect(incoming, deepcopy(app.data))
            assert preview.plan.duplicate_count == 1
            assert any(row.status == 'blocked' for row in preview.plan.rows)
            assert preview.plan.error, 'mixed missing-image preview must explain partial selection'
            for level in (.75, 1.0, 1.5):
                app.set_ui_scale(level)
                pump()
                root_scaling = float(root.tk.call('tk', 'scaling'))
                window = ImportWindow(app)
                window.win.title('ClawBoard Synthetic Import Acceptance')
                pump()
                window._show_preview(preview)
                assert window._selection_keys() == ('c:0', 'c:2')
                window.listbox.selection_clear(0, 'end')
                window.listbox.selection_set(2)
                window._selection_changed()
                assert '13812345678' not in window.preview_text.get('1.0', 'end')
                assert '13812345678' not in window.listbox.get(2)
                window.listbox.selection_clear(0, 'end')
                window.listbox.selection_set(0)
                window._selection_changed()
                saved = window.preview_text.get('1.0', 'end')
                assert long_body in saved and '仅显示前' not in saved
                assert window.preview_text.cget('state') == 'disabled'
                window.path_entry.icursor(3)
                window.preview_text.mark_set('insert', '4.4')
                guards(window)
                for area in [*areas, areas[0]]:
                    window.win.geometry('%+d%+d' % (area[0] + 40, area[1] + 40))
                    pump(.65)
                    dpi = int(u32.GetDpiForWindow(top_hwnd(window.win)))
                    font = int(root.tk.call('font', 'configure', window.listbox.cget('font'), '-size'))
                    assert font == -round(abs(config.FONT[1]) * 96 / 72 * dpi / 96 * level)
                    assert window._selection_keys() == ('c:0',)
                    assert window.preview_text.get('1.0', 'end') == saved
                    assert window.path_entry.index('insert') == 3
                    assert window.preview_text.index('insert') == '4.4'
                    window.win.geometry('%dx%d' % window.win.minsize())
                    pump()
                    inside(window.import_button, window.win)
                    inside(window.close_button, window.win)
                    for control in (window.select_button, window.inspect_button,
                                    window.all_button, window.none_button, window.path_entry,
                                    window.listbox, window.preview_text):
                        control.focus_force()
                        control.event_generate('<FocusIn>')
                        pump(.08)
                        inside(control, window.win)
                    assert abs(float(root.tk.call('tk', 'scaling')) - root_scaling) < .001
                    assert config.DPI_SCALE == base_dpi / 96
                    samples.append(dict(ui_scale=level, native_dpi=dpi, fixed_footer=True,
                        focus_reveal=True, selection_and_content_retained=True))
                app.set_ui_scale(1.25)
                pump()
                assert abs(window._scale - dpi / 96 * 1.25) < .001
                assert window._selection_keys() == ('c:0',)
                assert window.preview_text.get('1.0', 'end') == saved
                assert window.path_entry.index('insert') == 3
                check_disposed(window)
            for _ in range(4):
                quick = ImportWindow(app)
                quick.win.destroy()
                assert quick._closed and not quick._jobs
            root.event_generate('<<ClawBoardUIScaleChanged>>', when='tail')
            pump()
            assert not python_errors and not tcl_errors, (python_errors, tcl_errors)
            assert not app.application.dispatcher.errors
            assert {str(path): digest(path) for path in base.iterdir() if path.is_file()} == fixture_before
            assert not (base / '.restore-jobs').exists()
            assert not (base / 'images').exists()
            return dict(passed=True, settings_entry=True, default_selection=True,
                privacy_mask=True, full_long_preview=True, callbacks_disposed=True,
                samples=samples, python_errors=python_errors, tcl_errors=tcl_errors,
                synthetic_hashes_unchanged=True, foreground_keyboard_claimed=False)
        finally:
            app.quit_app()


if __name__ == '__main__':
    run()
