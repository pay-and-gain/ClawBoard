"""Native fixed-top actions: synthetic App, temporary paths, NO_SAVE throughout."""
import hashlib
import json
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
    from tools.windows_test_guard import acquire_desktop_test_lease
    acquire_desktop_test_lease()
    real = [ROOT / 'ClawBoard数据.json', Path.home() / 'Desktop/cut/ClawBoard数据.json',
            Path(os.environ['APPDATA']) / 'ClawBoard/ClawBoard数据.json']
    before = {str(path): digest(path) for path in real}
    with tempfile.TemporaryDirectory(prefix='cb-v4-top-actions-') as temporary:
        from clawboard import config, runtime
        config.BASE_DIR = temporary
        config.DATA_FILE = str(Path(temporary) / 'ClawBoard数据.json')
        config.CRASH_LOG = str(Path(temporary) / 'crash.log')
        runtime.NO_SAVE = True
        from clawboard.models import default_data, normalize_item
        data = default_data()
        data['settings'].update(listen=False, trigger_enabled=False, hotkey_enabled=False,
                                update_check=False, first_run=False, edge_hide=False)
        data['clip'] = [normalize_item(dict(id='synthetic', text='Synthetic v4 action test'), 1)]
        fixture = Path(config.DATA_FILE)
        fixture.write_text(json.dumps(data), encoding='utf-8')
        fixture_hash = digest(fixture)
        import tkinter as tk
        import ClawBoard as C
        C.NO_SAVE = True
        C.init_dpi_awareness()
        from clawboard.settings_dialog import SettingsWindow
        from clawboard.backup_dialog import BackupWindow
        from clawboard.trash_dialog import TrashWindow
        from clawboard.import_dialog import ImportWindow
        from clawboard.export_dialog import ExportDialog
        from clawboard.workbench import WorkbenchWindow
        root = tk.Tk()
        app = C.ClawBoard(root)
        errors, tcl_errors, checks = [], [], []
        root.report_callback_exception = lambda kind, error, trace: errors.append(repr(error))
        root.tk.createcommand('v4_top_bgerror', lambda value: tcl_errors.append(str(value)))
        root.tk.eval('proc bgerror {message} {v4_top_bgerror $message}')
        def pump(seconds=.12):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                root.update()
                time.sleep(.004)
        def inside(button, window):
            assert button.winfo_ismapped(), 'unmapped action'
            x, y = button.winfo_rootx() - window.winfo_rootx(), button.winfo_rooty() - window.winfo_rooty()
            assert x >= 0 and y >= 0
            assert x + button.winfo_width() <= window.winfo_width() + 2
            assert y + button.winfo_height() <= window.winfo_height() + 2
        try:
            pump(.3)
            for level in (.75, 1.0, 1.5):
                config.UI_SCALE = level
                for factory in (SettingsWindow, BackupWindow, TrashWindow,
                                ImportWindow, ExportDialog, WorkbenchWindow):
                    app.tab = 'clip'
                    app.render()
                    pump()
                    window = factory(app)
                    pump()
                    win = window.win
                    win.geometry('380x340')
                    pump(.2)
                    if isinstance(window, SettingsWindow):
                        actions = (window.layout.close_button, window.layout.quit_button)
                        body = window.layout.shell
                    elif isinstance(window, BackupWindow) and not isinstance(window, ImportWindow):
                        actions = (window.create_button, window.inspect_button,
                                   window.restore_button, window.close_button)
                        body = window.body
                    elif isinstance(window, TrashWindow):
                        actions = (window.restore_button, window.purge_button,
                                   window.clear_button, window.close_button)
                        body = window.body
                    elif isinstance(window, ImportWindow):
                        actions = (window.import_button, window.close_button)
                        body = window.body
                    elif isinstance(window, ExportDialog):
                        actions = (window._export_button, window._cancel_button)
                        body = window._body
                    else:
                        actions = (window.locate_button, window.preview_button, window.close_button)
                        body = window.body
                    for button in actions:
                        inside(button, win)
                        assert button.winfo_rooty() < body.winfo_rooty(), factory.__name__ + ' action below body'
                        assert button.winfo_class() == 'Button'
                    checks.append(dict(window=factory.__name__, ui_scale=level,
                                       actions_visible_above_body=True))
                    window.close()
                    pump()
            assert not errors and not tcl_errors, (errors, tcl_errors)
            assert digest(fixture) == fixture_hash
            assert not (Path(temporary) / '.restore-jobs').exists()
        finally:
            app.quit_app()
    assert {str(path): digest(path) for path in real} == before
    print(json.dumps(dict(passed=True, checks=checks, real_hashes_unchanged=True)))


if __name__ == '__main__':
    run()
