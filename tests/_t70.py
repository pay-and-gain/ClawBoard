"""Real App recycle wiring: synthetic paths before imports, NO_SAVE throughout."""
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
    with tempfile.TemporaryDirectory(prefix='cb-real-recycle-app-') as temporary:
        from clawboard import config, runtime
        config.BASE_DIR = temporary
        config.DATA_FILE = str(Path(temporary) / 'ClawBoard数据.json')
        config.CRASH_LOG = str(Path(temporary) / 'crash.log')
        runtime.NO_SAVE = True
        from clawboard.models import default_data, normalize_item
        data = default_data()
        data['settings'].update(listen=False, trigger_enabled=False, update_check=False,
                                hotkey_enabled=False, first_run=False)
        original = normalize_item(dict(id='synthetic', text='Synthetic deleted 中文 😀',
            created_at=1700000000000, future={'retained': True}), 4)
        data['clip'] = [original]
        data['groups'][0]['items'] = [normalize_item(dict(id='phrase', text='Synthetic phrase',
            created_at=1700000000000, trigger='cb_synthetic'), 5)]
        fixture = Path(config.DATA_FILE)
        fixture.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        fixture_hash = digest(fixture)
        import tkinter as tk
        import ClawBoard as C
        C.NO_SAVE = True
        C.init_dpi_awareness()
        from clawboard.settings_dialog import SettingsWindow
        from clawboard.trash_dialog import TrashWindow
        root = tk.Tk()
        app = C.ClawBoard(root)
        # Exercise mapping refresh without installing a global keyboard hook.
        from clawboard.trigger import TriggerEngine
        app._trigger_engine = TriggerEngine()
        app._refresh_triggers()
        errors, tcl_errors, opened = [], [], []
        root.report_callback_exception = lambda kind, error, trace: errors.append(repr(error))
        root.tk.createcommand('cb_real_trash_bgerror', lambda message: tcl_errors.append(str(message)))
        root.tk.eval('proc bgerror {message} {cb_real_trash_bgerror $message}')
        def pump(seconds=.2):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                root.update()
                time.sleep(.004)
        def create_window(owner):
            window = TrashWindow(owner)
            opened.append(window)
            return window
        try:
            pump()
            app.del_item('synthetic', 'clip')
            app.del_item('phrase', 'phrase')
            self_entries = app.application.trash.entries()
            assert len(self_entries) == 2 and not app.data['clip']
            assert 'cb_synthetic' not in app._trigger_engine.triggers
            settings = SettingsWindow(app)
            settings.select_section('data')
            with patch('clawboard.trash_dialog.TrashWindow', side_effect=create_window):
                settings.layout.trash_button.invoke()
            pump()
            assert len(opened) == 1
            window = opened[0]
            assert len(window._rows) == 2
            with (patch.object(app, 'recycle_restore', side_effect=AssertionError('NO_SAVE restore')),
                  patch.object(app, 'recycle_purge', side_effect=AssertionError('NO_SAVE purge')),
                  patch('clawboard.trash_dialog.messagebox.askyesno',
                        side_effect=AssertionError('NO_SAVE confirmation'))):
                window.restore_selected()
                window.purge_selected()
                window.purge_all()
            assert '自测' in window.status.cget('text')
            restored = app.recycle_restore([entry['id'] for entry in self_entries])
            assert len(restored) == 2
            assert app.data['clip'][0] == original
            assert app._trigger_engine.triggers['cb_synthetic'] == 'Synthetic phrase'
            window.refresh()
            assert not window._rows
            window.close()
            settings.close()
            pump()
            assert not errors and not tcl_errors, (errors, tcl_errors)
            assert digest(fixture) == fixture_hash
            assert sorted(path.name for path in Path(temporary).iterdir()) == ['ClawBoard数据.json']
        finally:
            app.quit_app()
    assert {str(path): digest(path) for path in real} == before, 'real data changed'
    print('PASS: real App recycle entry, deletion/restore, trigger refresh, NO_SAVE and lifecycle; real hashes unchanged')


if __name__ == '__main__':
    run()
