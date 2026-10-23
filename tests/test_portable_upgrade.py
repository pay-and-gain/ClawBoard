"""Portable upgrade contracts; synthetic temporary files, no App/registry/process changes."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import upgrade_portable as upgrade


def executable(content):
    header = bytearray(128)
    header[:2] = b'MZ'
    struct.pack_into('<I', header, 60, len(header))
    return bytes(header) + b'PE\0\0' + content


class PortableUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='cb-upgrade-contract-')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.cut = self.directory / 'cut'
        self.cut.mkdir()
        self.current = self.cut / 'ClawBoard-test.exe'
        self.candidate = self.directory / 'candidate.exe'
        self.old, self.new = executable(b'old-synthetic'), executable(b'new-synthetic')
        self.current.write_bytes(self.old)
        self.candidate.write_bytes(self.new)
        self.data = self.cut / 'ClawBoard数据.json'
        self.images = self.cut / 'images'
        self.images.mkdir()
        (self.images / 'example.png').write_bytes(b'synthetic-image')
        (self.images / 'orphan.png').write_bytes(b'synthetic-orphan')
        self.raw = dict(schema_version=3, vendor={'unknown': [1, {'keep': True}]},
                        settings={'theme': 'dark'}, gi=0,
                        clip=[dict(id='clip-a', text='SYNTHETIC BODY NEVER LOGGED',
                                   created_at=1_700_000_000_000, fav=1, content_type='text',
                                   extra={'future': 'preserved'}),
                              dict(id='clip-image', text='[image]', created_at=1_700_000_000_001,
                                   content_type='image', image_path='example.png')],
                        groups=[dict(name='SYNTHETIC GROUP NEVER LOGGED', unknown=['preserved'],
                                     items=[dict(id='phrase-a', text='SYNTHETIC PHRASE NEVER LOGGED',
                                                 trigger='demo', created_at=1_700_000_000_002)])])
        self.write_data()
        (self.cut / 'unrelated-secret-note.txt').write_text('must not enter backup')
        (self.cut / 'unrelated').mkdir()
        (self.cut / 'unrelated' / 'other.txt').write_text('must not be walked')
        self.idle = self.enterContext(patch.object(upgrade, '_assert_idle', return_value=None))
        self.enterContext(patch.object(upgrade.JsonStore, 'save', side_effect=AssertionError('save called')))

    def write_data(self):
        self.data.write_text(json.dumps(self.raw, ensure_ascii=False), encoding='utf-8')

    def make_plan(self):
        return upgrade.plan(self.current, self.candidate)

    def make_backup(self):
        value = self.make_plan()
        reviewed = upgrade.plan_sha256(value)
        return value, reviewed, upgrade.backup(value, expected_plan_sha=reviewed)

    def payload(self):
        return {path.relative_to(self.cut).as_posix(): path.read_bytes()
                for path in (self.data, *self.images.iterdir())}

    def test_plan_is_read_only_preserves_optional_unknown_fields_and_prints_only_summary(self):
        before = self.payload()
        tree = sorted(path.relative_to(self.cut).as_posix() for path in self.cut.rglob('*'))
        value = self.make_plan()
        self.assertEqual(value['semantics'], dict(schema_version=3, history_count=2, group_count=1,
                                                 phrase_count=1, image_count=2, referenced_image_count=1))
        self.assertEqual(self.payload(), before)
        self.assertEqual(sorted(path.relative_to(self.cut).as_posix() for path in self.cut.rglob('*')), tree)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(upgrade.main(['plan', '--current', str(self.current),
                                           '--candidate', str(self.candidate)]), 0)
        report = json.loads(output.getvalue())
        self.assertIn('schema_version', report)
        self.assertNotIn('schema', report)
        self.assertNotIn('SYNTHETIC', output.getvalue())
        self.assertNotIn('vendor', output.getvalue())

    def test_backup_whitelist_crc_hashes_and_apply_rollback_only_touch_executable(self):
        payload = self.payload()
        value, reviewed, manifest = self.make_backup()
        with zipfile.ZipFile(manifest.parent / 'portable-backup.zip') as archive:
            self.assertEqual(set(archive.namelist()), {self.current.name, self.data.name,
                                                      'images/example.png', 'images/orphan.png'})
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.read(self.current.name), self.old)
        original_open = Path.open
        def protect_payload(path, mode='r', *args, **kwargs):
            if path in (self.data, *self.images.iterdir()) and any(char in mode for char in 'wax+'):
                raise AssertionError('data or image opened for writing')
            return original_open(path, mode, *args, **kwargs)
        with patch.object(Path, 'open', protect_payload):
            result = upgrade.apply(manifest, expected_plan_sha=reviewed)
            self.assertEqual(result['state'], 'applied')
            self.assertEqual(self.current.read_bytes(), self.new)
            self.assertEqual(self.payload(), payload)
            upgrade.rollback(manifest, expected_plan_sha=reviewed)
        self.assertEqual(self.current.read_bytes(), self.old)
        self.assertEqual(self.payload(), payload)
        self.assertTrue(manifest.exists())
        self.assertEqual(list(self.cut.glob('.ClawBoard-upgrade-*')), [])

    def test_running_process_aborts_before_any_write_and_never_terminates_it(self):
        self.idle.side_effect = upgrade.UpgradeError('current executable process is running')
        with self.assertRaises(upgrade.UpgradeError):
            self.make_plan()
        self.assertEqual(list(self.cut.glob('backup-*')), [])
        self.assertEqual(self.current.read_bytes(), self.old)

    def test_reviewed_hash_and_required_plan_review_block_writes(self):
        with self.assertRaises(upgrade.UpgradeError):
            upgrade.plan(self.current, self.candidate, expected_old_sha='0' * 64)
        value = self.make_plan()
        for reviewed in (None, '0' * 64):
            with self.assertRaises(upgrade.UpgradeError):
                upgrade.backup(value, expected_plan_sha=reviewed)
        self.assertEqual(list(self.cut.glob('backup-*')), [])

    def test_source_change_after_plan_aborts_backup_before_directory_creation(self):
        value = self.make_plan()
        (self.images / 'example.png').write_bytes(b'changed externally')
        with self.assertRaises(upgrade.UpgradeError):
            upgrade.backup(value, expected_plan_sha=upgrade.plan_sha256(value))
        self.assertEqual(list(self.cut.glob('backup-*')), [])

    def test_source_change_during_archive_verification_never_creates_ready_manifest(self):
        value = self.make_plan()
        verify = upgrade._verify_archive
        def external_change(path, original):
            verify(path, original)
            self.data.write_bytes(self.data.read_bytes() + b' ')
        with patch.object(upgrade, '_verify_archive', side_effect=external_change):
            with self.assertRaises(upgrade.UpgradeError):
                upgrade.backup(value, expected_plan_sha=upgrade.plan_sha256(value))
        directories = list(self.cut.glob('backup-*'))
        self.assertEqual(len(directories), 1)
        self.assertTrue((directories[0] / 'aborted.json').exists())
        self.assertFalse((directories[0] / 'manifest.json').exists())
        self.assertEqual(self.current.read_bytes(), self.old)

    def test_apply_replace_failure_preserves_original_and_verified_old_backup(self):
        _, reviewed, manifest = self.make_backup()
        before = self.payload()
        with patch.object(upgrade.os, 'replace', side_effect=PermissionError('synthetic denial')):
            with self.assertRaises(PermissionError):
                upgrade.apply(manifest, expected_plan_sha=reviewed)
        self.assertEqual(self.current.read_bytes(), self.old)
        self.assertEqual(self.payload(), before)
        self.assertEqual(list(self.cut.glob('.ClawBoard-upgrade-*')), [])
        with zipfile.ZipFile(manifest.parent / 'portable-backup.zip') as archive:
            self.assertEqual(archive.read(self.current.name), self.old)

    def test_candidate_change_or_unreviewed_manifest_blocks_apply(self):
        _, reviewed, manifest = self.make_backup()
        for expected in (None, '0' * 64):
            with self.assertRaises(upgrade.UpgradeError):
                upgrade.apply(manifest, expected_plan_sha=expected)
        self.candidate.write_bytes(executable(b'another build'))
        with self.assertRaises(upgrade.UpgradeError):
            upgrade.apply(manifest, expected_plan_sha=reviewed)
        self.assertEqual(self.current.read_bytes(), self.old)

    def test_crc_corruption_is_rejected_even_if_archive_envelope_hash_is_updated(self):
        _, reviewed, manifest = self.make_backup()
        archive_path = manifest.parent / 'portable-backup.zip'
        with zipfile.ZipFile(archive_path) as archive:
            info = archive.getinfo(self.current.name)
        damaged = bytearray(archive_path.read_bytes())
        name_size, extra_size = struct.unpack_from('<HH', damaged, info.header_offset + 26)
        offset = info.header_offset + 30 + name_size + extra_size
        damaged[offset + info.compress_size // 2] ^= 0x40
        archive_path.write_bytes(damaged)
        document = json.loads(manifest.read_text())
        document['archive_sha256'] = upgrade._file_record(archive_path)['sha256']
        manifest.write_text(json.dumps(document), encoding='utf-8')
        with self.assertRaises(upgrade.UpgradeError):
            upgrade.apply(manifest, expected_plan_sha=reviewed)
        self.assertEqual(self.current.read_bytes(), self.old)

    def test_process_appearing_during_staging_aborts_before_replace(self):
        _, reviewed, manifest = self.make_backup()
        stage = upgrade._stage
        def process_appears(*args):
            path = stage(*args)
            self.idle.side_effect = upgrade.UpgradeError('current executable process is running')
            return path
        with patch.object(upgrade, '_stage', side_effect=process_appears):
            with self.assertRaises(upgrade.UpgradeError):
                upgrade.apply(manifest, expected_plan_sha=reviewed)
        self.assertEqual(self.current.read_bytes(), self.old)
        self.assertTrue(manifest.exists())
        self.assertEqual(list(self.cut.glob('.ClawBoard-upgrade-*')), [])

    def test_corrupted_archive_and_wrong_item_hash_block_apply(self):
        _, reviewed, manifest = self.make_backup()
        archive_path = manifest.parent / 'portable-backup.zip'
        with zipfile.ZipFile(archive_path) as archive:
            original = {name: archive.read(name) for name in archive.namelist()}
        original[self.current.name] = executable(b'not the archived original')
        with zipfile.ZipFile(archive_path, 'w') as archive:
            for name, data in original.items():
                archive.writestr(name, data)
        document = json.loads(manifest.read_text())
        document['archive_sha256'] = upgrade._file_record(archive_path)['sha256']
        manifest.write_text(json.dumps(document), encoding='utf-8')
        with self.assertRaises(upgrade.UpgradeError):
            upgrade.apply(manifest, expected_plan_sha=reviewed)
        self.assertEqual(self.current.read_bytes(), self.old)

    def test_rollback_preserves_new_history_and_images_and_rejects_unknown_current_exe(self):
        _, reviewed, manifest = self.make_backup()
        upgrade.apply(manifest, expected_plan_sha=reviewed)
        self.raw['clip'].append(dict(id='after-upgrade', text='new synthetic history', created_at=1_700_000_000_003))
        self.write_data()
        (self.images / 'after.png').write_bytes(b'new synthetic image')
        before = self.payload()
        upgrade.rollback(manifest, expected_plan_sha=reviewed)
        self.assertEqual(self.current.read_bytes(), self.old)
        self.assertEqual(self.payload(), before)
        self.current.write_bytes(executable(b'unknown replacement'))
        with self.assertRaises(upgrade.UpgradeError):
            upgrade.rollback(manifest, expected_plan_sha=reviewed)

    def test_normalization_changes_existing_id_or_unknown_value_are_rejected(self):
        self.raw['clip'][0]['id'] = 12
        self.write_data()
        with self.assertRaises(upgrade.UpgradeError):
            self.make_plan()
        self.raw['clip'][0]['id'] = 'clip-a'
        self.write_data()
        normal = upgrade.JsonStore(self.data).load().data
        normal['vendor']['unknown'][1]['keep'] = False
        with patch.object(upgrade.JsonStore, 'load', return_value=types.SimpleNamespace(data=normal, recovery_required=False)):
            with self.assertRaises(upgrade.UpgradeError):
                self.make_plan()

    def test_missing_or_escaping_image_reference_aborts_without_writing(self):
        for reference in ('missing.png', '../outside.png', 'name:stream'):
            self.raw['clip'][1]['image_path'] = reference
            self.write_data()
            with self.assertRaises(upgrade.UpgradeError):
                self.make_plan()
        self.assertEqual(list(self.cut.glob('backup-*')), [])

    def test_nested_images_directory_and_candidate_inside_portable_directory_are_rejected(self):
        (self.images / 'nested').mkdir()
        with self.assertRaises(upgrade.UpgradeError):
            self.make_plan()
        (self.images / 'nested').rmdir()
        inside = self.cut / 'candidate.exe'
        inside.write_bytes(self.new)
        with self.assertRaises(upgrade.UpgradeError):
            upgrade.plan(self.current, inside)

    def test_symlink_hardlink_and_reparse_attribute_are_rejected(self):
        link = self.images / 'link.png'
        try:
            link.symlink_to(self.images / 'example.png')
        except OSError:
            pass  # Windows without developer-mode symlink permission still tests reparse flags below.
        else:
            with self.assertRaises(upgrade.UpgradeError):
                self.make_plan()
            link.unlink()
        os.link(self.images / 'example.png', link)
        with self.assertRaises(upgrade.UpgradeError):
            self.make_plan()
        link.unlink()
        original = Path.lstat
        def flagged(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            return types.SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400) if path == self.images else info
        with patch.object(Path, 'lstat', flagged):
            with self.assertRaises(upgrade.UpgradeError):
                self.make_plan()


if __name__ == '__main__':
    unittest.main(verbosity=2)
