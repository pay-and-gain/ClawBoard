"""Real Tk split-dialog layout regression; synthetic stub only, no App or clipboard access."""
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
    paths = [ROOT / 'ClawBoard数据.json', Path.home() / 'Desktop/cut/ClawBoard数据.json',
             Path(os.environ['APPDATA']) / 'ClawBoard/ClawBoard数据.json']
    before = {str(path): digest(path) for path in paths}
    with tempfile.TemporaryDirectory(prefix='cb-split-layout-') as temp:
        config.BASE_DIR = temp
        config.DATA_FILE = str(Path(temp) / 'ClawBoard数据.json')
        config.CRASH_LOG = str(Path(temp) / 'events.log')
        runtime.NO_SAVE = True
        from clawboard.widgets import SplitDialog
        from clawboard.win32 import init_dpi_awareness, monitors, u32, top_hwnd
        init_dpi_awareness()
        root = tk.Tk()
        root.title('ClawBoard synthetic split layout regression')
        errors = []
        root.report_callback_exception = lambda kind, value, trace: errors.append(kind.__name__)
        group = {'name': 'Synthetic', 'items': []}
        calls = []
        app = SimpleNamespace(root=root, cur_group=lambda: group,
                              save=lambda *args: calls.append('save'),
                              render=lambda: calls.append('render'), tip=lambda text: None, tab='clip')

        def pump():
            end = time.monotonic() + .12
            while time.monotonic() < end:
                root.update()
                time.sleep(.005)

        def buttons(dialog):
            return {child.cget('text'): child for child in dialog.footer.winfo_children()}

        def assert_visible(dialog):
            window = dialog.win
            for label, button in buttons(dialog).items():
                x, y = button.winfo_rootx() - window.winfo_rootx(), button.winfo_rooty() - window.winfo_rooty()
                assert button.winfo_ismapped(), label
                assert x >= 0 and y >= 0, label
                assert x + button.winfo_width() <= window.winfo_width(), label
                assert y + button.winfo_height() <= window.winfo_height(), label
                assert button.winfo_height() >= button.winfo_reqheight(), label
            assert dialog.txt.winfo_height() > 10
            assert dialog.prev.winfo_height() > 10

        cases = []
        try:
            for monitor in monitors():
                left, top, right, bottom = monitor
                for scale in (1.0, 1.25, 1.5):
                    root.geometry('450x500%+d%+d' % (left + 60, top + 60))
                    pump()
                    dpi = int(u32.GetDpiForWindow(top_hwnd(root)))
                    config.DPI_SCALE, config.UI_SCALE = dpi / 96, scale
                    root.tk.call('tk', 'scaling', dpi / 72 * scale)
                    text = '|'.join(('合成测试内容' * 100, '完整末尾测试', 'third'))
                    dialog = SplitDialog(app, text)
                    dialog.mode.set(dialog.MODES[-1])
                    dialog.do_preview()
                    pump()
                    assert_visible(dialog)
                    # A long preview remains scrollable without growing the window.
                    assert dialog.prev.cget('state') == 'disabled'
                    assert '完整末尾测试' in dialog.prev.get('1.0', 'end-1c')
                    assert dialog.do_split() == text.split('|')
                    initial_height = dialog.win.winfo_height()
                    dialog.do_preview()
                    pump()
                    assert dialog.win.winfo_height() == initial_height
                    minimum = dialog.win.minsize()
                    dialog.win.geometry('%dx%d' % minimum)
                    pump()
                    assert_visible(dialog)
                    cases.append(dict(dpi=dpi, ui_scale=scale, minimum=minimum))
                    buttons(dialog)['取消'].invoke()
                    root.update()
                    assert not dialog.win.winfo_exists() and not group['items'] and not calls
            dialog = SplitDialog(app, 'first|完整合成内容|third')
            dialog.mode.set(dialog.MODES[-1])
            pump()
            buttons(dialog)['拆成常用语'].invoke()
            root.update()
            assert [item['text'] for item in group['items']] == ['third', '完整合成内容', 'first']
            assert calls == ['save', 'render']
            dialog = SplitDialog(app, '')
            pump()
            dialog.ok()
            assert dialog.win.winfo_exists() and '没拆出' in dialog.prev.get('1.0', 'end-1c')
            assert_visible(dialog)
            dialog.cancel()
            assert not errors, errors
            assert {str(path): digest(path) for path in paths} == before, 'real data changed'
            assert not Path(config.DATA_FILE).exists()
            print(json.dumps(dict(passed=True, cases=cases, real_hashes_unchanged=True,
                                  cancel_and_split_bindings_passed=True), ensure_ascii=True))
        finally:
            root.destroy()


if __name__ == '__main__':
    run()
