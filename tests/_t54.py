"""Real Tk toolbar shrink regression; UI harness only, no App or clipboard access."""
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
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def run():
    import tkinter as tk
    from clawboard import config, runtime
    paths = [ROOT / 'ClawBoard数据.json', Path.home() / 'Desktop/cut/ClawBoard数据.json',
             Path(os.environ['APPDATA']) / 'ClawBoard/ClawBoard数据.json']
    before = {str(p): digest(p) for p in paths}
    with tempfile.TemporaryDirectory(prefix='cb-toolbar-layout-') as temp:
        config.BASE_DIR = temp
        config.DATA_FILE = str(Path(temp) / 'ClawBoard数据.json')
        config.CRASH_LOG = str(Path(temp) / 'events.log')
        runtime.NO_SAVE = True
        from clawboard.app_ui import UiMixin
        from clawboard.win32 import init_dpi_awareness, monitors, top_hwnd, u32
        init_dpi_awareness()

        class Panel(UiMixin):
            def min_size(self):
                return config.scaled(config.MIN_W), config.scaled(config.MIN_H)

        app = Panel()
        app.root = tk.Tk()
        app.root.title('ClawBoard synthetic toolbar layout regression')
        app.st, app._search_trace, app.collapsed = {}, None, False
        app.search = tk.StringVar(master=app.root)
        errors, calls = [], []
        app.root.report_callback_exception = lambda kind, error, trace: errors.append(kind.__name__)
        for name in ('hide', 'toggle_pin', 'toggle_collapse', 'start_move', 'do_move',
                     'on_click_item', 'on_menu_item', 'on_hover_item', 'load_samples',
                     'open_repo', '_search_changed', 'on_search_return', 'search_menu',
                     'select_all_visible', 'add_phrase', 'split_words', 'del_sel',
                     'clear_list', 'open_transform', 'open_settings', 'start_resize',
                     'do_resize', 'bind_edge_resize'):
            setattr(app, name, lambda *args, key=name: calls.append(key))

        def pump():
            end = time.monotonic() + .08
            while time.monotonic() < end:
                app.root.update()
                time.sleep(.005)
            app._layout_tool()
            app.root.update()

        def check():
            assert app.tool.winfo_ismapped()
            assert app.tool.winfo_height() == config.scaled(config.TOOL_H)
            assert app.search_entry.winfo_ismapped()
            assert config.scaled(48) <= app.search_entry.winfo_width() <= config.scaled(100)
            if not app.search.get():
                assert app.search_ph.winfo_rootx() >= app.search_entry.winfo_rootx()
                assert app.search_ph.winfo_rootx() + app.search_ph.winfo_width() <= (
                    app.search_entry.winfo_rootx() + app.search_entry.winfo_width())
            assert app.vlist.winfo_height() > 5
            shown = []
            for text, widget in app._tool_btns + [('more', app.more_btn)]:
                expected = bool(app._tool_hidden) if text == 'more' else text not in app._tool_hidden
                assert bool(widget.winfo_ismapped()) == expected, text
                if not expected:
                    continue
                shown.append(widget)
                assert widget.winfo_width() >= widget.winfo_reqwidth(), text
                assert widget.winfo_height() >= widget.winfo_reqheight(), text
                x = widget.winfo_rootx() - app.tool.winfo_rootx()
                y = widget.winfo_rooty() - app.tool.winfo_rooty()
                assert x >= 0 and y >= 0, text
                assert x + widget.winfo_width() <= app.tool.winfo_width(), text
                assert y + widget.winfo_height() <= app.tool.winfo_height(), text
            for text in ('＋', '删', '拆', '⚙'):
                assert dict(app._tool_btns)[text].winfo_ismapped(), text
            expected_order = [t for t in ('＋', '删', '拆', '清', '🔧', '⚙') if t not in app._tool_hidden]
            actual_order = [b.cget('text') for b in sorted(shown, key=lambda b: b.winfo_rootx())
                            if b is not app.more_btn]
            assert actual_order == expected_order
            assert actual_order.index('拆') == actual_order.index('删') + 1
            assert app.search_entry.winfo_rootx() + app.search_entry.winfo_width() <= min(
                b.winfo_rootx() for b in shown)

        samples = []
        try:
            for monitor in monitors():
                left, top, right, bottom = monitor
                app.root.geometry('500x600%+d%+d' % (left + 60, top + 60))
                app.root.update()
                dpi = int(u32.GetDpiForWindow(top_hwnd(app.root)))
                for level in (.5, .75, 1.0, 1.25, 1.5):
                    config.DPI_SCALE, config.UI_SCALE = dpi / 96, level
                    app.root.tk.call('tk', 'scaling', dpi / 72 * level)
                    app.build_ui()
                    for width, height in ((640, 500), (280, 340), (320, 340),
                                          (640, 340), (280, 500), (640, 500)):
                        app.root.geometry('%dx%d%+d%+d' % (config.scaled(width), config.scaled(height),
                                                          left + 60, top + 60))
                        pump()
                        check()
                    app.root.geometry('%dx%d' % (config.scaled(280), config.scaled(340)))
                    pump()
                    assert all(button.winfo_ismapped() for _, button in app._tool_btns)
                    # Wider control metrics exercise the overflow fallback without
                    # changing the user's minimum window size or hiding Split.
                    dict(app._tool_btns)['清'].configure(width=40)
                    app._last_tw = 0
                    pump()
                    check()
                    menus = []
                    with patch.object(tk.Menu, 'tk_popup', lambda menu, *args: menus.append(menu)):
                        app.more_menu()
                    menu = menus[-1]
                    assert menu.index('end') + 1 == len(app._tool_hidden)
                    labels = [menu.entrycget(i, 'label') for i in range(menu.index('end') + 1)]
                    assert all('拆词' not in label for label in labels)
                    start = len(calls)
                    menu.invoke(0)
                    assert len(calls) == start + 1 and calls[-1] in ('clear_list', 'open_transform')
                    menu.destroy()
                    dict(app._tool_btns)['清'].configure(width=3)
                    app._last_tw = 0
                    pump()
                    app.body.pack_forget()
                    pump()
                    app.body.pack(fill='both', expand=True)
                    pump()
                    check()
                    samples.append(dict(dpi=dpi, ui_scale=level, sizes_checked=6))
            assert not errors, errors
            assert {str(p): digest(p) for p in paths} == before, 'real data changed'
            assert not Path(config.DATA_FILE).exists()
            print(json.dumps(dict(passed=True, samples=samples, real_hashes_unchanged=True,
                                  compact_search_and_button_order_passed=True)))
        finally:
            app.root.destroy()


if __name__ == '__main__':
    run()
