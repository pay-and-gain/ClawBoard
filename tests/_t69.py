"""Native recycle-bin layout: temporary paths, NO_SAVE, no App or clipboard."""
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
    require_foreground = '--foreground' in sys.argv
    real = [ROOT / 'ClawBoard数据.json', Path.home() / 'Desktop/cut/ClawBoard数据.json',
            Path(os.environ['APPDATA']) / 'ClawBoard/ClawBoard数据.json']
    before = {str(path): digest(path) for path in real}
    with tempfile.TemporaryDirectory(prefix='cb-trash-native-ui-') as temporary:
        from clawboard import config, runtime
        config.BASE_DIR = temporary
        config.DATA_FILE = str(Path(temporary) / 'synthetic.json')
        config.CRASH_LOG = str(Path(temporary) / 'crash.log')
        runtime.NO_SAVE = True
        import tkinter as tk
        from clawboard.trash_dialog import TrashWindow
        from clawboard.windows_geometry import monitors, top_hwnd
        from clawboard.windows_api import u32
        from clawboard.win32 import init_dpi_awareness
        init_dpi_awareness()
        root = tk.Tk()
        root.title('ClawBoard synthetic recycle-bin validation')
        root.attributes('-topmost', True)
        python_errors, tcl_errors, samples, calls = [], [], [], []
        root.report_callback_exception = lambda kind, error, trace: python_errors.append(repr(error))
        root.tk.createcommand('cb_trash_bgerror', lambda message: tcl_errors.append(str(message)))
        root.tk.eval('proc bgerror {message} {cb_trash_bgerror $message}')
        rows = [
            dict(id='trash-phone', deleted_at=1700000000000,
                 item=dict(id='phone', text='phone 13812345678', sens=['手机号']), group=None),
            dict(id='trash-long', deleted_at=1700000001000,
                 item=dict(id='long', text='Synthetic long content\n' * 1200),
                 group=dict(name='Synthetic phrases', recycle_id='group-test'))]

        def forbidden(*args, **kwargs):
            calls.append('forbidden')
            raise AssertionError('NO_SAVE called a mutation or confirmation')

        app = SimpleNamespace(root=root, st=dict(mask_sensitive=True),
            application=SimpleNamespace(trash=SimpleNamespace(entries=lambda: list(rows))),
            recycle_restore=forbidden, recycle_purge=forbidden, recycle_expire=forbidden)

        def pump(seconds=.2):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                root.update()
                time.sleep(.004)

        def inside(button, window):
            x, y = window.winfo_rootx(), window.winfo_rooty()
            details = (button.cget('text'), button.winfo_rootx(), button.winfo_rooty(),
                       button.winfo_width(), button.winfo_height(), x, y,
                       window.winfo_width(), window.winfo_height(), str(window.focus_get()))
            assert button.winfo_ismapped(), button.cget('text')
            assert x <= button.winfo_rootx(), details
            assert y <= button.winfo_rooty(), details
            assert button.winfo_rootx() + button.winfo_width() <= x + window.winfo_width(), details
            assert button.winfo_rooty() + button.winfo_height() <= y + window.winfo_height(), details
            assert button.winfo_height() >= button.winfo_reqheight(), 'action clipped'

        try:
            with patch('clawboard.trash_dialog.messagebox.askyesno', forbidden):
                areas = monitors()
                root.geometry('300x250%+d%+d' % (areas[0][0] + 30, areas[0][1] + 30))
                pump()
                base_dpi = int(u32.GetDpiForWindow(top_hwnd(root)))
                foreground_ready = False
                for level in (.75, 1.0, 1.5):
                    config.DPI_SCALE, config.UI_SCALE = base_dpi / 96, level
                    root.tk.call('tk', 'scaling', base_dpi / 72 * level)
                    tk_scale = float(root.tk.call('tk', 'scaling'))
                    window = TrashWindow(app)
                    window.win.title('ClawBoard Synthetic Trash Acceptance')
                    pump()
                    window.win.lift()
                    window.listbox.focus_force()
                    if require_foreground and not foreground_ready:
                        print(json.dumps(dict(waiting_for_foreground=True,
                            title=window.win.title(), hwnd=top_hwnd(window.win),
                            pid=os.getpid(), timeout_seconds=90)), flush=True)
                        deadline = time.monotonic() + 90
                        while u32.GetForegroundWindow() != top_hwnd(window.win) and time.monotonic() < deadline:
                            pump(.04)
                        assert u32.GetForegroundWindow() == top_hwnd(window.win), 'foreground activation timed out'
                        foreground_ready = True
                    assert '13812345678' not in window.preview.get('1.0', 'end')
                    window.listbox.selection_clear(0, 'end')
                    window.listbox.selection_set(1)
                    window._selection_changed()
                    saved = window.preview.get('1.0', 'end')
                    assert '恢复会保留完整内容' in saved
                    assert len(saved) < window.PREVIEW_LIMIT + 256
                    window._focus_preview()
                    window.restore_selected()
                    window.purge_selected()
                    window.purge_all()
                    window.expire()
                    assert window.status.cget('text') == '自测模式，不改动资料'
                    for area in [*areas, areas[0]]:
                        window.win.geometry('%+d%+d' % (area[0] + 40, area[1] + 40))
                        pump(.65)
                        dpi = int(u32.GetDpiForWindow(top_hwnd(window.win)))
                        font_size = int(root.tk.call('font', 'configure', window.listbox.cget('font'), '-size'))
                        assert font_size == -round(abs(config.FONT[1]) * 96 / 72 * dpi / 96 * level)
                        assert window._selection_ids() == ['trash-long']
                        assert window.preview.get('1.0', 'end') == saved
                        window.win.geometry('%dx%d' % window.win.minsize())
                        pump()
                        inside(window.restore_button, window.win)
                        inside(window.close_button, window.win)
                        for button in (window.refresh_button, window.purge_button, window.clear_button):
                            # Make the synthetic target active before testing
                            # FocusIn; user activity may have focused another app.
                            button.focus_force()
                            pump(.08)
                            assert window.win.focus_get() is button, 'synthetic button lacks Tk focus'
                            foreground = u32.GetForegroundWindow() == top_hwnd(window.win)
                            if require_foreground:
                                assert foreground, 'synthetic window is not foreground'
                            else:
                                # This mode checks layout/reveal callbacks; it
                                # does not claim OS foreground keyboard input.
                                button.event_generate('<FocusIn>')
                                pump(.04)
                            inside(button, window.win)
                        assert config.DPI_SCALE == base_dpi / 96
                        assert abs(float(root.tk.call('tk', 'scaling')) - tk_scale) < .001
                        samples.append(dict(ui_scale=level, native_dpi=dpi,
                            fixed_footer=True, danger_buttons_reachable=True,
                            foreground_verified=foreground))
                    config.UI_SCALE = 1.25
                    root.event_generate('<<ClawBoardUIScaleChanged>>', when='tail')
                    pump()
                    assert abs(window._scale - dpi / 96 * 1.25) < .001
                    assert window._selection_ids() == ['trash-long']
                    binding = window._scale_binding
                    window._schedule('dpi', window._sync_scale)
                    pending = tuple(window._jobs.values())
                    window.close()
                    assert not window._jobs and window._scale_binding is None
                    assert binding not in root.bind('<<ClawBoardUIScaleChanged>>')
                    assert all(job not in root.tk.splitlist(root.tk.call('after', 'info')) for job in pending)
                    pump(.15)
                # A direct destroy must also cancel the window's pending jobs.
                fast = TrashWindow(app)
                fast.win.destroy()
                pump()
                assert fast._closed and not fast._jobs
                rows.clear()
                empty = TrashWindow(app)
                pump()
                assert '回收站为空' in empty.preview.get('1.0', 'end')
                assert empty.restore_button.cget('state') == 'disabled'
                empty.close()
                pump()
                assert not calls and not python_errors and not tcl_errors, (calls, python_errors, tcl_errors)
                assert not list(Path(temporary).iterdir()), 'synthetic UI wrote files'
        finally:
            root.destroy()
    assert {str(path): digest(path) for path in real} == before, 'real data changed'
    print(json.dumps(dict(passed=True, foreground_required=require_foreground,
                          samples=samples, no_save_guards=True,
                          callbacks_disposed=True, real_hashes_unchanged=True)))


if __name__ == '__main__':
    run()
