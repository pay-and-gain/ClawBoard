"""Merge transactions and helper coordination using synthetic temporary files."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clawboard.backup_format import BackupError
from clawboard.backups import BackupService
from clawboard.import_service import ImportService
from clawboard import restore_job as jobs, backup_restore, backup_startup


class SimulatedCrash(BaseException):
    pass


@contextmanager
def lease(_):
    yield


class ImportServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cb-merge-service-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.base = self.root / 'current'
        self.base.mkdir()
        self.path = self.base / 'ClawBoard数据.json'
        self.images = self.base / 'images'
        self.images.mkdir()
        self.current = dict(schema_version=3, clip=[dict(id='old', text='KEEP current')],
                            groups=[dict(name='默认', items=[])],
                            settings=dict(max_items=500, theme='dark'),
                            future={'preserve': True})
        self.write_current()
        self.original = self.path.read_bytes()
        self.source = self.root / 'export.json'
        self.source.write_text(json.dumps({'version': 3, 'items': [
            dict(id='old', text='Synthetic imported 中文 😀', future={'key': 8})]}), encoding='utf-8')
        self.service = ImportService(self.path, self.images)

    def write_current(self):
        self.path.write_text(json.dumps(self.current, ensure_ascii=False), encoding='utf-8')

    def source_hash(self):
        return hashlib.sha256(self.source.read_bytes()).hexdigest()

    def merge(self, keys=('c:0',)):
        return self.service.merge(self.source, self.source_hash(), keys)

    def image_backup(self):
        directory = self.root / 'incoming'
        directory.mkdir()
        (directory / 'images').mkdir()
        (directory / 'images/shared.png').write_bytes(b'synthetic-new-image')
        data = dict(schema_version=3, clip=[dict(text='[图片]', content_type='image',
                                               image_path='shared.png')], groups=[])
        path = directory / 'ClawBoard数据.json'
        path.write_text(json.dumps(data), encoding='utf-8')
        self.source = self.root / 'backup.zip'
        BackupService(path).create(self.source)

    def test_additive_unknown_fields_settings_and_backup(self):
        result = self.merge()
        merged = json.loads(self.path.read_bytes())
        self.assertEqual(merged['clip'][-1] if merged['clip'][-1]['id'] == 'old'
                         else merged['clip'][0], self.current['clip'][0])
        incoming = next(x for x in merged['clip'] if x['id'] != 'old')
        self.assertEqual(incoming['future'], {'key': 8})
        self.assertEqual(merged['settings'], self.current['settings'])
        self.assertEqual(merged['future'], self.current['future'])
        self.assertEqual(result.imported_count, 1)
        self.assertTrue(result.backup_path.is_file())
        with __import__('zipfile').ZipFile(result.backup_path) as archive:
            self.assertEqual(archive.read('data.json'), self.original)

    def test_preview_is_read_only(self):
        snapshot = deepcopy(self.current)
        preview = self.service.inspect(self.source, snapshot)
        self.assertEqual(snapshot, self.current)
        self.assertEqual(preview.plan.imported_count, 1)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(sorted(x.name for x in self.base.iterdir()), ['ClawBoard数据.json', 'images'])

    def test_changed_source_rejected(self):
        expected = self.source_hash()
        self.source.write_text('{"version":3,"items":[]}', encoding='utf-8')
        with self.assertRaises(BackupError):
            self.service.merge(self.source, expected, ['c:0'])
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_duplicate_noop_keeps_exact_original_bytes(self):
        self.source.write_text(json.dumps({'version': 3, 'items': [dict(text='KEEP current')]}), encoding='utf-8')
        result = self.merge()
        self.assertTrue(result.no_op)
        self.assertIsNone(result.backup_path)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_missing_json_image_cannot_be_imported(self):
        self.source.write_text(json.dumps({'version': 3, 'items': [
            dict(text='[图片]', content_type='image', image_path='shared.png')]}), encoding='utf-8')
        with self.assertRaises(BackupError):
            self.merge()
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_zip_image_renamed_and_existing_spare_untouched(self):
        self.image_backup()
        (self.images / 'shared.png').write_bytes(b'KEEP original spare')
        result = self.merge()
        merged = json.loads(self.path.read_bytes())
        item = next(x for x in merged['clip'] if x.get('content_type') == 'image')
        self.assertNotEqual(item['image_path'].casefold(), 'shared.png')
        self.assertEqual((self.images / item['image_path']).read_bytes(), b'synthetic-new-image')
        self.assertEqual((self.images / 'shared.png').read_bytes(), b'KEEP original spare')
        self.assertEqual(result.imported_count, 1)

    def test_first_image_can_create_missing_directory(self):
        self.image_backup()
        self.images.rmdir()
        self.assertEqual(self.merge().imported_count, 1)
        self.assertEqual(len(list(self.images.iterdir())), 1)

    def test_failure_after_image_write_rolls_back(self):
        self.image_backup()
        replace = os.replace
        failed = False
        def failing(source, target):
            nonlocal failed
            if Path(target) == self.path and not failed:
                failed = True
                raise OSError('synthetic disk error')
            return replace(source, target)
        with patch.object(backup_restore.os, 'replace', side_effect=failing):
            with self.assertRaises(BackupError):
                self.merge()
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(list(self.images.iterdir()), [])

    def test_process_crash_recovers_original_library(self):
        self.image_backup()
        replace = os.replace
        def crashing(source, target):
            result = replace(source, target)
            if Path(target) == self.path:
                raise SimulatedCrash()
            return result
        with patch.object(backup_restore.os, 'replace', side_effect=crashing):
            with self.assertRaises(SimulatedCrash):
                self.merge()
        recovered = BackupService(self.path).recover_pending()
        self.assertEqual(recovered.status, 'rolled_back')
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(list(self.images.iterdir()), [])

    def test_helper_uses_latest_library_after_parent_exits(self):
        ticket = jobs.prepare_import_job(self.base, self.source, self.source_hash(), ['c:0'], parent_pid=123)
        self.current['clip'].append(dict(id='later', text='KEEP later capture'))
        self.write_current()
        result = jobs.run_restore_job(ticket, self.base, wait_parent=lambda *_: True,
                                      lease=lease, restart=lambda: None)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['operation'], 'merge')
        self.assertIn('KEEP later capture', [x['text'] for x in json.loads(self.path.read_bytes())['clip']])
        notice = backup_startup.consume_notice(self.base)
        self.assertEqual(notice[0], '内容合并导入完成')

    def test_helper_cancel_keeps_library(self):
        ticket = jobs.prepare_import_job(self.base, self.source, self.source_hash(), ['c:0'], parent_pid=123)
        jobs.cancel_restore_job(ticket, self.base)
        result = jobs.run_restore_job(ticket, self.base, wait_parent=lambda *_: True,
                                      lease=lease, restart=lambda: None)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_import_selection_ticket_validation(self):
        for keys in ([], ['c:0', 'c:0'], ['../escape'], ['c:' + '9' * 25]):
            with self.subTest(keys=keys), self.assertRaises(jobs.RestoreJobError):
                jobs.prepare_import_job(self.base, self.source, self.source_hash(), keys)


if __name__ == '__main__':
    unittest.main()
