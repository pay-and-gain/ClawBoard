"""Native export layout regression; synthetic records, no App or file export."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace

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
    with tempfile.TemporaryDirectory(prefix='cb-export-layout-') as temporary:
        config.BASE_DIR = temporary
        config.DATA_FILE = str(Path(temporary) / 'ClawBoard数据.json')
        config.CRASH_LOG = str(Path(temporary) / 'crash.log')
        runtime.NO_SAVE = True
        from clawboard.export_dialog import ExportDialog
        from clawboard.windows_geometry import monitors, top_hwnd
        from clawboard.windows_api import u32, MONITORINFO, MONITOR_DEFAULTTONEAREST
        from clawboard.win32 import init_dpi_awareness
        init_dpi_awareness()
        root = tk.Tk()
        root.title('ClawBoard synthetic export-layout regression')
        errors, samples = [], []
        root.report_callback_exception = lambda kind, error, trace: errors.append(repr(error))

        def pump(seconds=.15):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                root.update()
                time.sleep(.003)

        def inside(widget, bounds):
            left, top, right, bottom = bounds
            x, y = widget.winfo_rootx(), widget.winfo_rooty()
            assert widget.winfo_ismapped()
            assert left <= x and top <= y
            assert x + widget.winfo_width() <= right
            assert y + widget.winfo_height() <= bottom
            assert widget.winfo_height() >= widget.winfo_reqheight(), 'button clipped'

        try:
            for area in monitors():
                root.geometry('300x250%+d%+d' % (area[0] + 35, area[1] + 35))
                pump(.5)
                dpi = int(u32.GetDpiForWindow(top_hwnd(root)))
                info = MONITORINFO()
                info.cbSize = ctypes.sizeof(info)
                monitor = u32.MonitorFromWindow(top_hwnd(root), MONITOR_DEFAULTTONEAREST)
                assert u32.GetMonitorInfoW(monitor, ctypes.byref(info))
                r = info.rcWork
                work = (r.left, r.top, r.right, r.bottom)
                for level in (.5, 1.0, 1.5):
                    config.DPI_SCALE, config.UI_SCALE = dpi / 96, level
                    root.tk.call('tk', 'scaling', dpi / 72 * level)
                    app = SimpleNamespace(root=root,
                        vlist=SimpleNamespace(multi=set(), items=[{'id': 'synthetic', 'sens': ['test']}]),
                        application=SimpleNamespace(tasks=SimpleNamespace(invalidate=lambda *args: None)),
                        tip=lambda message: None)
                    dialog = ExportDialog(app)
                    pump(.5)
                    win = dialog.win
                    bounds = (win.winfo_rootx(), win.winfo_rooty(),
                              win.winfo_rootx() + win.winfo_width(),
                              win.winfo_rooty() + win.winfo_height())
                    assert work[0] <= bounds[0] < bounds[2] <= work[2], (work, bounds, dpi, level, root.geometry(), win.geometry())
                    assert work[1] <= bounds[1] < bounds[3] <= work[3], (work, bounds, dpi, level)
                    for button in (dialog._export_button, dialog._cancel_button):
                        inside(button, bounds)
                    # The footer must retain its full buttons when the body is constrained.
                    win.geometry('%dx%d' % (win.winfo_width(), max(180, win.winfo_height() // 2)))
                    pump()
                    bounds = (win.winfo_rootx(), win.winfo_rooty(),
                              win.winfo_rootx() + win.winfo_width(),
                              win.winfo_rooty() + win.winfo_height())
                    for button in (dialog._export_button, dialog._cancel_button):
                        inside(button, bounds)
                    assert dialog._body.canvas.winfo_height() > 0
                    samples.append(dict(native_dpi=dpi, ui_scale=level, footer_visible=True))
                    dialog.close()
                    pump(.05)
            assert not errors, errors
            assert not list(Path(temporary).iterdir()), 'layout test wrote files'
        finally:
            root.destroy()
    assert {str(path): digest(path) for path in real} == before, 'real data changed during regression'
    print(json.dumps(dict(passed=True, samples=samples, real_hashes_unchanged=True)))


if __name__ == '__main__':
    run()
