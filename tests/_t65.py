"""Real App wiring smoke: temporary fixture, NO_SAVE, no clipboard writes."""
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
from tools.windows_test_guard import acquire_desktop_test_lease
acquire_desktop_test_lease()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def run():
    real = [ROOT / 'ClawBoard数据.json', Path.home() / 'Desktop/cut/ClawBoard数据.json',
            Path(os.environ['APPDATA']) / 'ClawBoard/ClawBoard数据.json']
    before = {str(path): digest(path) for path in real}
    with tempfile.TemporaryDirectory(prefix='cb-backup-app-') as temporary:
        from clawboard import config, runtime
        config.BASE_DIR = temporary
        config.DATA_FILE = str(Path(temporary) / 'ClawBoard数据.json')
        config.CRASH_LOG = str(Path(temporary) / 'crash.log')
        runtime.NO_SAVE = True
        from clawboard.models import default_data
        data = default_data()
        data['settings'].update(listen=False, trigger_enabled=False, update_check=False,
                                hotkey='none', onboarded=True, theme='light')
        data['clip'] = [dict(id='synthetic-smoke', text='Synthetic backup integration',
                             content_type='text')]
        fixture = Path(config.DATA_FILE)
        fixture.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        fixture_hash = digest(fixture)
        import tkinter as tk
        import ClawBoard as C
        C.NO_SAVE = True
        C.init_dpi_awareness()
        from clawboard.settings_dialog import SettingsWindow
        from clawboard.backup_dialog import BackupWindow
        root = tk.Tk()
        app = C.ClawBoard(root)
        errors, opened = [], []
        root.report_callback_exception = lambda kind, error, trace: errors.append(repr(error))

        def pump(seconds=.25):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                root.update()
                time.sleep(.004)

        def create_window(owner):
            window = BackupWindow(owner)
            opened.append(window)
            return window

        try:
            pump()
            settings = SettingsWindow(app)
            settings.select_section('data')
            pump()
            with patch('clawboard.backup_dialog.BackupWindow', side_effect=create_window):
                settings.layout.backup_button.invoke()
            pump()
            assert len(opened) == 1
            window = opened[0]
            assert window._base_dir == Path(temporary)
            assert window._service.data_file == fixture
            with (patch('clawboard.backup_dialog.filedialog.asksaveasfilename',
                        side_effect=AssertionError('NO_SAVE opened save picker')),
                  patch('clawboard.backup_dialog.filedialog.askopenfilename',
                        side_effect=AssertionError('NO_SAVE opened open picker')),
                  patch('clawboard.backup_dialog.prepare_restore_job',
                        side_effect=AssertionError('NO_SAVE prepared restore')),
                  patch('clawboard.backup_dialog.launch_restore_job',
                        side_effect=AssertionError('NO_SAVE launched helper')),
                  patch.object(app, 'quit_app', side_effect=AssertionError('NO_SAVE initiated quit'))):
                window.create_button.invoke()
                window.select_button.invoke()
                window.inspect_button.invoke()
                window.confirm_restore()
            pump()
            assert '自测' in window.status.cget('text')
            assert not window._busy and window.preview is None
            window.close()
            settings.close()
            pump()
            assert not errors, errors
            assert digest(fixture) == fixture_hash
            assert sorted(path.name for path in Path(temporary).iterdir()) == ['ClawBoard数据.json']
        finally:
            app.quit_app()
    assert {str(path): digest(path) for path in real} == before, 'real data changed'
    print('PASS: real App settings-to-backup wiring, temporary path, NO_SAVE, lifecycle; real hashes unchanged')


if __name__ == '__main__':
    run()
