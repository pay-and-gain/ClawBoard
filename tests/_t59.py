"""Paper main-panel integration; synthetic Tk harness, no App or clipboard."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
from dataclasses import fields
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
    with tempfile.TemporaryDirectory(prefix='cb-paper-panel-') as temp:
        config.BASE_DIR = temp
        config.DATA_FILE = str(Path(temp) / 'ClawBoard数据.json')
        config.CRASH_LOG = str(Path(temp) / 'crash.log')
        runtime.NO_SAVE = True
        from clawboard.app_ui import UiMixin
        from clawboard.models import default_data
        from clawboard.theme import apply_theme
        from clawboard.windows_focus import window_is_current_process
        from clawboard.win32 import init_dpi_awareness, top_hwnd
        init_dpi_awareness()

        class Panel(UiMixin):
            def min_size(self):
                return config.scaled(config.MIN_W), config.scaled(config.MIN_H)

        app = Panel()
        defaults = config.AppState()
        for field in fields(config.AppState):
            setattr(app, field.name, getattr(defaults, field.name))
        app.root = tk.Tk()
        app.root.title('ClawBoard synthetic paper panel')
        app.root.geometry('500x500')
        app.data = default_data()
        app.data['clip'] = [dict(id='one', text='sample text', source_app='Synthetic',
                                 content_type='text', fav=1, created_at=1700000000000),
                            dict(id='two', text='sample image', source_app='Synthetic',
                                 content_type='image', image_w=20, image_h=10, fav=0)]
        app.data['groups'][0]['items'] = [dict(id='phrase', name='Synthetic phrase', text='phrase body')]
        app.st = app.data['settings']
        app.st['theme'] = 'light'
        apply_theme(app.st)
        app.search = tk.StringVar(master=app.root)
        app._search_trace = app._search_job = app._filter_pending = app._filter_result = None
        app.application = None
        errors, calls = [], []
        app.root.report_callback_exception = lambda kind, error, trace: errors.append(str(error))
        for name in ('hide', 'toggle_pin', 'toggle_collapse', 'start_move', 'do_move',
                     'on_click_item', 'on_menu_item', 'on_hover_item', 'open_repo',
                     'on_search_return', 'search_menu', 'select_all_visible', 'add_phrase',
                     'split_words', 'del_sel', 'clear_list', 'open_transform', 'open_settings',
                     'start_resize', 'do_resize', 'bind_edge_resize', 'save', 'note'):
            setattr(app, name, lambda *a, key=name: calls.append(key))
        try:
            app.build_ui()
            app.render()
            app.root.update()
            assert window_is_current_process(top_hwnd(app.root)) is True
            app.tab_fav._lb.invoke()
            assert app.tab == 'clip' and app.search.get() == 'is:fav'
            assert [r['id'] for r in app.vlist.items] == ['one']
            app.tab_clip._lb.invoke()
            app.search.set('sample')
            menus = []
            with patch.object(tk.Menu, 'tk_popup', lambda menu, *a: menus.append(menu)):
                app.filter_btn.invoke()
            menu = menus.pop()
            image_index = next(i for i in range(menu.index('end') + 1)
                               if menu.type(i) == 'command' and menu.entrycget(i, 'label') == '图片')
            menu.invoke(image_index)
            assert app.search.get() == 'sample type:image'
            assert [r['id'] for r in app.vlist.items] == ['two']
            menu.destroy()
            assert app.locate_workbench_item('clip', 'one')
            assert app.sel_clip == 'one' and app.search.get() == ''
            app.open_workbench()
            current = app._workbench_window
            app.root.update()
            assert window_is_current_process(top_hwnd(current.win)) is True
            current.query.set('sample')
            app.root.update()
            current.close()
            app.open_workbench()
            assert app._workbench_window.query.get() == 'sample'
            app._workbench_window.close()
            assert app.locate_workbench_item('phrase', 'phrase', 0)
            assert app.tab == 'phrase' and app.sel_phrase == 'phrase'
            assert not app.locate_workbench_item('clip', 'missing')
            assert not errors, errors
        finally:
            app.root.destroy()
    assert {str(p): digest(p) for p in paths} == before
    print('PASS: paper controls, visual query filters, favorites, workbench reopen/navigation, owned-window boundary; real data unchanged')


if __name__ == '__main__':
    run()
