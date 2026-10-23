"""Paste ordering, owner-thread UI delivery and passive privacy regressions."""
import ast
import pathlib
import sys
import threading
import time
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clawboard import runtime
from clawboard.classify import preview, human_size
from clawboard.dispatch import EventDispatcher
from clawboard.history import HistoryService
from clawboard.paste_adapter import PasteBackend, PasteMixin, PasteRequest
from clawboard.privacy import display_text
from clawboard.timefmt import full_time


def backend(**changes):
    values = dict(write_text=lambda text: True, write_files=lambda paths: True,
                  looks_files=lambda text: False, write_image=lambda data: True,
                  read_image=lambda name: b'png', decode_image=lambda raw: (b'dib', 1, 1),
                  can_message=lambda target: True, message=lambda target: True,
                  activate=lambda target, **kwargs: True, send_keys=lambda: None,
                  sequence=lambda: 5, sleep=lambda seconds: None)
    values.update(changes)
    return PasteBackend(**values)


class BackendTests(unittest.TestCase):
    def test_text_copy_keeps_raw_content_and_only_trims_edges(self):
        written = []
        result = backend(write_text=lambda text: written.append(text) or True).perform(
            PasteRequest(1, text=' \n  code\n    indent  \n'))
        self.assertEqual(written, ['code\n    indent'])
        self.assertTrue(result.copied)
        self.assertFalse(result.pasted)
        self.assertEqual(result.sequence, 5)

    def test_files_probe_and_write_happen_inside_backend(self):
        calls = []
        result = backend(looks_files=lambda text: calls.append('probe') or True,
                         write_files=lambda paths: calls.append(paths) or True).perform(
            PasteRequest(1, text=' C:\\a.txt\n  C:\\b.txt  '))
        self.assertTrue(result.copied)
        self.assertEqual(calls, ['probe', ['C:\\a.txt', 'C:\\b.txt']])

    def test_plain_paste_cannot_be_reinterpreted_as_file_drop(self):
        calls = []
        result = backend(looks_files=lambda text: self.fail('plain paste probes files'),
                         write_text=lambda text: calls.append(text) or True).perform(
            PasteRequest(1, text='<p>C:\\a.txt</p>', plain=True))
        self.assertTrue(result.copied)
        self.assertEqual(calls, ['C:\\a.txt'])

    def test_image_decode_and_write_order(self):
        calls = []
        result = backend(read_image=lambda name: calls.append('read') or b'png',
                         decode_image=lambda raw: (calls.append('decode') or b'dib', 1, 1),
                         write_image=lambda dib: calls.append('write') or True).perform(
            PasteRequest(1, image_name='a.png'))
        self.assertTrue(result.copied)
        self.assertEqual(calls, ['read', 'decode', 'write'])

    def test_missing_image_does_not_write_clipboard(self):
        def missing(name):
            raise FileNotFoundError(name)
        result = backend(read_image=missing,
                         write_image=lambda dib: self.fail('writing a missing image')).perform(
            PasteRequest(1, image_name='missing.png'))
        self.assertFalse(result.copied)
        self.assertIn('丢失', result.error)

    def test_failed_write_never_pastes(self):
        result = backend(write_text=lambda text: False,
                         message=lambda target: self.fail('pasted after write failure')).perform(
            PasteRequest(1, text='hello', target=10, should_paste=True))
        self.assertFalse(result.copied)
        self.assertFalse(result.pasted)

    def test_focus_failure_has_copy_only_fallback(self):
        result = backend(can_message=lambda target: False,
                         activate=lambda target, **kw: False,
                         send_keys=lambda: self.fail('sending keys without focus')).perform(
            PasteRequest(1, text='hello', target=10, should_paste=True))
        self.assertTrue(result.copied)
        self.assertFalse(result.pasted)
        self.assertIn('手动', result.error)

    def test_cancelled_request_never_writes(self):
        stopped = threading.Event()
        stopped.set()
        result = backend(write_text=lambda text: self.fail('cancelled request wrote')).perform(
            PasteRequest(1, text='hello'), cancelled=stopped)
        self.assertFalse(result.copied)


class FakeApp(PasteMixin):
    def __init__(self, native, overlap=False):
        self.owner = threading.get_ident()
        self.events = []
        self.data = {'clip': [{'id': 'a', 'text': 'one'}, {'id': 'b', 'text': 'two'}]}
        self.st = {'autopaste': True, 'trim_paste': True, 'sound_paste': False}
        self.hidden = False
        self.prev_hwnd = 10
        self.overlap = overlap
        self._paste_backend = native
        self.application = types.SimpleNamespace(dispatcher=EventDispatcher(),
            reset_clipboard=lambda sequence: self.record('ack', sequence))
        self.root = types.SimpleNamespace(attributes=lambda *args: self.record('topmost', args))
        self.vlist = types.SimpleNamespace(flash=lambda cid: self.record('flash', cid))

    def record(self, name, value=None):
        if threading.get_ident() != self.owner:
            raise AssertionError('UI operation ran on worker')
        self.events.append((name, value))

    def find_raw_item(self, cid):
        return next((item for item in self.data['clip'] if item['id'] == cid), None)

    def _panel_overlaps(self, hwnd):
        return self.overlap

    def sync_topmost(self):
        self.record('restore')

    def save(self, later=False):
        self.record('save')

    def tip(self, text):
        self.record('tip', text)

    def wait(self):
        deadline = time.monotonic() + 3
        while self._paste_tasks.pending and time.monotonic() < deadline:
            self.application.dispatcher.drain()
            time.sleep(0.002)
        self.application.dispatcher.drain()
        if self._paste_tasks.pending:
            raise AssertionError('paste queue did not finish')


class PasteQueueTests(unittest.TestCase):
    def test_serial_queue_preserves_payload_and_main_thread_completion(self):
        owner = threading.get_ident()
        state = {'text': None, 'seq': 1}
        operations = []
        def write(text):
            self.assertNotEqual(threading.get_ident(), owner)
            state['text'] = text
            state['seq'] += 1
            operations.append(('write', text))
            return True
        def paste(target):
            operations.append(('paste', state['text']))
            return True
        app = FakeApp(backend(write_text=write, message=paste, sequence=lambda: state['seq']))
        try:
            self.assertTrue(app.paste('one', cid='a'))
            self.assertTrue(app.paste('two', cid='b'))
            app.wait()
            self.assertEqual(operations, [('write', 'one'), ('paste', 'one'),
                                          ('write', 'two'), ('paste', 'two')])
            self.assertEqual([event for event in app.events if event[0] == 'ack'],
                             [('ack', 2), ('ack', 3)])
            self.assertEqual([item['use_count'] for item in app.data['clip']], [1, 1])
            self.assertEqual(list(app.application.dispatcher.errors), [])
        finally:
            app.close_paste()

    def test_foreground_yield_is_ui_callback_and_always_restored(self):
        app = FakeApp(backend(can_message=lambda target: False), overlap=True)
        try:
            app.paste('one', cid='a')
            app.wait()
            self.assertIn(('topmost', ('-topmost', False)), app.events)
            self.assertIn(('restore', None), app.events)
            self.assertFalse(app._topmost_yield)
            self.assertEqual(list(app.application.dispatcher.errors), [])
        finally:
            app.close_paste()

    def test_failed_copy_does_not_increment_use_count(self):
        app = FakeApp(backend(write_text=lambda text: False))
        try:
            app.paste('one', cid='a')
            app.wait()
            self.assertNotIn('use_count', app.data['clip'][0])
            self.assertFalse(any(event[0] == 'flash' for event in app.events))
            self.assertTrue(any(event[0] == 'tip' for event in app.events))
        finally:
            app.close_paste()

    def test_queue_is_bounded_and_close_cancels_backlog(self):
        entered, release = threading.Event(), threading.Event()
        writes = []
        def write(text):
            entered.set()
            release.wait(2)
            writes.append(text)
            return True
        app = FakeApp(backend(write_text=write))
        try:
            for n in range(4):
                self.assertTrue(app.paste(str(n)))
            self.assertTrue(entered.wait(1))
            self.assertFalse(app.paste('overflow'))
            app.close_paste()
            self.assertFalse(app.paste('after-close'))
        finally:
            release.set()
            app.close_paste()

    def test_expired_focus_gate_cannot_change_window(self):
        app = FakeApp(backend(), overlap=True)
        try:
            app._ensure_paste()
            expired = threading.Event()
            expired.set()
            allowed = [False]
            app._begin_paste_focus(1, expired, allowed)
            self.assertFalse(allowed[0])
            self.assertEqual(app.events, [])
        finally:
            app.close_paste()


def method(name, parent='InteractionMixin', **namespace):
    tree = ast.parse((ROOT / 'clawboard/app_interact.py').read_text(encoding='utf-8'))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == parent)
    function = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name)
    compiled = ast.Module(body=[function], type_ignores=[])
    exec(compile(ast.fix_missing_locations(compiled), '<interaction-regression>', 'exec'), namespace)
    return namespace[name]


class PassivePrivacyTests(unittest.TestCase):
    def test_toast_masks_before_truncation(self):
        seen = []
        show = method('show_copy_toast', display_text=display_text, preview=preview,
                      CopyToast=lambda app, lines, chars, text, ms: seen.append(text))
        app = types.SimpleNamespace(st={'mask_sensitive': True, 'toast_ms': 1})
        show(app, 'password=very_long_secret_value_12345')
        self.assertEqual(len(seen), 1)
        self.assertNotIn('very_long_secret_value', seen[0])

    def test_text_preview_masks_raw_but_explicit_reveal_is_honored(self):
        seen = []
        show = method('_preview_now', display_text=display_text,
                      ContentPreview=lambda app, text, kind, meta: seen.append(text))
        item = {'text': 'password=secret_value_12345', 'sens': ['密码']}
        app = types.SimpleNamespace(st={'mask_sensitive': True}, close_preview=lambda: None,
                                    current_target_text=lambda: (item['text'], item))
        show(app)
        self.assertNotIn('secret_value', seen[0])
        item['mask_off'] = True
        show(app)
        self.assertEqual(seen[-1], item['text'])

    def test_detail_masks_by_default(self):
        seen = []
        class Dialog:
            def __init__(self, root, title, fields, **kwargs):
                seen.append(fields[0][1])
            def show(self, *args):
                pass
        show = method('show_detail', display_text=display_text, preview=preview,
                      human_size=human_size, full_time=full_time, Dialog=Dialog)
        show(types.SimpleNamespace(root=None, st={'mask_sensitive': True}),
             {'text': 'password=secret_value_12345',
              'source_title': 'password=window_title_secret_value'})
        self.assertNotIn('secret_value', seen[0])
        self.assertNotIn('window_title_secret', seen[0])

    def test_no_save_never_registers_image_cleanup(self):
        seen = []
        purge = method('_purge_image_files', runtime=runtime)
        app = types.SimpleNamespace(application=types.SimpleNamespace(
            queue_image_cleanup=lambda names: seen.extend(names)))
        before = runtime.NO_SAVE
        runtime.NO_SAVE = True
        try:
            purge(app, [{'content_type': 'image', 'image_path': 'existing.png'}])
        finally:
            runtime.NO_SAVE = before
        self.assertEqual(seen, [])

    def test_phrase_edit_invalidates_derived_metadata(self):
        item = {'id': 'a', 'text': 'old', 'tags': ['url'], 'sens': ['密码'], 'kind_auto': 'url'}
        class Dialog:
            def __init__(self, root, title, fields, on_ok=None):
                self.on_ok = on_ok
            def show(self, *args):
                self.on_ok(['{"x":1}', 'new-trigger'])
        edit = method('edit_phrase', parent='PhraseMixin', Dialog=Dialog)
        history = HistoryService({'clip': []})
        app = types.SimpleNamespace(root=None, find=lambda cid, kind: item,
             application=types.SimpleNamespace(history=history), save=lambda later: None,
             render=lambda: None)
        edit(app, 'a')
        self.assertEqual(item['kind_auto'], 'json')
        self.assertEqual(item['tags'], ['json'])
        self.assertNotIn('sens', item)
        self.assertEqual(item['trigger'], 'new-trigger')

    def test_image_preview_load_is_queued_and_stale_selection_is_ignored(self):
        submitted, shown = [], []
        submit = lambda fn, *args, **kwargs: submitted.append((fn, args, kwargs))
        show = method('_preview_now')
        ready = method('_show_image_preview',
                       ImagePreview=lambda app, **kwargs: shown.append(kwargs))
        item = {'id': 'a', 'text': '[图片]', 'image_path': 'a.png',
                'image_w': 1920, 'image_h': 1080}
        selected = [item]
        app = types.SimpleNamespace(hidden=False, collapsed=False, tab='clip',
            st={'show_preview': True}, close_preview=lambda: None,
            current_target_text=lambda: (selected[0]['text'], selected[0]),
            _thumbnail_cache=types.SimpleNamespace(get=lambda name: self.fail('UI loaded image')),
            application=types.SimpleNamespace(closed=False, tasks=types.SimpleNamespace(submit=submit)))
        app._show_image_preview = types.MethodType(ready, app)
        show(app)
        self.assertEqual(submitted[0][1], ('a.png',))
        self.assertEqual(submitted[0][2]['key'], 'image-preview')
        selected[0] = {'id': 'b', 'text': 'other'}
        submitted[0][2]['on_result'](b'png')
        self.assertEqual(shown, [])
        selected[0] = item
        submitted[0][2]['on_result'](b'png')
        self.assertEqual(shown, [{'meta': '1920×1080', 'data': b'png'}])

    def test_close_preview_cancels_debounce_and_invalidates_background_result(self):
        seen = []
        close = method('close_preview')
        app = types.SimpleNamespace(_pv_job='timer',
            root=types.SimpleNamespace(after_cancel=lambda value: seen.append(('cancel', value))),
            application=types.SimpleNamespace(tasks=types.SimpleNamespace(
                invalidate=lambda key: seen.append(('invalidate', key)))),
            _preview=types.SimpleNamespace(close=lambda: seen.append(('close', None))))
        close(app)
        self.assertEqual(seen, [('cancel', 'timer'), ('invalidate', 'image-preview'), ('close', None)])
        self.assertIsNone(app._pv_job)
        self.assertIsNone(app._preview)


if __name__ == '__main__':
    unittest.main(verbosity=2)
