"""Import-source regression; only synthetic temporary files, no App/clipboard."""
from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clawboard import backup_format as F
from clawboard import import_source as I


class ImportSourceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='cb-import-source-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def source(self, data, name='source.json'):
        path = self.root / name
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        return path

    def library(self):
        return {'schema_version': 3, 'clip': [{'id': 'c', 'text': '合成正文', 'future': {'keep': 1}}],
                'groups': [{'name': '合成分组', 'items': [{'id': 'p', 'text': '合成常用语'}]}],
                'settings': {'future': 'must-not-import'},
                'trash': {'version': 1, 'items': []}}

    def package(self, *, extra=False):
        data = self.library()
        data['clip'].append({'id': 'image', 'text': '[合成图片]', 'content_type': 'image',
                             'image_path': 'main.png', 'future': {'image_path': 'nested.png'}})
        images = []
        for name in ('main.png', 'nested.png') + (('orphan.png',) if extra else ()):
            image = self.root / name
            image.write_bytes(('synthetic:' + name).encode())
            images.append((name, image))
        raw = F.json_bytes(data)
        details, _ = F.data_details(raw)
        path = self.root / 'source.zip'
        F.write_package(path, raw, images, details=details, safety=extra)
        return path

    def test_library_records_have_deterministic_keys_and_detached_unknown_fields(self):
        data = self.library()
        path = self.source(data)
        result = I.read_source(path)
        self.assertEqual(result.kind, 'json-library')
        self.assertEqual(result.path, path.absolute())
        self.assertEqual(result.sha256, hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual([entry.key for entry in result.entries], ['c:0', 'g:0:0'])
        clip, phrase = result.entries
        self.assertEqual((clip.section, clip.group_key, clip.group_name), ('clip', '', ''))
        self.assertEqual((phrase.section, phrase.group_key, phrase.group_name),
                         ('phrase', 'g:0', '合成分组'))
        self.assertEqual(clip.item, data['clip'][0])
        clip.item['future']['keep'] = 2
        self.assertEqual(I.read_source(path).entries[0].item['future']['keep'], 1)
        self.assertFalse(result.image_hashes)
        with self.assertRaises(FrozenInstanceError):
            clip.key = 'changed'

    def test_current_and_older_all_export_versions(self):
        for version in ('3.0.0', '2.7.0', '2.6.1'):
            with self.subTest(version=version):
                data = self.library()
                del data['schema_version']
                data.update(app='ClawBoard', version=version, exported_at='synthetic')
                result = I.read_source(self.source(data))
                self.assertEqual(result.kind, 'json-all')
                self.assertEqual(len(result.entries), 2)

    def test_selected_export_becomes_history(self):
        result = I.read_source(self.source({'version': 3, 'items': [{'text': '甲'}, {'text': '乙'}]}))
        self.assertEqual(result.kind, 'json-items')
        self.assertEqual([entry.key for entry in result.entries], ['c:0', 'c:1'])
        self.assertTrue(all(entry.section == 'clip' for entry in result.entries))

    def test_old_library_without_schema_accepted(self):
        result = I.read_source(self.source({'clip': [{'text': 'old C shape', 'content_type': 0}],
                                           'groups': []}))
        self.assertEqual(result.entries[0].item['content_type'], 0)

    def test_empty_library_is_valid_but_settings_and_trash_are_not_entries(self):
        data = self.library()
        data['clip'] = []
        data['groups'] = []
        data['trash']['items'].append({'id': 'trash', 'deleted_at': 1,
                                      'item': {'id': 'r', 'text': 'not an import candidate'}})
        self.assertEqual(I.read_source(self.source(data)).entries, ())

    def test_json_images_are_marked_unavailable_without_reading_neighbor_assets(self):
        path = self.source({'version': 3, 'items': [{'text': 'photo', 'content_type': 'image',
                    'image_path': 'same.png', 'future': {'image_path': 'second.png'}}]})
        (self.root / 'same.png').write_bytes(b'private-neighbor-do-not-read')
        (self.root / 'images').mkdir()
        (self.root / 'images/second.png').write_bytes(b'private-neighbor-do-not-read')
        opened = []
        original = Path.open

        def open_path(path, *args, **kwargs):
            opened.append(path)
            return original(path, *args, **kwargs)

        with patch.object(Path, 'open', open_path):
            result = I.read_source(path)
        self.assertEqual(opened, [path])
        self.assertEqual(result.entries[0].images, ('same.png', 'second.png'))
        self.assertIn('缺少图片', result.entries[0].issue)
        self.assertFalse(result.image_hashes)

    def test_image_without_top_level_path_is_unavailable(self):
        result = I.read_source(self.source({'version': 3, 'items': [
            {'text': 'image', 'content_type': 'image'}]}))
        self.assertTrue(result.entries[0].issue)

    def test_only_nested_image_reference_is_conservatively_preserved(self):
        result = I.read_source(self.source({'version': 3, 'items': [
            {'text': 'text', 'metadata': [{'future': {'image_path': 'nested.png'}}]}]}))
        self.assertEqual(result.entries[0].images, ('nested.png',))
        self.assertTrue(result.entries[0].issue)

    def test_json_does_not_touch_optional_staging(self):
        staging = self.root / 'not-created'
        I.read_source(self.source(self.library()), staging=staging)
        self.assertFalse(staging.exists())

    def test_zip_validation_and_hashes_without_extraction(self):
        path = self.package()
        before = set(self.root.iterdir())
        result = I.read_source(path)
        self.assertEqual(result.kind, 'backup')
        self.assertEqual(result.sha256, hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(len(result.entries), 3)
        image = result.entries[1]
        self.assertEqual(image.images, ('main.png', 'nested.png'))
        self.assertFalse(image.issue)
        self.assertEqual(result.image_hashes['main.png'],
                         hashlib.sha256(b'synthetic:main.png').hexdigest())
        self.assertEqual(set(self.root.iterdir()), before)

    def test_zip_extracts_only_into_fresh_caller_directory(self):
        staging = self.root / 'staging'
        result = I.read_source(self.package(), staging=staging)
        self.assertEqual((staging / 'images/main.png').read_bytes(), b'synthetic:main.png')
        self.assertEqual(set(path.relative_to(staging).as_posix()
                             for path in staging.rglob('*') if path.is_file()),
                         {'data.json', 'images/main.png', 'images/nested.png'})
        self.assertFalse(result.entries[1].issue)

    def test_existing_empty_staging_is_allowed(self):
        staging = self.root / 'staging'
        staging.mkdir()
        I.read_source(self.package(), staging=staging)
        self.assertTrue((staging / 'data.json').is_file())

    def test_nonempty_staging_is_rejected_without_overwrite(self):
        staging = self.root / 'staging'
        staging.mkdir()
        keep = staging / 'data.json'
        keep.write_bytes(b'keep')
        with self.assertRaises(I.ImportError):
            I.read_source(self.package(), staging=staging)
        self.assertEqual(keep.read_bytes(), b'keep')
        self.assertEqual(list(staging.iterdir()), [keep])

    def test_safety_backup_extra_assets_are_hashed_but_not_candidates(self):
        result = I.read_source(self.package(extra=True))
        self.assertEqual(len(result.entries), 3)
        self.assertEqual(set(result.image_hashes), {'main.png', 'nested.png', 'orphan.png'})

    def test_expected_hash_binds_json_and_zip_sources(self):
        for path in (self.source(self.library()), self.package()):
            with self.subTest(suffix=path.suffix):
                expected = hashlib.sha256(path.read_bytes()).hexdigest()
                self.assertEqual(I.read_source(path, expected_sha256=expected.upper()).sha256, expected)
                with self.assertRaises(I.ImportError):
                    I.read_source(path, expected_sha256='0' * 64)

    def test_invalid_expected_hash_is_rejected(self):
        for value in ('x', 1, '', 'g' * 64):
            with self.subTest(value=value), self.assertRaises(I.ImportError):
                I.read_source(self.source(self.library()), expected_sha256=value)

    def test_bad_root_or_ambiguous_format_is_rejected(self):
        for data in ([], None, {}, {'settings': {}},
                     {'version': 3, 'items': [], 'clip': []}):
            with self.subTest(data=data), self.assertRaises(I.ImportError):
                I.read_source(self.source(data))

    def test_future_or_invalid_versions_are_rejected(self):
        cases = [dict(version=value, items=[]) for value in (4, 0, True, '3', None)]
        cases += [dict(schema_version=value, clip=[], groups=[]) for value in (4, 0, True, '3')]
        cases += [dict(app='ClawBoard', version=value, clip=[], groups=[])
                  for value in (str(int(I.APP_VER.split('.')[0]) + 1) + '.0.0',
                                '.'.join(I.APP_VER.split('.')[:2] + [str(int(I.APP_VER.split('.')[2]) + 1)]),
                                '10000000.0', '3.bad', None)]
        cases += [dict(app='Other', version='1.0.0', clip=[], groups=[])]
        for data in cases:
            with self.subTest(data=data), self.assertRaises(I.ImportError):
                I.read_source(self.source(data))

    def test_invalid_lists_groups_and_items_are_not_silently_dropped(self):
        cases = [dict(clip={}, groups=[]), dict(clip=[], groups={}),
                 dict(clip=[{'text': 'valid'}, {'text': None}], groups=[]),
                 dict(clip=[], groups=[None]),
                 dict(clip=[], groups=[{'name': 3, 'items': []}]),
                 dict(clip=[], groups=[{'name': 'ok', 'items': {}}]),
                 dict(clip=[], groups=[{'name': 'ok', 'items': [1]}])]
        for data in cases:
            with self.subTest(data=data), self.assertRaises(I.ImportError):
                I.read_source(self.source(data))

    def test_unsafe_or_bad_image_paths_are_rejected(self):
        for name in ('../escape.png', 'C:/secret.png', 'CON.png', 'trailing. ', 5, True, []):
            data = {'version': 3, 'items': [{'text': 'valid', 'future': {'image_path': name}}]}
            with self.subTest(name=name), self.assertRaises(I.ImportError):
                I.read_source(self.source(data))

    def test_case_insensitive_image_aliases_are_rejected(self):
        data = {'version': 3, 'items': [{'text': 'a', 'image_path': 'Photo.png'},
                                       {'text': 'b', 'image_path': 'photo.png'}]}
        with self.assertRaises(I.ImportError):
            I.read_source(self.source(data))

    def test_entry_and_group_count_limits(self):
        cases = [{'version': 3, 'items': [{'text': 'a'}] * 3},
                 {'clip': [{'text': 'a'}], 'groups': [{'name': 'g', 'items': [{'text': 'b'}] * 2}]},
                 {'clip': [], 'groups': [{'name': 'empty', 'items': []}] * 3}]
        with patch.object(I, 'MAX_IMPORT_ITEMS', 2):
            for data in cases:
                with self.subTest(data=data), self.assertRaises(I.ImportError):
                    I.read_source(self.source(data))

    def test_bounded_json_read(self):
        path = self.source(self.library())
        with patch.object(I, 'MAX_JSON_BYTES', 16), self.assertRaises(I.ImportError):
            I.read_source(path)

    def test_duplicate_json_keys_and_nonfinite_numbers_are_rejected(self):
        path = self.root / 'source.json'
        for raw in (b'{"clip": [], "clip": [], "groups": []}',
                    b'{"clip": [{"text": "x", "future": NaN}], "groups": []}'):
            path.write_bytes(raw)
            with self.subTest(raw=raw), self.assertRaises(I.ImportError):
                I.read_source(path)

    def test_invalid_unicode_is_rejected_before_future_utf8_save(self):
        path = self.root / 'source.json'
        path.write_bytes(b'{"version":3,"items":[{"text":"\\ud800"}]}')
        with self.assertRaises(I.ImportError):
            I.read_source(path)

    def test_corrupt_zip_member_fails_verified_reader(self):
        original = self.package()
        changed = self.root / 'corrupt.zip'
        with zipfile.ZipFile(original) as source:
            members = {name: source.read(name) for name in source.namelist()}
        members['images/main.png'] = b'changed-image'
        with zipfile.ZipFile(changed, 'w') as target:
            for name, raw in members.items():
                target.writestr(name, raw)
        with self.assertRaises(I.ImportError):
            I.read_source(changed)

    def test_future_application_version_in_zip_is_rejected(self):
        original = self.package()
        changed = self.root / 'future.zip'
        with zipfile.ZipFile(original) as source:
            members = {name: source.read(name) for name in source.namelist()}
        manifest = json.loads(members['manifest.json'])
        manifest['app_version'] = str(int(I.APP_VER.split('.')[0]) + 1) + '.0.0'
        members['manifest.json'] = F.json_bytes(manifest)
        with zipfile.ZipFile(changed, 'w') as target:
            for name, raw in members.items():
                target.writestr(name, raw)
        with self.assertRaises(I.ImportError):
            I.read_source(changed)

    def test_cancel_is_distinct_and_does_not_create_staging(self):
        staging = self.root / 'not-created'
        with self.assertRaises(F.BackupCancelled):
            I.read_source(self.package(), staging=staging, cancelled=lambda: True)
        self.assertFalse(staging.exists())

    def test_unsupported_format_and_read_errors_do_not_expose_paths_or_body(self):
        secret = 'PRIVATE-BODY-NOT-IN-ERROR'
        for path in (self.root / (secret + '.json'), self.source({}, secret + '.txt')):
            with self.subTest(path=path):
                with self.assertRaises(I.ImportError) as error:
                    I.read_source(path)
                self.assertNotIn(secret, str(error.exception))


if __name__ == '__main__':
    unittest.main()
