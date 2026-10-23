# -*- coding: utf-8 -*-
"""模型/存储边界回归；只操作临时目录，不创建 App 或调用 Windows API。"""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clawboard.config import DEFAULT_SETTINGS, SCHEMA_VERSION
from clawboard.models import default_data, normalize_data, normalize_item
from clawboard.storage import JsonStore, RecoveryRequiredError, StorageError


class ModelTests(unittest.TestCase):
    def test_defaults_are_independent(self):
        first, second = default_data(), default_data()
        first['settings']['listen'] = False
        first['groups'][0]['items'].append({'text': 'example'})
        self.assertTrue(second['settings']['listen'])
        self.assertEqual(second['groups'][0]['items'], [])

    def test_c_enum_types_are_searchable_strings(self):
        import query
        for value, expected in enumerate(('text', 'url', 'json', 'multiline')):
            with self.subTest(value=value):
                item = normalize_item({'id': 2, 'text': 'example', 'content_type': value}, 1)
                self.assertEqual(item['content_type'], expected)
                self.assertEqual(item['id'], '2')
                self.assertEqual(len(query.match('type:' + expected, [item])[0]), 1)

    def test_bad_known_fields_are_repaired(self):
        item = normalize_item({'text': 'example', 'created_at': 'bad', 'copy_count': None,
                               'source_app': 4, 'seq': {}, 'content_size': -8,
                               'sens': ['密码', 1], 'tags': 'bad'}, 3)
        self.assertEqual(item['seq'], 3)
        self.assertEqual(item['copy_count'], 1)
        self.assertEqual(item['source_app'], 'unknown')
        self.assertEqual(item['content_size'], 7)
        self.assertEqual(item['sens'], ['密码'])
        self.assertEqual(item['tags'], [])
        self.assertEqual(item['is_estimated'], 1)

    def test_unknown_fields_survive_normalization(self):
        raw = {'vendor': {'revision': 4}, 'clip': [{'text': 'example', 'extra': [1]}],
               'settings': {'theme': 'light', 'future_option': {'x': True}},
               'groups': [{'name': 'test', 'extra_group': 9, 'items': []}]}
        normalized = normalize_data(copy.deepcopy(raw))
        self.assertEqual(normalized['vendor'], raw['vendor'])
        self.assertEqual(normalized['clip'][0]['extra'], [1])
        self.assertEqual(normalized['settings']['future_option'], {'x': True})
        self.assertEqual(normalized['groups'][0]['extra_group'], 9)

    def test_future_schema_is_not_downgraded(self):
        self.assertEqual(normalize_data({'schema_version': 99})['schema_version'], 99)

    def test_invalid_collections_and_settings(self):
        data = normalize_data({'clip': {}, 'groups': [{'name': 'test', 'items': None}],
                               'settings': {'max_items': True, 'theme': 'invalid'}, 'gi': 'bad'})
        self.assertEqual(data['clip'], [])
        self.assertEqual(data['groups'][0]['items'], [])
        self.assertEqual(data['settings']['max_items'], DEFAULT_SETTINGS['max_items'])
        self.assertEqual(data['settings']['theme'], DEFAULT_SETTINGS['theme'])
        self.assertEqual(data['gi'], 0)

    def test_invalid_items_are_dropped(self):
        data = normalize_data({'clip': [None, {'text': 1}, {'text': 'valid'}]})
        self.assertEqual(len(data['clip']), 1)
        self.assertEqual(data['clip'][0]['text'], 'valid')

    def test_valid_timestamps_are_preserved(self):
        raw = {'text': 'example', 'created_at': 1700000000000, 'updated_at': 1700000000001,
               'last_used_at': 1700000000002, 'id': 'stable'}
        item = normalize_item(raw, 1)
        self.assertEqual(item['created_at'], 1700000000000)
        self.assertEqual(item['updated_at'], 1700000000001)
        self.assertEqual(item['last_used_at'], 1700000000002)
        self.assertEqual(item['id'], 'stable')

    def test_invalid_optional_timestamp_and_explicit_null(self):
        item = normalize_item({'text': 'example', 'updated_at': None, 'last_used_at': 'bad'}, 1)
        self.assertIsNone(item['updated_at'])
        self.assertIsNone(item['last_used_at'])


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='clawboard-storage-test-')
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'ClawBoard数据.json'
        self.store = JsonStore(self.path)

    def test_missing_file_does_not_write_during_load(self):
        result = self.store.load()
        self.assertFalse(result.recovery_required)
        self.assertFalse(result.migrated)
        self.assertEqual(result.data['schema_version'], SCHEMA_VERSION)
        self.assertEqual(list(self.path.parent.iterdir()), [])

    def test_corrupt_file_is_protected_until_explicit_recovery(self):
        broken = b'{"clip": [this is invalid JSON'
        self.path.write_bytes(broken)
        result = self.store.load()
        self.assertTrue(result.recovery_required)
        self.assertTrue(result.notices)
        with self.assertRaises(RecoveryRequiredError):
            self.store.save(result.data)
        self.assertEqual(self.path.read_bytes(), broken)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        self.store.recover(result.data)
        self.assertFalse(self.store.recovery_required)
        archived = list(self.path.parent.glob('*.corrupt-*'))
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0].read_bytes(), broken)
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8'))['clip'], [])

    def test_non_object_root_is_protected(self):
        self.path.write_text('[1,2,3]', encoding='utf-8')
        self.assertTrue(self.store.load().recovery_required)
        self.assertEqual(self.path.read_text(encoding='utf-8'), '[1,2,3]')

    def test_migration_is_in_memory_then_backed_up_on_first_save(self):
        legacy = {'clip': [{'text': 'legacy'}], 'groups': []}
        original = json.dumps(legacy)
        self.path.write_text(original, encoding='utf-8')
        loaded = self.store.load()
        self.assertTrue(loaded.migrated)
        self.assertEqual(loaded.data['schema_version'], SCHEMA_VERSION)
        self.assertEqual(self.path.read_text(encoding='utf-8'), original)
        self.assertFalse(Path(str(self.path) + '.bak').exists())
        self.store.save(loaded.data)
        self.assertEqual(Path(str(self.path) + '.bak').read_text(encoding='utf-8'), original)
        self.store.save(loaded.data)
        self.assertFalse(Path(str(self.path) + '.bak.1').exists())

    def test_unknown_fields_round_trip(self):
        raw = default_data()
        raw['extension'] = {'enabled': True}
        raw['settings']['future_option'] = 42
        raw['clip'] = [{'id': 'x', 'text': 'synthetic', 'extra': ['opaque']}]
        self.path.write_text(json.dumps(raw), encoding='utf-8')
        result = self.store.load()
        self.store.save(result.data)
        again = self.store.load().data
        self.assertEqual(again['extension'], {'enabled': True})
        self.assertEqual(again['settings']['future_option'], 42)
        self.assertEqual(again['clip'][0]['extra'], ['opaque'])

    def test_atomic_replace_failure_preserves_original_and_cleans_temp(self):
        original = json.dumps(default_data())
        self.path.write_text(original, encoding='utf-8')
        with patch('clawboard.storage.os.replace', side_effect=PermissionError('synthetic denied')):
            with self.assertRaises(StorageError):
                self.store.save(default_data())
        self.assertEqual(self.path.read_text(encoding='utf-8'), original)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_serialization_failure_preserves_original(self):
        self.path.write_text('{}', encoding='utf-8')
        with self.assertRaises(StorageError):
            self.store.save({'invalid': object()})
        self.assertEqual(self.path.read_text(encoding='utf-8'), '{}')
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_three_backup_generations(self):
        for value in range(4):
            self.path.write_text(str(value), encoding='utf-8')
            self.store.backup()
        self.assertEqual(Path(str(self.path) + '.bak').read_text(encoding='utf-8'), '3')
        self.assertEqual(Path(str(self.path) + '.bak.1').read_text(encoding='utf-8'), '2')
        self.assertEqual(Path(str(self.path) + '.bak.2').read_text(encoding='utf-8'), '1')
        self.assertFalse(Path(str(self.path) + '.bak.3').exists())

    def test_recovery_write_failure_keeps_protection(self):
        self.path.write_text('invalid', encoding='utf-8')
        self.store.load()
        with patch('clawboard.storage.os.replace', side_effect=PermissionError('synthetic denied')):
            with self.assertRaises(StorageError):
                self.store.recover(default_data())
        self.assertTrue(self.store.recovery_required)
        self.assertEqual(self.path.read_text(encoding='utf-8'), 'invalid')

    def test_utf8_bom_is_readable(self):
        self.path.write_text(json.dumps(default_data()), encoding='utf-8-sig')
        self.assertFalse(self.store.load().recovery_required)


if __name__ == '__main__':
    unittest.main(verbosity=2)
