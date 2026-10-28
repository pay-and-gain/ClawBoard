"""Recycle retention across saves, image GC and complete backups; synthetic only."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile

from clawboard.application import ApplicationController
from clawboard.backups import BackupService, BackupError
from clawboard.media import ImageStore
from clawboard.models import default_data
from clawboard.storage import JsonStore
from clawboard.trash import TrashService


class TrashIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cb-recycle-integration-')
        self.directory = Path(self.temp.name)
        self.data = default_data()
        self.store = JsonStore(self.directory / 'data.json')
        self.images = ImageStore(self.directory / 'images')
        self.no_save = False
        self.errors = []
        self.app = ApplicationController(self.data, self.store, self.images,
            no_save=lambda: self.no_save, on_error=self.errors.append)

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def settle(self):
        end = time.monotonic() + 3
        while self.app.pending:
            self.app.drain()
            self.assertLess(time.monotonic(), end)
            threading.Event().wait(.001)
        self.app.drain()

    def seed(self):
        name = self.images.write(b'synthetic retained image')
        self.data['clip'] = [dict(id='image', text='[image]', content_type='image',
                                  image_path=name, created_at=1, seq=2)]
        self.store.save(self.data)
        return name

    def test_recycled_image_is_protected_even_if_cleanup_was_already_queued(self):
        name = self.seed()
        self.app.queue_image_cleanup([name])
        self.app.trash.move(['image'])
        self.app.request_save()
        self.app.flush()
        self.settle()
        self.assertTrue((self.images.directory / name).is_file())
        loaded = self.store.load().data
        self.assertEqual(TrashService(loaded).entries()[0]['item']['image_path'], name)
        self.assertFalse(loaded['clip'])

    def test_failed_permanent_delete_save_keeps_original_image_and_disk_record(self):
        name = self.seed()
        entry = self.app.trash.move(['image'])[0]
        self.app.request_save()
        self.app.flush()
        self.settle()
        removed = self.app.trash.purge([entry['id']])
        self.app.queue_image_cleanup(item['image_path'] for item in removed)
        with patch.object(self.store, 'save', side_effect=OSError('synthetic disk full')):
            self.app.request_save()
            with self.assertRaises(OSError):
                self.app.flush()
            self.settle()
            self.assertTrue((self.images.directory / name).is_file())
            self.assertEqual(len(TrashService(self.store.load().data).entries()), 1)
        self.app.request_save()
        self.app.flush()
        self.settle()
        self.assertFalse((self.images.directory / name).exists())

    def test_automatic_expiry_is_saved_before_collecting_images(self):
        name = self.seed()
        entry = self.app.trash.move(['image'])[0]
        self.app.request_save()
        self.app.flush()
        self.settle()
        self.app.trash.clock = lambda: entry['deleted_at'] + 30 * 86400 * 1000
        self.app.request_save()
        self.app.flush()
        self.settle()
        self.assertEqual(self.app.trash.entries(), [])
        self.assertFalse((self.images.directory / name).exists())

    def test_no_save_never_expires_or_removes_a_persisted_recycled_image(self):
        name = self.seed()
        entry = self.app.trash.move(['image'])[0]
        self.store.save(self.data)
        before = self.store.path.read_bytes()
        self.app.trash.clock = lambda: entry['deleted_at'] + 31 * 86400 * 1000
        self.no_save = True
        self.app.request_save()
        self.settle()
        self.assertEqual(len(self.app.trash.entries()), 1)
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertTrue((self.images.directory / name).is_file())

    def test_complete_backup_roundtrip_includes_recycled_image_and_unknown_fields(self):
        name = self.seed()
        self.data['clip'][0]['future'] = {'kept': [1, 2]}
        self.app.trash.move(['image'])
        self.store.save(self.data)
        archive = self.directory / 'complete.zip'
        service = BackupService(self.store.path, self.images.directory)
        preview = service.create(archive)
        self.assertEqual((preview.clip_count, preview.trash_count, preview.image_count), (0, 1, 1))
        with zipfile.ZipFile(archive) as package:
            self.assertIn('images/' + name, package.namelist())
        target = self.directory / 'restored' / 'ClawBoard数据.json'
        target.parent.mkdir()
        JsonStore(target).save(default_data())
        BackupService(target).restore(archive, expected_sha256=preview.sha256)
        restored = JsonStore(target).load().data
        trash = TrashService(restored)
        item = trash.restore([trash.entries()[0]['id']])[0]
        self.assertEqual(item['future'], {'kept': [1, 2]})
        self.assertEqual((target.parent / 'images' / name).read_bytes(), b'synthetic retained image')

    def test_old_complete_backup_without_trash_count_remains_readable(self):
        self.store.save(self.data)
        archive = self.directory / 'old.zip'
        service = BackupService(self.store.path, self.images.directory)
        service.create(archive)
        with zipfile.ZipFile(archive) as package:
            payload = {name: package.read(name) for name in package.namelist()}
        manifest = json.loads(payload['manifest.json'])
        manifest.pop('trash_count', None)
        payload['manifest.json'] = json.dumps(manifest).encode()
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as package:
            for name, value in payload.items():
                package.writestr(name, value)
        self.assertEqual(service.inspect(archive).trash_count, 0)

    def test_optional_future_metadata_images_are_included_and_restored(self):
        name = self.seed()
        self.data['clip'] = []
        self.data['trash'] = {'version': 1, 'items': [], 'future': {'image_path': name}}
        self.store.save(self.data)
        archive = self.directory / 'future.zip'
        service = BackupService(self.store.path, self.images.directory)
        preview = service.create(archive)
        self.assertEqual(preview.image_count, 1)
        target = self.directory / 'future-restored' / 'ClawBoard数据.json'
        target.parent.mkdir()
        JsonStore(target).save(default_data())
        BackupService(target).restore(archive, expected_sha256=preview.sha256)
        self.assertEqual(JsonStore(target).load().data['trash'], self.data['trash'])
        self.assertEqual((target.parent / 'images' / name).read_bytes(), b'synthetic retained image')

    def test_unknown_trash_is_preserved_by_saves_but_rejected_by_complete_backup(self):
        self.data['trash'] = {'version': 9000, 'items': [], 'future': 'untouched'}
        original = dict(self.data['trash'])
        self.app.request_save()
        self.app.flush()
        self.settle()
        self.assertEqual(self.store.load().data['trash'], original)
        self.assertEqual(len(self.errors), 1)
        with self.assertRaises(BackupError):
            BackupService(self.store.path).create(self.directory / 'reject.zip')


if __name__ == '__main__':
    unittest.main()
