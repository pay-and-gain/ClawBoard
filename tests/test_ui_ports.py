"""Actual UI adapter methods against deterministic ports, without Tk/Win32.

These are integration tests of the real method bodies. AST loading avoids OS
imports; controls, schedulers and background completion order are injected.
"""
import ast
from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import query
from clawboard.history import HistoryService
from clawboard.models import default_data
from clawboard.search import SearchService
from clawboard.viewmodels import ViewProjection


def adapter_class(relative_path, name, namespace=None):
    tree = ast.parse((ROOT / relative_path).read_text(encoding='utf-8'))
    definition = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)
    # Dependencies inherited in the product are supplied as ports below. The
    # tested method bodies themselves remain unchanged.
    definition.bases = []
    module = ast.Module(body=[definition], type_ignores=[])
    globals_ = {} if namespace is None else dict(namespace)
    exec(compile(ast.fix_missing_locations(module), relative_path, 'exec'), globals_)
    return globals_[name]


class Scheduler:
    def __init__(self):
        self.pending = {}
        self.sequence = 0

    def after(self, delay, callback):
        self.sequence += 1
        token = 'timer-%d' % self.sequence
        self.pending[token] = (delay, callback)
        return token

    def after_cancel(self, token):
        self.pending.pop(token, None)


class ManualTasks:
    def __init__(self):
        self.jobs = []
        self.reject = False

    def submit(self, fn, *args, **kwargs):
        if self.reject:
            return None
        self.jobs.append((fn, args, kwargs))
        return object()

    def complete(self, index=0):
        fn, args, options = self.jobs.pop(index)
        try:
            result = fn(*args)
        except Exception as error:
            options['on_error'](error)
        else:
            options['on_result'](result)


class ExitPortsTests(unittest.TestCase):
    def test_failed_quit_preserves_hook_tray_hotkey_and_window(self):
        events = []
        system = adapter_class('clawboard/system.py', 'SystemMixin',
                               {'stop_keyboard_hook': lambda: events.append('stop-hook')})
        app = system()
        app.note = lambda text: events.append('note')
        app.tip = lambda text: events.append('tip')
        app.save = lambda: events.append('save')
        app.hw = SimpleNamespace(unreg_hotkey=lambda: events.append('unregister'),
                                 tray_del=lambda: events.append('delete-tray'),
                                 stop=lambda: events.append('stop-window-thread'))
        app.root = SimpleNamespace(destroy=lambda: events.append('destroy'))
        def fail_close():
            events.append('bridge-close')
            raise OSError('synthetic disk failure')
        app.bridge = SimpleNamespace(close=fail_close)
        app.quit_app()
        self.assertIn('save', events)
        self.assertIn('tip', events)
        for forbidden in ('stop-hook', 'unregister', 'delete-tray', 'stop-window-thread', 'destroy'):
            self.assertNotIn(forbidden, events)

    def test_successful_quit_saves_before_destroying_system_resources(self):
        events = []
        system = adapter_class('clawboard/system.py', 'SystemMixin',
                               {'stop_keyboard_hook': lambda: events.append('stop-hook')})
        app = system()
        app.note = lambda text: None
        app.tip = lambda text: self.fail('successful quit should not report failure')
        app.save = lambda: events.append('save')
        app.bridge = SimpleNamespace(close=lambda: events.append('bridge-close'))
        app.hw = SimpleNamespace(unreg_hotkey=lambda: events.append('unregister'),
                                 tray_del=lambda: events.append('delete-tray'),
                                 stop=lambda: events.append('stop-window-thread'))
        app.root = SimpleNamespace(destroy=lambda: events.append('destroy'))
        app.quit_app()
        self.assertEqual(events, ['save', 'bridge-close', 'stop-hook', 'unregister',
                                  'delete-tray', 'stop-window-thread', 'destroy'])

    def test_final_application_save_failure_does_not_close_paste_or_cancel_pump(self):
        events = []
        bridge_type = adapter_class('clawboard/tk_bridge.py', 'TkApplicationBridge')
        bridge = bridge_type.__new__(bridge_type)
        bridge._closed = False
        bridge._pump_id = 'pump'
        bridge.root = SimpleNamespace(after_cancel=lambda token: events.append('cancel-pump'))
        bridge.app = SimpleNamespace(close_paste=lambda: events.append('close-paste'))
        def fail():
            events.append('application-close')
            raise OSError('synthetic final-save failure')
        bridge.application = SimpleNamespace(flush=lambda: events.append('flush'), close=fail)
        with self.assertRaises(OSError):
            bridge.close()
        self.assertEqual(events, ['flush', 'application-close'])
        self.assertFalse(bridge._closed)
        self.assertEqual(bridge._pump_id, 'pump')


class UiStatePortsTests(unittest.TestCase):
    def setUp(self):
        self.query = ['alpha']
        self.events, self.pasted = [], []
        self.scheduler = Scheduler()
        self.tasks = ManualTasks()
        self.samples = [{'id': 'sample-%d' % index, 'text': 'example', 'seq': index}
                        for index in range(1, 7)]
        ui = adapter_class('clawboard/app_ui.py', 'UiMixin',
                           {'Q': query, 'onboard': SimpleNamespace(sample_items=lambda: deepcopy(self.samples))})
        interaction = adapter_class('clawboard/app_interact.py', 'InteractionMixin')
        combined = type('UiPorts', (ui, interaction), {})
        self.app = combined()
        self.app.data = default_data()
        self.app.data['clip'] = [
            {'id': 'a', 'text': 'alpha selected', 'created_at': 1},
            {'id': 'b', 'text': 'beta result', 'created_at': 2},
            {'id': 'c', 'text': 'alpha newest', 'created_at': 3},
        ]
        self.app.st = self.app.data['settings']
        self.app.search = SimpleNamespace(get=lambda: self.query[0])
        self.app.application = SimpleNamespace(data_revision=0, tasks=self.tasks,
                                               search=SearchService(), history=HistoryService(self.app.data))
        self.app.root = self.scheduler
        self.app.tab = 'clip'
        self.app.sel_clip = 'a'
        self.app.sel_phrase = None
        self.app._filter_result = None
        self.app._filter_pending = None
        self.app._search_job = None
        self.app._projection = ViewProjection()
        self.app._last_view_key = None
        self.app._sync_ph = lambda: None
        self.app.tip = lambda text: self.events.append(('tip', text))
        self.app.note = lambda text: self.events.append(('note', text))
        self.app.paste = lambda *args, **kwargs: self.pasted.append((args, kwargs))
        self.app.vlist = SimpleNamespace(items=[], sel='a', multi=set(), update_view=lambda: None)
        def save(later=False):
            self.app.application.data_revision += 1
            self.events.append(('save', later))
        self.app.save = save
        def render():
            rows, selection, keyword = ui.visible_items(self.app)
            self.app.vlist.items = rows
            self.app._last_view_key = (self.app.tab, self.app.data.get('gi'), self.query[0].strip())
            self.events.append(('render', keyword))
        self.app.render = render

    def ready_alpha(self):
        self.app.render()
        self.assertEqual(len(self.tasks.jobs), 1)
        self.tasks.complete()
        self.assertEqual([item['id'] for item in self.app.vlist.items], ['c', 'a'])

    def test_load_samples_advances_history_authority_past_all_sample_sequences(self):
        self.app.data['clip'] = []
        self.app._seq = 0
        self.app.application.history.sequence = 0
        self.app.load_samples()
        maximum = max(item['seq'] for item in self.app.data['clip'])
        self.assertEqual(self.app._seq, maximum)
        self.assertGreater(self.app.application.history.next_sequence(), maximum)

    def test_late_query_result_cannot_replace_newer_query_or_selection(self):
        self.app.render()
        self.query[0] = 'beta'
        self.app.render()
        self.tasks.complete(0)
        self.assertEqual(self.app.vlist.items, [])
        self.tasks.complete(0)
        self.assertEqual([item['id'] for item in self.app.vlist.items], ['b'])
        self.assertEqual(self.app.sel_clip, 'a')
        self.assertEqual(self.pasted, [])

    def test_late_data_snapshot_is_discarded_after_revision_changes(self):
        self.app.render()
        self.app.data['clip'][0]['text'] = 'changed to gamma'
        self.app.application.data_revision += 1
        self.tasks.complete(0)
        self.assertIsNone(self.app._filter_result)
        self.assertEqual(self.app.vlist.items, [])
        self.tasks.complete(0)
        self.assertEqual([item['id'] for item in self.app.vlist.items], ['c'])

    def test_enter_during_debounce_never_pastes_a_previous_query(self):
        self.ready_alpha()
        self.query[0] = 'beta'
        self.app._search_changed()
        self.assertEqual([item['id'] for item in self.app.vlist.items], ['c', 'a'])
        self.app.on_search_return()
        self.assertEqual(self.pasted, [])
        self.assertTrue(any(kind == 'tip' for kind, _ in self.events))
        self.assertEqual(self.app.vlist.items, [])

    def test_quick_paste_during_debounce_never_uses_previous_rows(self):
        self.ready_alpha()
        self.query[0] = 'beta'
        self.app._search_changed()
        self.app.quick_paste(1)
        self.assertEqual(self.pasted, [])
        self.assertEqual(self.app.vlist.items, [])

    def test_ready_search_preserves_selection_identity_then_records_history(self):
        self.ready_alpha()
        self.app.on_search_return()
        self.assertEqual(len(self.pasted), 1)
        self.assertEqual(self.pasted[0][0], ('alpha selected', True, 'a'))
        self.assertEqual(self.app.data['search_history'], ['alpha'])

    def test_capacity_rejection_keeps_search_retryable_without_old_rows(self):
        self.tasks.reject = True
        self.app.render()
        self.assertIsNone(self.app._filter_pending)
        self.assertEqual(self.app.vlist.items, [])
        self.assertTrue(self.scheduler.pending)
        self.tasks.reject = False
        self.app.render()
        self.tasks.complete()
        self.assertEqual([item['id'] for item in self.app.vlist.items], ['c', 'a'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
