"""Native dialog lifecycle regression; synthetic stubs, no App or clipboard."""
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
    with tempfile.TemporaryDirectory(prefix='cb-dialog-lifecycle-') as temporary:
        config.BASE_DIR = temporary
        config.DATA_FILE = str(Path(temporary) / 'synthetic.json')
        config.CRASH_LOG = str(Path(temporary) / 'crash.log')
        runtime.NO_SAVE = True
        from clawboard.settings_dialog import SettingsWindow
        from clawboard.export_dialog import ExportDialog
        from clawboard.win32 import init_dpi_awareness
        init_dpi_awareness()
        root = tk.Tk()
        root.title('ClawBoard synthetic dialog lifecycle')
        sentinel = tk.Entry(root)
        sentinel.pack()
        python_errors, tcl_errors, samples, invalidated, saved = [], [], [], [], []
        root.report_callback_exception = lambda kind, error, trace: python_errors.append(repr(error))
        # An after script can fail before Python is entered. Tk's background
        # error handler is essential: report_callback_exception misses it.
        root.tk.createcommand('cb_lifecycle_bgerror', lambda message: tcl_errors.append(str(message)))
        root.tk.eval('proc bgerror {message} {cb_lifecycle_bgerror $message}')

        def pump(seconds=.2):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                root.update()
                time.sleep(.003)

        def after_ids():
            return set(root.tk.splitlist(root.tk.call('after', 'info')))

        def app_stub():
            app = SimpleNamespace(root=root, st=dict(config.DEFAULT_SETTINGS),
                vlist=SimpleNamespace(multi=set(), items=[dict(id='synthetic', text='synthetic')]),
                application=SimpleNamespace(tasks=SimpleNamespace(invalidate=invalidated.append)))
            for name in ('render', 'apply_effects', 'apply_trigger_setting', 'open_releases',
                         'apply_hotkey', 'rebuild', 'tip', 'quit_app', 'toggle_listen', 'set_ui_scale'):
                setattr(app, name, lambda *args: None)
            app.save = lambda *args: saved.append('save')
            return app

        def watch_focus(dialog):
            calls = []
            lift, focus = dialog.win.lift, dialog.win.focus_force
            def lifted(*args, **kwargs):
                calls.append('lift')
                return lift(*args, **kwargs)
            def focused(*args, **kwargs):
                calls.append('focus')
                return focus(*args, **kwargs)
            dialog.win.lift, dialog.win.focus_force = lifted, focused
            return calls

        try:
            pump(.05)
            with patch('clawboard.settings_dialog.get_autostart', return_value=(False, '')):
                for cls in (SettingsWindow, ExportDialog):
                    # Live windows retain the intended single deferred focus.
                    baseline = after_ids()
                    dialog = cls(app_stub())
                    calls = watch_focus(dialog)
                    pump()
                    assert calls == ['lift', 'focus'], (cls.__name__, calls)
                    dialog.close()
                    pump(.05)
                    assert after_ids() == baseline
                    for attempt in range(4):
                        baseline = after_ids()
                        dialog = cls(app_stub())
                        calls = watch_focus(dialog)
                        if attempt % 2:
                            dialog.win.destroy()
                            mode = 'direct-destroy'
                        else:
                            dialog.close()
                            mode = 'close'
                        remaining = sorted(after_ids() - baseline)
                        sentinel.focus_force()
                        pump()
                        samples.append(dict(dialog=cls.__name__, mode=mode,
                                            remaining_after=remaining, late_focus=calls))
                        assert not calls, (cls.__name__, 'closed dialog still focused', calls)
                        assert root.focus_lastfor() is sentinel
                        assert after_ids() == baseline
            assert not saved, 'unchanged synthetic settings unexpectedly saved'
            assert not list(Path(temporary).iterdir()), 'lifecycle test wrote files'
        finally:
            root.destroy()
    assert {str(path): digest(path) for path in real} == before, 'real data changed'
    result = dict(samples=samples, python_errors=python_errors, tcl_bgerrors=tcl_errors,
                  real_hashes_unchanged=True)
    print(json.dumps(result))
    assert not python_errors and not tcl_errors, result
    assert all(not sample['remaining_after'] for sample in samples), result


if __name__ == '__main__':
    run()
