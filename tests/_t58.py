"""Real Tk workbench harness; synthetic data and no App or clipboard access."""
from copy import deepcopy
import hashlib
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
    real_paths = [ROOT / 'ClawBoard数据.json', Path.home() / 'Desktop/cut/ClawBoard数据.json',
                  Path(os.environ['APPDATA']) / 'ClawBoard/ClawBoard数据.json']
    before_hashes = {str(path): digest(path) for path in real_paths}
    with tempfile.TemporaryDirectory(prefix='cb-workbench-') as temp:
        config.BASE_DIR = temp
        config.DATA_FILE = str(Path(temp) / 'ClawBoard数据.json')
        config.CRASH_LOG = str(Path(temp) / 'crash.log')
        runtime.NO_SAVE = True
        from clawboard.workbench import WorkbenchWindow
        from clawboard.theme import apply_theme
        from clawboard.win32 import init_dpi_awareness
        from clawboard.dispatch import EventDispatcher
        from clawboard.tasks import WorkerTasks
        from clawboard.image import dib_to_png
        from clawboard.media import ImageStore
        from clawboard.thumbnails import ThumbnailCache
        import struct
        init_dpi_awareness()
        root = tk.Tk()
        root.title('ClawBoard synthetic workbench regression')
        root.geometry('300x380+80+80')
        errors, located = [], []
        root.report_callback_exception = lambda kind, error, trace: errors.append(repr(error))
        records = [dict(id='clip-%d' % index, text='Synthetic content %d' % index,
                        content_type='text', content_size=24, source_app='SyntheticApp')
                   for index in range(80)]
        records[3]['text'] = '完整内容 ' * 3000 + '保留完整末尾'
        records[4]['text'] = 'password=synthetic-private-value'
        records[4]['sens'] = ['密码']
        store = ImageStore(Path(temp) / 'images')
        header = struct.pack('<IiiHHIIiiII', 40, 32, 16, 1, 32, 0, 32 * 16 * 4, 0, 0, 0, 0)
        name = store.write(dib_to_png(header + bytes((100, 160, 180, 255)) * (32 * 16))[0])
        records[5].update(content_type='image', image_path=name, image_w=32, image_h=16)
        data = dict(clip=records, groups=[dict(name='Synthetic group', items=[
            dict(id='phrase-1', name='Synthetic name', text='Synthetic phrase')])])
        before_data = deepcopy(data)
        settings = dict(config.DEFAULT_SETTINGS)
        apply_theme(settings)
        dispatcher = EventDispatcher()
        tasks = WorkerTasks(dispatcher)
        app = SimpleNamespace(root=root, data=data, st=settings,
                              search=tk.StringVar(master=root, value='unchanged main search'),
                              application=SimpleNamespace(data_revision=0, tasks=tasks),
                              _thumbnail_cache=ThumbnailCache(store))
        window = WorkbenchWindow(app, on_locate=lambda entry: located.append(entry))

        def pump(seconds=.18):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                root.update()
                dispatcher.drain()
                time.sleep(.004)

        def select(index):
            window.listbox.selection_clear(0, 'end')
            window.listbox.selection_set(index)
            window.listbox.event_generate('<<ListboxSelect>>')
            pump()

        try:
            pump(.4)
            assert len(window._rows) == 80
            assert window.meta.cget('text') == ''
            select(3)
            assert window.preview.get('1.0', 'end-1c') == records[3]['text']
            selected_key = window._selected
            window.refresh()
            pump()
            assert window._selected == selected_key
            select(4)
            assert 'synthetic-private-value' not in window.preview.get('1.0', 'end-1c')
            select(5)
            assert window._photo and window._photo.width() > 0
            window.meta_button.invoke()
            assert 'SyntheticApp' in window.meta.cget('text')
            window.meta_button.invoke()
            assert window.meta.cget('text') == ''

            samples = []
            for scale in (0.75, 1.0, 1.5):
                with patch.object(window, '_window_scale', return_value=scale):
                    window.refresh_style()
                    pump()
                    for width in (320, 660, 960):
                        window.win.geometry('%dx%d' % (round(width * scale), round(430 * scale)))
                        pump()
                        bounds = window.win.winfo_rootx(), window.win.winfo_rooty(), window.win.winfo_width(), window.win.winfo_height()
                        for button in (window.close_button, window.locate_button):
                            assert button.winfo_ismapped()
                            assert button.winfo_rootx() >= bounds[0]
                            assert button.winfo_rootx() + button.winfo_width() <= bounds[0] + bounds[2]
                            assert button.winfo_rooty() + button.winfo_height() <= bounds[1] + bounds[3]
                        if width == 320:
                            assert not window.sidebar.winfo_ismapped()
                            window.preview_button.invoke()
                            pump()
                            assert window.detail.winfo_ismapped()
                            assert not window.list_frame.winfo_ismapped()
                            window.preview_button.invoke()
                            pump()
                            assert window.list_frame.winfo_ismapped()
                        samples.append((scale, width))

            window.query.set('content 79')
            pump(.4)
            assert len(window._rows) == 1 and window._rows[0][0].record['id'] == 'clip-79'
            saved = window.snapshot()
            window.refresh_style()
            pump()
            assert window.snapshot() == saved
            assert app.search.get() == 'unchanged main search'
            window.locate_button.invoke()
            pump()
            assert len(located) == 1 and located[0].record['id'] == 'clip-79'
            assert not window.win.winfo_exists()
            assert data == before_data
            assert app.search.get() == 'unchanged main search'
            restored = WorkbenchWindow(app, state=window.view_state)
            pump()
            assert restored.query.get() == 'content 79'
            assert restored._selected == ('clip', 'clip-79')
            restored.close()
            pump()
            assert not errors, errors
            print('PASS: workbench search/full masked text/image preview/9 scaled layouts/locate/reopen; no data writes')
        finally:
            window.close()
            tasks.shutdown(wait=True)
            root.destroy()
    assert before_hashes == {str(path): digest(path) for path in real_paths}, 'real library changed'


if __name__ == '__main__':
    run()
