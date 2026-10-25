"""Dialog/service regression with pure formatters and AST-loaded UI adapters.

No App/Tk root is constructed. File tests use only TemporaryDirectory; fake
widgets assert that completion delivery runs on the owner thread.
"""
import ast
import csv
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clawboard import exports
from clawboard.dispatch import EventDispatcher
from clawboard.history import HistoryService
from clawboard.tasks import WorkerTasks


def adapter_class(filename, name, namespace):
    tree = ast.parse((ROOT / 'clawboard' / filename).read_text(encoding='utf-8'))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)
    namespace.setdefault('tk', types.SimpleNamespace(TclError=RuntimeError))
    namespace.setdefault('T', {'fg': '#111', 'fg2': '#777', 'danger': '#f00'})
    namespace.setdefault('safe_release', lambda widget: None)
    code = ast.Module(body=[cls], type_ignores=[])
    exec(compile(ast.fix_missing_locations(code), str(ROOT / 'clawboard' / filename), 'exec'), namespace)
    return namespace[name]


class FakeWidget:
    def __init__(self, value=''):
        self.value = value
        self.options = {}
        self.owner = threading.get_ident()
        self.exists = True
        self.calls = 0

    def assert_owner(self):
        if threading.get_ident() != self.owner:
            raise AssertionError('worker touched a widget')

    def configure(self, **values):
        self.assert_owner()
        self.options.update(values)
        self.calls += 1

    def get(self, *args):
        self.assert_owner()
        return self.value

    def delete(self, *args):
        self.assert_owner()
        self.value = ''
        self.calls += 1

    def insert(self, index, value):
        self.assert_owner()
        self.value += value
        self.calls += 1

    def winfo_exists(self):
        self.assert_owner()
        return self.exists

    def destroy(self):
        self.assert_owner()
        self.exists = False

    def after(self, *args):
        raise AssertionError('worker must not schedule Tk callbacks')


class ExportServiceTests(unittest.TestCase):
    def setUp(self):
        self.items = [{'id': 'i', 'text': '中文\nline,"quoted"', 'created_at': 1700000000000,
                       'source_app': 'editor', 'content_type': 'text', 'content_size': 24,
                       'extension': {'keep': True}}]
        self.directory = tempfile.TemporaryDirectory(prefix='clawboard-export-test-')
        self.addCleanup(self.directory.cleanup)

    def test_csv_bom_and_quoted_newline_representation(self):
        data = exports.render_items(self.items, 'csv')
        self.assertTrue(data.startswith(b'\xef\xbb\xbf'))
        rows = list(csv.reader(io.StringIO(data.decode('utf-8-sig'))))
        self.assertEqual(rows[0], ['时间(本地)', '来源应用', '类型', '大小(字节)', '内容'])
        self.assertEqual(rows[1][-1], self.items[0]['text'].replace('\n', '\\n'))

    def test_json_keeps_complete_metadata_and_full_content(self):
        self.items[0]['text'] = 'large-' * 100001
        payload = json.loads(exports.render_items(self.items, 'json'))
        self.assertEqual(payload['items'], self.items)

    def test_markdown_embedded_fences_stay_inside_content(self):
        self.items[0]['text'] = '```python\nprint(1)\n```'
        text = exports.render_items(self.items, 'md', now=1700000000).decode()
        self.assertIn('````\n```python\nprint(1)\n```\n````', text)

    def test_plain_text_keeps_old_layout(self):
        text = exports.render_items(self.items, 'txt').decode()
        self.assertTrue(text.startswith('[1] '))
        self.assertIn(' | editor | text\n' + self.items[0]['text'] + '\n', text)

    def test_atomic_export_failure_preserves_original(self):
        target = Path(self.directory.name) / 'history.json'
        target.write_text('original', encoding='utf-8')
        with patch('clawboard.exports.os.replace', side_effect=PermissionError('synthetic denied')):
            with self.assertRaises(PermissionError):
                exports.write_items(target, self.items, 'json')
        self.assertEqual(target.read_text(encoding='utf-8'), 'original')
        self.assertEqual(list(target.parent.iterdir()), [target])

    def test_cancellation_removes_partial_file(self):
        target = Path(self.directory.name) / 'history.json'
        counter = [0]

        def cancelled():
            counter[0] += 1
            return counter[0] >= 3

        with self.assertRaises(exports.ExportCancelled):
            exports.write_items(target, self.items, 'json', cancelled=cancelled)
        self.assertEqual(list(target.parent.iterdir()), [])

    def test_payload_and_destination_are_injected(self):
        target = Path(self.directory.name) / 'all.json'
        payload = {'clip': self.items, 'groups': [], 'app': 'test'}
        self.assertEqual(exports.write_payload(target, payload), target)
        self.assertEqual(json.loads(target.read_text(encoding='utf-8')), payload)

    def test_export_names_are_distinct_even_in_same_second(self):
        first = exports.new_export_path(self.directory.name, 'csv', now=1700000000)
        second = exports.new_export_path(self.directory.name, 'csv', now=1700000000)
        self.assertNotEqual(first, second)
        self.assertEqual(first.suffix, '.csv')


class TransformAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tips, self.copies, self.ingested = [], [], []
        self.dispatcher = EventDispatcher()
        self.tasks = WorkerTasks(self.dispatcher)
        self.addCleanup(lambda: self.tasks.shutdown(wait=True))
        self.namespace = {'tx': lambda: types.SimpleNamespace(apply=lambda key, source: source.upper()),
                          'clip_write': lambda text: self.copies.append(text) or True}
        cls = adapter_class('transform_dialog.py', 'TransformWindow', self.namespace)
        self.dialog = cls.__new__(cls)
        raw = {'id': 'i', 'text': 'old', 'created_at': 1700000000000,
               'kind_auto': 'text', 'tags': ['phone'], 'sens': ['手机号']}
        history = HistoryService({'clip': [raw]})
        self.app = types.SimpleNamespace(
            application=types.SimpleNamespace(tasks=self.tasks, history=history),
            tip=self.tips.append, tab='clip',
            ingest=lambda text, **kwargs: self.ingested.append((text, kwargs)) or True,
            find_raw_item=lambda identifier: raw if identifier == 'i' else None,
            save=lambda later=False: None, render=lambda: None)
        self.dialog.app = self.app
        self.dialog.win = FakeWidget()
        self.dialog.src = FakeWidget('source')
        self.dialog.out = FakeWidget()
        self.dialog.result_status = FakeWidget()
        self.dialog.lb = types.SimpleNamespace(curselection=lambda: (0,))
        self.dialog._keys = ['upper']
        self.dialog._task_key = ('transform', id(self.dialog))
        self.dialog._closed = self.dialog._pending = self.dialog._ready = self.dialog._truncated = False
        self.dialog._full_result = None
        self.dialog._source_text = 'source'
        self.dialog._source_truncated = False
        self.dialog.item = {'id': 'i'}
        self.raw = raw

    def drain(self):
        deadline = time.monotonic() + 2
        while self.tasks.pending and time.monotonic() < deadline:
            self.dispatcher.drain()
            time.sleep(.001)
        self.assertEqual(self.tasks.pending, 0)

    def test_full_large_result_is_copied_not_truncated_preview(self):
        result = 'full-' * 120001
        self.dialog._show(result, None)
        self.assertEqual(len(self.dialog.out.value), 500000)
        self.assertEqual(self.dialog.out.options['state'], 'disabled')
        self.assertIn('预览已截断', self.dialog.result_status.options['text'])
        self.dialog.copy_out()
        self.assertEqual(self.copies, [result])
        self.dialog.save_new()
        self.assertEqual(self.ingested, [(result, {'manual': True})])

    def test_small_successful_preview_keeps_manual_edits(self):
        self.dialog._show('original result', None)
        self.dialog.out.value = 'edited by user'
        self.dialog.copy_out()
        self.assertEqual(self.copies, ['edited by user'])

    def test_error_and_pending_messages_cannot_be_saved(self):
        self.dialog._show('', 'synthetic error')
        self.dialog.copy_out()
        self.dialog.save_new()
        self.dialog._pending = True
        self.dialog.out.value = '后台处理中…'
        self.dialog.overwrite()
        self.assertEqual(self.copies, [])
        self.assertEqual(self.ingested, [])
        self.assertEqual(self.raw['text'], 'old')

    def test_overwrite_recomputes_all_metadata_and_preserves_created_time(self):
        self.dialog._show('{"a":1}', None)
        self.dialog.overwrite()
        self.assertEqual(self.raw['text'], '{"a":1}')
        self.assertEqual(self.raw['kind_auto'], 'json')
        self.assertEqual(self.raw['tags'], ['json'])
        self.assertNotIn('sens', self.raw)
        self.assertEqual(self.raw['created_at'], 1700000000000)

    def test_even_small_transform_runs_in_worker(self):
        owner = threading.get_ident()
        worker_threads = []
        self.namespace['tx'] = lambda: types.SimpleNamespace(
            apply=lambda key, source: worker_threads.append(threading.get_ident()) or source.upper())
        self.dialog.run()
        self.dialog.copy_out()
        self.assertEqual(self.copies, [])
        self.drain()
        self.assertTrue(worker_threads)
        self.assertNotEqual(worker_threads[0], owner)
        self.assertEqual(self.dialog.out.value, 'SOURCE')

    def test_closed_dialog_discards_worker_completion_without_widget_access(self):
        gate = threading.Event()
        self.namespace['tx'] = lambda: types.SimpleNamespace(apply=lambda key, source: gate.wait(1) or 'done')
        self.dialog.run()
        self.dialog.close()
        calls = self.dialog.out.calls
        gate.set()
        self.drain()
        self.assertEqual(self.dialog.out.calls, calls)

    def test_truncated_source_transform_uses_complete_source(self):
        self.dialog._source_text = 'input-' * 40000
        self.dialog._source_truncated = True
        self.dialog.src.value = 'short visible preview'
        self.dialog.run()
        self.drain()
        self.assertEqual(self.dialog._out_text(), self.dialog._source_text.upper())

    def test_newer_selection_discards_older_worker_result(self):
        gate = threading.Event()

        def apply(key, source):
            if source == 'old':
                gate.wait(1)
            return source.upper()

        self.namespace['tx'] = lambda: types.SimpleNamespace(apply=apply)
        self.dialog.src.value = 'old'
        self.dialog.run()
        self.dialog.src.value = 'new'
        self.dialog.run()
        deadline = time.monotonic() + 1
        while self.dialog._pending and time.monotonic() < deadline:
            self.dispatcher.drain()
            time.sleep(.001)
        self.assertEqual(self.dialog.out.value, 'NEW')
        gate.set()
        self.drain()
        self.assertEqual(self.dialog.out.value, 'NEW')


class SafetyAndCompatibilityTests(unittest.TestCase):
    def test_wipe_no_save_guard_prevents_confirmation_and_all_side_effects(self):
        runtime = types.SimpleNamespace(NO_SAVE=True)
        cls = adapter_class('settings_dialog.py', 'SettingsWindow', {'runtime': runtime})
        instance = cls.__new__(cls)
        messages = []
        instance.app = types.SimpleNamespace(tip=messages.append,
            confirm=lambda *args: self.fail('NO_SAVE must not launch a destructive confirmation'))
        instance.wipe_all()
        self.assertTrue(messages)

    def test_wipe_rechecks_no_save_after_confirmation(self):
        runtime = types.SimpleNamespace(NO_SAVE=False)
        cls = adapter_class('settings_dialog.py', 'SettingsWindow', {'runtime': runtime})
        instance = cls.__new__(cls)
        callbacks, messages = [], []
        instance.app = types.SimpleNamespace(tip=messages.append,
            confirm=lambda text, callback: callbacks.append(callback))
        instance.wipe_all()
        runtime.NO_SAVE = True
        callbacks[0]()
        self.assertTrue(messages)

    def test_listen_switch_uses_the_single_system_entrypoint(self):
        widgets = []

        class RowWidget(FakeWidget):
            def __init__(self, *args, **kwargs):
                super().__init__()
                self.options.update(kwargs)
                self.bindings = {}
                widgets.append(self)

            def pack(self, *args, **kwargs):
                pass

            def bind(self, event, callback):
                self.bindings[event] = callback

        namespace = {'tk': types.SimpleNamespace(Frame=RowWidget, Label=RowWidget, Button=RowWidget),
                     'FONT': (), 'FONT_B': (),
                     'T': {'bg': '', 'fg': '', 'fg2': '', 'acc': '', 'card': '', 'card_h': '', 'line': ''}}
        cls = adapter_class('settings_dialog.py', 'SettingsWindow', namespace)
        instance = cls.__new__(cls)
        state, calls = {'listen': True}, []

        def toggle():
            calls.append('toggle_listen')
            state['listen'] = not state['listen']

        instance.app = types.SimpleNamespace(st=state, toggle_listen=toggle,
            save=lambda *args: self.fail('system entrypoint already saves'))
        instance.row_switch(None, 'listen', 'listen')
        instance._switches['listen'].options['command']()
        self.assertEqual(calls, ['toggle_listen'])
        self.assertFalse(state['listen'])

    def test_legacy_dialog_module_monkeypatch_forwards_to_adapters(self):
        script = '''
import sys, types
sys.path.insert(0, %r)
win32 = types.ModuleType('clawboard.win32')
win32.get_autostart = lambda: (False, '')
win32.set_autostart = lambda value: True
clipboard = types.ModuleType('clawboard.clipboard')
clipboard.clip_write = lambda text: True
widgets = types.ModuleType('clawboard.widgets')
for name in ('ScrollFrame','ThinBar','dark_top','center_on','safe_release'):
    setattr(widgets, name, lambda *args, **kwargs: None)
sys.modules['clawboard.win32'] = win32
sys.modules['clawboard.clipboard'] = clipboard
sys.modules['clawboard.widgets'] = widgets
import clawboard.dialogs as D
from clawboard import settings_dialog, transform_dialog, export_dialog
from unittest.mock import patch
original = D.tx
temporary = lambda: 'patched'
with patch('clawboard.dialogs.tx', temporary):
    assert D.tx is temporary and transform_dialog.tx is temporary
assert D.tx is original and transform_dialog.tx is original
replacement = lambda: None
D.tx = replacement
assert transform_dialog.tx is replacement
D.clip_write = replacement
assert transform_dialog.clip_write is replacement
D.BASE_DIR = '/synthetic/injected/path'
assert settings_dialog.BASE_DIR == D.BASE_DIR == export_dialog.BASE_DIR
D.DATA_FILE = '/synthetic/injected/data.json'
assert settings_dialog.DATA_FILE == D.DATA_FILE
assert D.SettingsWindow is settings_dialog.SettingsWindow
''' % str(ROOT)
        subprocess.run([sys.executable, '-c', script], check=True, capture_output=True, text=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
