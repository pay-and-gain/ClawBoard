"""Native backup layout: temporary synthetic library, NO_SAVE, no App/clipboard."""
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
    with tempfile.TemporaryDirectory(prefix='cb-native-backup-ui-') as temporary:
        base = Path(temporary)
        source, images = base / 'synthetic.json', base / 'synthetic-images'
        source.write_text(json.dumps(dict(schema_version=3,
            clip=[dict(id='synthetic', text='complete synthetic fixture')], groups=[], settings={})), encoding='utf-8')
        config.BASE_DIR, config.DATA_FILE = temporary, str(source)
        config.CRASH_LOG = str(base / 'crash.log')
        runtime.NO_SAVE = True
        from clawboard.backup_dialog import BackupWindow
        from clawboard.backups import BackupService
        from clawboard.windows_geometry import monitors, top_hwnd
        from clawboard.windows_api import u32
        from clawboard.win32 import init_dpi_awareness
        init_dpi_awareness()
        # Core creation is path-injected and cannot use the runtime data file.
        preview = BackupService(source, images).create(base / 'synthetic-backup.zip')
        temporary_before = {str(path): digest(path) for path in base.iterdir() if path.is_file()}
        root = tk.Tk()
        root.title('ClawBoard synthetic backup layout')
        root.attributes('-topmost', True)
        errors, samples, invalidated = [], [], []
        root.report_callback_exception = lambda kind, error, trace: errors.append(repr(error))

        def pump(seconds=.35):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                root.update()
                time.sleep(.004)

        def forbidden(*args, **kwargs):
            raise AssertionError('NO_SAVE must block picker, save, restore helper and quit')

        def inside(button, window):
            x, y = window.winfo_rootx(), window.winfo_rooty()
            assert button.winfo_ismapped(), button.cget('text')
            assert x <= button.winfo_rootx()
            assert y <= button.winfo_rooty()
            assert button.winfo_rootx() + button.winfo_width() <= x + window.winfo_width()
            assert button.winfo_rooty() + button.winfo_height() <= y + window.winfo_height()
            assert button.winfo_height() >= button.winfo_reqheight(), 'action clipped'

        app = SimpleNamespace(root=root, _store=SimpleNamespace(path=source),
            application=SimpleNamespace(image_store=SimpleNamespace(directory=images),
                tasks=SimpleNamespace(invalidate=invalidated.append, submit=forbidden)),
            save_now=forbidden, quit_app=forbidden)
        try:
            with patch('clawboard.backup_dialog.filedialog.askopenfilename', forbidden), \
                 patch('clawboard.backup_dialog.filedialog.asksaveasfilename', forbidden), \
                 patch('clawboard.backup_dialog.prepare_restore_job', forbidden), \
                 patch('clawboard.backup_dialog.launch_restore_job', forbidden):
                areas = monitors()
                root.geometry('300x250%+d%+d' % (areas[0][0] + 30, areas[0][1] + 30))
                pump()
                base_dpi = int(u32.GetDpiForWindow(top_hwnd(root)))
                for level in (.75, 1.0, 1.5):
                    config.DPI_SCALE, config.UI_SCALE = base_dpi / 96, level
                    root.tk.call('tk', 'scaling', base_dpi / 72 * level)
                    scaling = float(root.tk.call('tk', 'scaling'))
                    window = BackupWindow(app)
                    pump()
                    window._show_preview(preview)
                    window._paint_busy()
                    window.path_entry.icursor(3)
                    window.win.lift()
                    window.path_entry.focus_force()
                    pump(.1)
                    saved_text = window.preview_label.cget('text')
                    window.create_backup()
                    window.choose_archive()
                    window.inspect_archive()
                    window.confirm_restore()
                    for area in [*areas, areas[0]]:
                        window.win.geometry('%+d%+d' % (area[0] + 40, area[1] + 40))
                        pump(.65)
                        dpi = int(u32.GetDpiForWindow(top_hwnd(window.win)))
                        font_size = int(root.tk.call('font', 'configure', window.path_entry.cget('font'), '-size'))
                        assert font_size == -round(12 * dpi / 96 * level)
                        assert window.preview is preview and window.preview_label.cget('text') == saved_text
                        assert window.path_entry.index('insert') == 3
                        assert window.win.focus_get() is window.path_entry
                        window.win.geometry('%dx%d' % window.win.minsize())
                        pump()
                        inside(window.close_button, window.win)
                        for button in (window.create_button, window.select_button,
                                       window.inspect_button, window.restore_button):
                            button.focus_set()
                            pump(.05)
                            inside(button, window.win)
                        window.path_entry.focus_set()
                        pump(.05)
                        assert config.DPI_SCALE == base_dpi / 96
                        assert abs(float(root.tk.call('tk', 'scaling')) - scaling) < .001
                        samples.append(dict(ui_scale=level, native_dpi=dpi, narrow_buttons_reachable=True))
                    config.UI_SCALE = 1.25
                    root.event_generate('<<ClawBoardUIScaleChanged>>', when='tail')
                    pump()
                    assert abs(window._scale - dpi / 96 * 1.25) < .001
                    assert window.preview is preview
                    binding = window._scale_binding
                    window._schedule('dpi', window._sync_scale)
                    pending = tuple(window._jobs.values())
                    window.close()
                    assert not window._jobs and window._scale_binding is None
                    assert not window.archive.trace_info()
                    assert binding not in root.bind('<<ClawBoardUIScaleChanged>>')
                    assert all(job not in root.tk.splitlist(root.tk.call('after', 'info')) for job in pending)
                    root.event_generate('<<ClawBoardUIScaleChanged>>', when='tail')
                    pump(.15)
                assert not errors, errors
                assert len(invalidated) == 3
                assert {str(path): digest(path) for path in base.iterdir() if path.is_file()} == temporary_before
        finally:
            root.destroy()
    assert {str(path): digest(path) for path in real} == before, 'real data changed'
    print(json.dumps(dict(passed=True, samples=samples, no_save_guards=True,
                          callbacks_disposed=True, real_hashes_unchanged=True)))


if __name__ == '__main__':
    run()
