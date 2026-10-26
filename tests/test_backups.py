"""Backup/restore service regression. Only synthetic temporary libraries are used."""
from copy import deepcopy
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clawboard import backup_format as F
from clawboard import backup_restore as R
from clawboard.backups import BackupCancelled, BackupError, BackupService


class SimulatedCrash(BaseException):
    pass


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='cb-backup-test-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / 'source/ClawBoard数据.json'
        self.source.parent.mkdir()
        self.images = self.source.parent / 'images'
        self.images.mkdir()
        (self.images / 'shared.png').write_bytes(b'synthetic-new-image')
        self.data = dict(schema_version=3, future={'preserved': ['中文', 1]},
            clip=[dict(id='text', text='untruncated\ncontent', future_item={'keep': True}),
                  dict(id='image', text='[图片]', content_type='image', image_path='shared.png'),
                  dict(id='file', text='C:/missing-secret.docx', content_type='filelist')],
            groups=[dict(name='custom', future_group=5, items=[
                dict(id='phrase', text='[图片]', content_type='image', image_path='shared.png')])],
            settings=dict(theme='light', future_setting={'keep': True}))
        self.raw = json.dumps(self.data, ensure_ascii=False, indent=3).encode('utf-8')
        self.source.write_bytes(self.raw)
        self.service = BackupService(self.source)
        self.archive = self.root / 'package.zip'
        self.preview = self.service.create(self.archive)
        self.target = self.root / 'target/ClawBoard数据.json'
        self.target.parent.mkdir()
        self.old_raw = b'{"schema_version":3,"clip":[{"id":"old","text":"old","image_path":"shared.png"}],"groups":[],"future":"original"}'
        self.target.write_bytes(self.old_raw)
        self.target_images = self.target.parent / 'images'
        self.target_images.mkdir()
        (self.target_images / 'shared.png').write_bytes(b'original-conflicting-image')
        (self.target_images / 'unrelated.txt').write_bytes(b'keep-unrelated')
        self.target_service = BackupService(self.target)

    def rewrite(self, transform, extras=()):
        target = self.root / 'changed.zip'
        with zipfile.ZipFile(self.archive) as source:
            members = {info.filename: source.read(info) for info in source.infolist()}
        transform(members)
        with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_STORED) as out:
            for name, raw in members.items():
                out.writestr(name, raw)
            for name, raw in extras:
                out.writestr(name, raw)
        return target

    def assert_original(self):
        self.assertEqual(self.target.read_bytes(), self.old_raw)
        self.assertEqual((self.target_images / 'shared.png').read_bytes(), b'original-conflicting-image')
        self.assertEqual((self.target_images / 'unrelated.txt').read_bytes(), b'keep-unrelated')

    def test_package_preserves_raw_json_and_unknown_fields_and_unique_images(self):
        inspected = self.service.inspect(self.archive)
        self.assertEqual(inspected, self.preview)
        self.assertEqual((inspected.clip_count, inspected.phrase_count, inspected.image_count,
                          inspected.external_file_count), (3, 1, 1, 1))
        with zipfile.ZipFile(self.archive) as archive:
            self.assertEqual(set(archive.namelist()), {'manifest.json', 'data.json', 'images/shared.png'})
            self.assertEqual(archive.read('data.json'), self.raw)
        self.assertEqual(inspected.sha256, hashlib.sha256(self.archive.read_bytes()).hexdigest())

    def test_restore_json_last_preserves_unrelated_files_and_complete_before_backup(self):
        replaced = []
        original_replace = os.replace
        def replace(source, destination):
            if Path(destination) in (self.target, self.target_images / 'shared.png'):
                replaced.append(Path(destination).name)
            return original_replace(source, destination)
        with patch.object(R.os, 'replace', side_effect=replace):
            result = self.target_service.restore(self.archive, self.preview.sha256)
        self.assertEqual(replaced, ['shared.png', self.target.name])
        self.assertEqual(self.target.read_bytes(), self.raw)
        self.assertEqual((self.target_images / 'shared.png').read_bytes(), b'synthetic-new-image')
        self.assertEqual((self.target_images / 'unrelated.txt').read_bytes(), b'keep-unrelated')
        with zipfile.ZipFile(result.backup_path) as original:
            self.assertEqual(original.read('data.json'), self.old_raw)
            self.assertEqual(original.read('images/shared.png'), b'original-conflicting-image')
            self.assertEqual(original.read('images/unrelated.txt'), b'keep-unrelated')
        self.assertFalse(result.cleanup_pending)
        self.assertIsNone(self.target_service.recover_pending())

    def test_restored_library_reloads_in_new_process(self):
        self.target_service.restore(self.archive, self.preview.sha256)
        script = '''
import json,sys
sys.path.insert(0,sys.argv[1])
from clawboard.storage import JsonStore
d=JsonStore(sys.argv[2]).load().data
assert d['future']=={'preserved':['中文',1]}
assert d['clip'][0]['future_item']=={'keep':True}
assert d['groups'][0]['future_group']==5
assert d['settings']['future_setting']=={'keep':True}
print('new-process-reload-ok')
'''
        done = subprocess.run([sys.executable, '-c', script, str(ROOT), str(self.target)],
                              capture_output=True, text=True, timeout=10)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_corrupt_current_json_is_preserved_before_valid_restore(self):
        corrupt = b'\xef\xbb\xbf{broken-json'
        self.target.write_bytes(corrupt)
        result = self.target_service.restore(self.archive, self.preview.sha256)
        self.assertEqual(self.target.read_bytes(), self.raw)
        with zipfile.ZipFile(result.backup_path) as old:
            self.assertEqual(old.read('data.json'), corrupt)
            self.assertEqual(json.loads(old.read('manifest.json'))['kind'], 'safety-snapshot')

    def test_valid_before_backup_can_restore_without_overwriting_spare_files(self):
        result = self.target_service.restore(self.archive, self.preview.sha256)
        (self.target_images / 'unrelated.txt').write_bytes(b'user-changed-spare')
        inspected = self.target_service.inspect(result.backup_path)
        self.target_service.restore(result.backup_path, inspected.sha256)
        self.assertEqual(self.target.read_bytes(), self.old_raw)
        self.assertEqual((self.target_images / 'shared.png').read_bytes(), b'original-conflicting-image')
        self.assertEqual((self.target_images / 'unrelated.txt').read_bytes(), b'user-changed-spare')

    def test_cancel_create_preserves_existing_destination(self):
        original = self.archive.read_bytes()
        with self.assertRaises(BackupCancelled):
            self.service.create(self.archive, cancelled=lambda: True)
        self.assertEqual(self.archive.read_bytes(), original)
        self.assertFalse(list(self.root.glob('.backup-*')))

    def test_cancel_restore_before_commit_preserves_library(self):
        with self.assertRaises(BackupCancelled):
            self.target_service.restore(self.archive, self.preview.sha256, cancelled=lambda: True)
        self.assert_original()
        self.assertFalse(list(self.target.parent.glob('.clawboard-restore-*')))

    def test_cancel_after_image_replace_rolls_back(self):
        stop = [False]
        original_replace = os.replace
        def replace(source, destination):
            result = original_replace(source, destination)
            if Path(destination) == self.target_images / 'shared.png':
                stop[0] = True
            return result
        with patch.object(R.os, 'replace', side_effect=replace), self.assertRaises(BackupCancelled):
            self.target_service.restore(self.archive, self.preview.sha256, cancelled=lambda: stop[0])
        self.assert_original()

    def test_cancel_after_json_replace_rolls_back_whole_plan(self):
        stop = [False]
        original_replace = os.replace
        def replace(source, destination):
            result = original_replace(source, destination)
            if Path(destination) == self.target:
                stop[0] = True
            return result
        with patch.object(R.os, 'replace', side_effect=replace), self.assertRaises(BackupCancelled):
            self.target_service.restore(self.archive, self.preview.sha256, cancelled=lambda: stop[0])
        self.assert_original()

    def test_rollback_temporary_cannot_collide_with_another_legal_image_name(self):
        self.data['clip'].extend([{'text': 'one', 'image_path': 'a.png'},
                                  {'text': 'two', 'image_path': 'a.png.rollback'}])
        self.source.write_bytes(F.json_bytes(self.data))
        for name in ('a.png', 'a.png.rollback'):
            (self.images / name).write_bytes(('new-' + name).encode())
            (self.target_images / name).write_bytes(('old-' + name).encode())
        self.preview = self.service.create(self.archive)
        self.crash_after(self.target)
        self.target_service.recover_pending()
        self.assert_original()
        for name in ('a.png', 'a.png.rollback'):
            self.assertEqual((self.target_images / name).read_bytes(), ('old-' + name).encode())

    def test_fresh_library_crash_removes_only_new_assets(self):
        fresh = self.root / 'fresh-crash/ClawBoard数据.json'
        service = BackupService(fresh)
        original_replace = os.replace
        def replace(source, destination):
            result = original_replace(source, destination)
            if Path(destination) == fresh:
                raise SimulatedCrash()
            return result
        with patch.object(R.os, 'replace', side_effect=replace), self.assertRaises(SimulatedCrash):
            service.restore(self.archive, self.preview.sha256)
        service.recover_pending()
        self.assertFalse(fresh.exists())
        self.assertFalse((fresh.parent / 'images').exists())

    def test_safety_backup_write_failure_never_modifies_targets(self):
        original_replace = os.replace
        def replace(source, destination):
            if Path(destination).name.startswith('ClawBoard恢复前_'):
                raise PermissionError('synthetic safety-backup denial')
            return original_replace(source, destination)
        with patch.object(R.os, 'replace', side_effect=replace), self.assertRaises(BackupError):
            self.target_service.restore(self.archive, self.preview.sha256)
        self.assert_original()
        self.assertFalse((self.target.parent / '.clawboard-restore-journal.json').exists())

    def test_disk_failure_replacing_json_rolls_images_back(self):
        original_replace, failed = os.replace, [False]
        def replace(source, destination):
            if Path(destination) == self.target and not failed[0]:
                failed[0] = True
                raise PermissionError('synthetic replacement denied')
            return original_replace(source, destination)
        with patch.object(R.os, 'replace', side_effect=replace), self.assertRaises(BackupError):
            self.target_service.restore(self.archive, self.preview.sha256)
        self.assert_original()
        self.assertIsNone(self.target_service.recover_pending())

    def test_disk_full_rollback_restores_bytes_without_new_file_allocation(self):
        self.crash_after(self.target_images / 'shared.png')
        no_space = OSError(errno.ENOSPC, 'synthetic full disk')
        original_open = Path.open
        def open_readonly(path, mode='r', *args, **kwargs):
            if any(flag in mode for flag in 'wax+'):
                raise no_space
            return original_open(path, mode, *args, **kwargs)
        with patch.object(Path, 'open', open_readonly), \
             patch.object(R.tempfile, 'mkstemp', side_effect=no_space) as allocate, \
             patch.object(R, '_copy', side_effect=no_space) as copy:
            # The journal marker may fail, but existing target bytes must already be old.
            with self.assertRaises(BackupError):
                self.target_service.recover_pending()
            self.assert_original()
            copy.assert_not_called()
            allocate.assert_called_once()
        self.assertTrue((self.target.parent / '.clawboard-restore-journal.json').exists())
        self.assertEqual(self.target_service.recover_pending().status, 'rolled_back')
        self.assert_original()

    def test_crash_after_rollback_rename_replays_without_consumed_before_image(self):
        self.crash_after(self.target)
        original_replace = os.replace
        def replace(source, destination):
            result = original_replace(source, destination)
            if Path(destination) == self.target_images / 'shared.png':
                raise SimulatedCrash()
            return result
        with patch.object(R.os, 'replace', side_effect=replace), self.assertRaises(SimulatedCrash):
            self.target_service.recover_pending()
        journal = self.target.parent / '.clawboard-restore-journal.json'
        plan = json.loads(journal.read_bytes())
        original_image = self.target.parent / plan['transaction'] / 'old/images/shared.png'
        self.assertFalse(original_image.exists(), 'rollback rename must consume its before-image')
        self.assertEqual((self.target_images / 'shared.png').read_bytes(), b'original-conflicting-image')
        script = '''
import sys
sys.path.insert(0,sys.argv[1])
from clawboard.backups import BackupService
r=BackupService(sys.argv[2]).recover_pending()
assert r.status=='rolled_back' and not r.cleanup_pending
print('rollback-rename-replay-ok')
'''
        done = subprocess.run([sys.executable, '-c', script, str(ROOT), str(self.target)],
                              capture_output=True, text=True, timeout=10)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assert_original()
        self.assertFalse(journal.exists())

    def crash_after(self, destination):
        original_replace = os.replace
        def replace(source, target):
            result = original_replace(source, target)
            if Path(target) == destination:
                raise SimulatedCrash()
            return result
        with patch.object(R.os, 'replace', side_effect=replace), self.assertRaises(SimulatedCrash):
            self.target_service.restore(self.archive, self.preview.sha256)

    def test_crash_after_json_replace_before_commit_rolls_back_in_new_process(self):
        self.crash_after(self.target)
        self.assertEqual(self.target.read_bytes(), self.raw)
        script = '''
import sys
sys.path.insert(0,sys.argv[1])
from clawboard.backups import BackupService
r=BackupService(sys.argv[2]).recover_pending()
assert r.status=='rolled_back' and not r.cleanup_pending
print('crash-recovery-ok')
'''
        done = subprocess.run([sys.executable, '-c', script, str(ROOT), str(self.target)],
                              capture_output=True, text=True, timeout=10)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assert_original()

    def test_crash_after_image_replace_rolls_back_and_is_idempotent(self):
        self.crash_after(self.target_images / 'shared.png')
        result = self.target_service.recover_pending()
        self.assertEqual(result.status, 'rolled_back')
        self.assert_original()
        self.assertIsNone(self.target_service.recover_pending())

    def test_crash_after_commit_keeps_new_library(self):
        with patch.object(R.RestoreTransaction, '_clean', side_effect=SimulatedCrash), self.assertRaises(SimulatedCrash):
            self.target_service.restore(self.archive, self.preview.sha256)
        result = self.target_service.recover_pending()
        self.assertEqual(result.status, 'committed')
        self.assertEqual(self.target.read_bytes(), self.raw)

    def test_cleanup_failure_does_not_report_committed_restore_as_failed(self):
        with patch.object(R.RestoreTransaction, '_clean', side_effect=PermissionError('synthetic cleanup denied')):
            result = self.target_service.restore(self.archive, self.preview.sha256)
        self.assertTrue(result.cleanup_pending)
        self.assertEqual(self.target_service.recover_pending().status, 'committed')

    def test_wrong_preview_hash_does_not_begin_restore(self):
        with self.assertRaises(BackupError):
            self.target_service.restore(self.archive, '0' * 64)
        self.assert_original()
        self.assertFalse(list(self.target.parent.glob('ClawBoard恢复前_*')))

    def test_no_existing_library_can_be_restored(self):
        fresh = self.root / 'fresh/ClawBoard数据.json'
        BackupService(fresh).restore(self.archive, self.preview.sha256)
        self.assertEqual(fresh.read_bytes(), self.raw)

    def test_create_rejects_data_file_and_parent_alias_and_image_directory(self):
        sub = self.source.parent / 'sub'
        sub.mkdir()
        for destination in (self.source, sub / '..' / self.source.name,
                            self.images / 'nested/package.zip', Path(str(self.source) + '.')):
            with self.subTest(destination=str(destination)), self.assertRaises(BackupError):
                self.service.create(destination)
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_create_requires_zip_extension_without_overwriting_other_files(self):
        for suffix in ('.py', '.exe', '.json', ''):
            destination = self.root / ('existing' + suffix)
            destination.write_bytes(b'original-unrelated-file')
            with self.subTest(suffix=suffix), self.assertRaises(BackupError):
                self.service.create(destination)
            self.assertEqual(destination.read_bytes(), b'original-unrelated-file')
        uppercase = self.root / 'accepted.ZIP'
        self.assertEqual(self.service.create(uppercase).archive, uppercase)

    def test_present_settings_must_be_object_but_legacy_omission_is_accepted(self):
        for settings in ([], 7, None, 'invalid', False):
            data = deepcopy(self.data)
            data['settings'] = settings
            raw = F.json_bytes(data)
            self.source.write_bytes(raw)
            with self.subTest(settings=settings), self.assertRaises(BackupError):
                self.service.create(self.root / 'invalid-settings.zip')
            # Reject an internally hashed package too, not only our writer input.
            details = dict(schema_version=3, clip_count=3, phrase_count=1, external_file_count=1)
            malformed = self.root / 'hashed-invalid-settings.zip'
            F.write_package(malformed, raw, [('shared.png', self.images / 'shared.png')], details=details)
            with self.assertRaises(BackupError):
                self.target_service.restore(malformed)
            self.assert_original()
        legacy = deepcopy(self.data)
        legacy.pop('settings')
        legacy_raw = F.json_bytes(legacy)
        self.source.write_bytes(legacy_raw)
        preview = self.service.create(self.archive)
        self.target_service.restore(self.archive, preview.sha256)
        self.assertEqual(self.target.read_bytes(), legacy_raw)

    def test_missing_source_image_fails_without_publishing(self):
        (self.images / 'shared.png').unlink()
        destination = self.root / 'missing.zip'
        with self.assertRaises(BackupError):
            self.service.create(destination)
        self.assertFalse(destination.exists())

    def test_unsafe_zip_paths_rejected_without_writes(self):
        for name in ('../escape', '/absolute', 'C:/absolute', 'images/name:stream',
                     'images/CON.png', 'images/COM¹.png', 'images/CONIN$', 'images/CONOUT$',
                     'images/CON .txt', 'images/NUL .png', 'images/COM1 .png', 'images/name.',
                     'images/name ', 'images/a\\b.png', 'images/sub/a.png', 'images/'):
            with self.subTest(name=name):
                changed = self.rewrite(lambda members: None, [(name, b'bad')])
                with self.assertRaises(BackupError):
                    self.target_service.inspect(changed)
                self.assert_original()

    def test_case_collisions_and_symlink_members_rejected(self):
        changed = self.rewrite(lambda members: None, [('images/SHARED.PNG', b'duplicate')])
        with self.assertRaises(BackupError):
            self.service.inspect(changed)
        info = zipfile.ZipInfo('images/link.png')
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        changed = self.rewrite(lambda members: None, [(info, b'../outside')])
        with self.assertRaises(BackupError):
            self.service.inspect(changed)

    def test_missing_image_and_bad_hash_and_invalid_json_rejected(self):
        changed = self.rewrite(lambda members: members.pop('images/shared.png'))
        with self.assertRaises(BackupError):
            self.service.inspect(changed)
        def bad_hash(members):
            manifest = json.loads(members['manifest.json'])
            manifest['members'][0]['sha256'] = '0' * 64
            members['manifest.json'] = F.json_bytes(manifest)
        changed = self.rewrite(bad_hash)
        with self.assertRaises(BackupError):
            self.service.inspect(changed)
        changed = self.rewrite(lambda members: members.update({'data.json': b'broken'}))
        with self.assertRaises(BackupError):
            self.service.inspect(changed)

    def test_crc_failure_rejected(self):
        changed = self.rewrite(lambda members: None)
        raw = bytearray(changed.read_bytes())
        marker = raw.index(b'synthetic-new-image')
        raw[marker] ^= 1
        changed.write_bytes(raw)
        with self.assertRaises(BackupError):
            self.service.inspect(changed)

    def test_encrypted_or_unsupported_compression_rejected(self):
        changed = self.rewrite(lambda members: None)
        raw = bytearray(changed.read_bytes())
        local, central = raw.index(b'PK\x03\x04'), raw.index(b'PK\x01\x02')
        raw[local + 6] |= 1
        raw[central + 8] |= 1
        changed.write_bytes(raw)
        with self.assertRaises(BackupError):
            self.service.inspect(changed)

    def test_manifest_size_and_json_size_and_total_limits(self):
        with patch.object(F, 'MAX_MANIFEST_BYTES', 20), self.assertRaises(BackupError):
            self.service.inspect(self.archive)
        with patch.object(F, 'MAX_JSON_BYTES', 20), self.assertRaises(BackupError):
            self.service.inspect(self.archive)
        with patch.object(F, 'MAX_TOTAL_BYTES', 20), self.assertRaises(BackupError):
            self.service.inspect(self.archive)

    def test_member_limit_checked_before_zipfile_allocates(self):
        with patch.object(F, 'MAX_MEMBERS', 2), patch.object(F.zipfile, 'ZipFile') as constructor:
            with self.assertRaises(BackupError):
                self.service.inspect(self.archive)
            constructor.assert_not_called()

    def test_safety_snapshot_directory_is_limited_before_collection(self):
        with patch.object(R, 'MAX_MEMBERS', 3), self.assertRaises(BackupError):
            self.target_service.restore(self.archive, self.preview.sha256)
        self.assert_original()

    def test_image_limit_rejects_sparse_oversized_source(self):
        with (self.images / 'shared.png').open('wb') as image:
            image.seek(F.MAX_IMAGE_BYTES)
            image.write(b'x')
        with self.assertRaises(BackupError):
            self.service.create(self.root / 'oversized-image.zip')

    def test_rollback_rejects_link_in_transaction_subtree(self):
        self.crash_after(self.target_images / 'shared.png')
        journal = self.target.parent / '.clawboard-restore-journal.json'
        plan = json.loads(journal.read_bytes())
        old = self.target.parent / plan['transaction'] / 'old'
        moved = old.with_name('original-moved')
        old.rename(moved)
        try:
            old.symlink_to(moved, target_is_directory=True)
        except OSError:
            moved.rename(old)
            self.skipTest('creating local symlinks is unavailable')
        try:
            with self.assertRaises(BackupError):
                self.target_service.recover_pending()
            self.assertEqual((moved / 'data.json').read_bytes(), self.old_raw)
        finally:
            old.unlink()

    def test_forged_directory_count_and_truncated_archive_rejected(self):
        changed = self.root / 'forged.zip'
        raw = bytearray(self.archive.read_bytes())
        raw[-14:-12] = struct.pack('<H', 2)
        raw[-12:-10] = struct.pack('<H', 2)
        changed.write_bytes(raw)
        with self.assertRaises(BackupError):
            self.service.inspect(changed)
        changed.write_bytes(self.archive.read_bytes()[:-5])
        with self.assertRaises(BackupError):
            self.service.inspect(changed)

    def test_incompatible_schema_and_unsafe_image_reference_rejected_at_create(self):
        for changes in ({'schema_version': 999}, {'schema_version': True},
                        {'clip': [{'text': 'bad', 'image_path': '../escape'}]}):
            data = deepcopy(self.data)
            data.update(changes)
            self.source.write_bytes(F.json_bytes(data))
            with self.subTest(changes=changes), self.assertRaises(BackupError):
                self.service.create(self.root / 'invalid.zip')

    def test_forged_journal_path_cannot_touch_outside_directory(self):
        self.crash_after(self.target_images / 'shared.png')
        journal = self.target.parent / '.clawboard-restore-journal.json'
        plan = json.loads(journal.read_bytes())
        plan['transaction'] = '../outside'
        journal.write_bytes(F.json_bytes(plan))
        with self.assertRaises(BackupError):
            self.target_service.recover_pending()
        self.assertEqual(self.target.read_bytes(), self.old_raw)
        self.assertTrue(journal.exists())

    def test_interrupted_restore_does_not_overwrite_external_edits(self):
        self.crash_after(self.target_images / 'shared.png')
        (self.target_images / 'shared.png').write_bytes(b'edited-by-another-tool')
        with self.assertRaises(BackupError):
            self.target_service.recover_pending()
        self.assertEqual((self.target_images / 'shared.png').read_bytes(), b'edited-by-another-tool')
        self.assertTrue((self.target.parent / '.clawboard-restore-journal.json').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
