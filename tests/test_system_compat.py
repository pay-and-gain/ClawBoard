"""Real legacy image-capture methods must not bypass persistence guards."""
import ast
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TestLegacyImageStorage(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='clawboard-legacy-image-')
        self.directory = Path(self.temp.name)
        self.runtime = SimpleNamespace(NO_SAVE=True)
        namespace = {'runtime': self.runtime, 'BASE_DIR': str(self.directory),
                     'os': __import__('os'), 'now_ms': lambda: 123456789,
                     'uid': lambda: 'new-image',
                     'clip_is_private': lambda: False,
                     'clipboard_has_image': lambda: True,
                     'sound': SimpleNamespace(play_copy=lambda: self.events.append('sound'))}
        tree = ast.parse((ROOT / 'clawboard/system.py').read_text(encoding='utf-8'))
        definition = next(node for node in tree.body
                          if isinstance(node, ast.ClassDef) and node.name == 'SystemMixin')
        module = ast.Module(body=[definition], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), 'clawboard/system.py', 'exec'), namespace)
        self.app = namespace['SystemMixin']()
        self.events = []
        self.app._store = SimpleNamespace(recovery_required=False)
        self.app.data = {'clip': [{'id': 'existing', 'text': 'keep this record'}]}
        self.app.st = {'smart_private': True, 'max_items': 2, 'sound_copy': False}
        self.app.tab = 'clip'
        self.app.next_seq = lambda: 1
        self.app._read_clip_image = lambda: (b'synthetic PNG data', 2, 1)
        self.app._purge_image_files = lambda items: self.events.append('purge')
        self.app.save = lambda later=False: self.events.append('save')
        self.app.render = lambda: self.events.append('render')
        self.app.tip = lambda text: self.events.append('tip')
        self.app.note = lambda text: self.events.append('note')
        self.original = deepcopy(self.app.data)

    def tearDown(self):
        self.temp.cleanup()

    def assert_untouched(self):
        self.assertEqual(self.app.data, self.original)
        self.assertEqual(self.events, [])
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_direct_legacy_store_does_not_even_create_directory_in_no_save(self):
        self.assertFalse(self.app._store_image(b'synthetic PNG data', 2, 1))
        self.assert_untouched()

    def test_indirect_ingest_cannot_bypass_no_save(self):
        self.app._ingest_image()
        self.assert_untouched()

    def test_legacy_dispatch_reports_unsaved_image_without_disk_or_data_changes(self):
        self.assertEqual(self.app._handle_clipboard_change(), 'empty')
        self.assert_untouched()

    def test_no_save_preserves_existing_json_and_image_bytes(self):
        image_directory = self.directory / 'images'
        image_directory.mkdir()
        image = image_directory / 'existing.png'
        image.write_bytes(b'existing image bytes')
        data = self.directory / 'ClawBoard数据.json'
        data.write_bytes(b'{"clip": [{"text": "existing file"}]}')
        original_files = {path.relative_to(self.directory): path.read_bytes()
                          for path in self.directory.rglob('*') if path.is_file()}
        self.app._store_image(b'replacement image bytes', 2, 1)
        current_files = {path.relative_to(self.directory): path.read_bytes()
                         for path in self.directory.rglob('*') if path.is_file()}
        self.assertEqual(current_files, original_files)
        self.assertEqual(self.app.data, self.original)
        self.assertEqual(self.events, [])

    def test_readonly_store_rejects_legacy_image_write(self):
        self.runtime.NO_SAVE = False
        self.app._store.recovery_required = True
        self.assertFalse(self.app._store_image(b'synthetic PNG data', 2, 1))
        self.assert_untouched()

    def test_injected_application_store_is_also_respected(self):
        self.runtime.NO_SAVE = False
        del self.app._store
        self.app.application = SimpleNamespace(store=SimpleNamespace(recovery_required=True))
        self.assertFalse(self.app._store_image(b'synthetic PNG data', 2, 1))
        self.assert_untouched()

    def test_writable_non_test_compatibility_capture_remains_functional(self):
        self.runtime.NO_SAVE = False
        png = b'synthetic PNG data'
        self.assertTrue(self.app._store_image(png, 2, 1, quiet=True))
        item = self.app.data['clip'][0]
        self.assertEqual(item['content_type'], 'image')
        self.assertEqual((item['image_w'], item['image_h']), (2, 1))
        self.assertEqual((self.directory / 'images' / item['image_path']).read_bytes(), png)
        self.assertEqual(self.events, ['save', 'render'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
