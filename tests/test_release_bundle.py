"""Release archives must expose only reviewed public bytes and preserve existing files."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import build_release as release


class ReleaseBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'public.zip'
        self.label = 'ClawBoard-2.7.0'
        self.payload = {'ClawBoard.exe': b'MZ synthetic', 'LICENSE.txt': b'MIT',
                        'README.zh-CN.txt': '中文说明'.encode(), 'README.en.txt': b'Guide',
                        'BUILD-INFO.txt': b'synthetic commit'}
        self.payload['SHA256SUMS.txt'] = release.checksum(self.payload)

    def test_portable_and_complete_archives_have_exact_bytes_and_checksums(self):
        for setup in (False, True):
            with self.subTest(setup=setup):
                payload = dict(self.payload)
                if setup:
                    payload[self.label + '-setup.exe'] = b'MZ synthetic installer'
                    payload['SHA256SUMS.txt'] = release.checksum(
                        {k: v for k, v in payload.items() if k != 'SHA256SUMS.txt'})
                target = self.path.with_name(str(setup) + '.zip')
                report = release.write_package(target, self.label, payload)
                release.verify_package(target, self.label, payload)
                self.assertEqual(report['sha256'], release.sha(target.read_bytes()))
                with zipfile.ZipFile(target) as archive:
                    self.assertEqual(len(archive.infolist()), 7 if setup else 6)
                    sums = archive.read(self.label + '/SHA256SUMS.txt').decode().splitlines()
                    for line in sums:
                        digest, name = line.split('  ', 1)
                        self.assertEqual(digest, release.sha(archive.read(self.label + '/' + name)))

    def test_unknown_private_or_traversal_files_are_rejected_before_output(self):
        for name in ('ClawBoard数据.json', 'events.log', 'backup.zip', 'secret.txt', '../secret'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                release.write_package(self.path, self.label, dict(self.payload, **{name: b'private'}))
        with self.assertRaises(ValueError):
            release.write_package(self.path, '../ClawBoard', self.payload)
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.path.parent.iterdir()), [])

    def test_existing_delivery_is_never_overwritten(self):
        self.path.write_bytes(b'existing delivery')
        with self.assertRaises(FileExistsError):
            release.write_package(self.path, self.label, self.payload)
        self.assertEqual(self.path.read_bytes(), b'existing delivery')

    def test_extra_zip_entry_and_changed_bytes_fail_verification(self):
        release.write_package(self.path, self.label, self.payload)
        changed = dict(self.payload, **{'ClawBoard.exe': b'different'})
        with self.assertRaises(ValueError):
            release.verify_package(self.path, self.label, changed)
        with zipfile.ZipFile(self.path, 'a') as archive:
            archive.writestr(self.label + '/private.json', b'{}')
        with self.assertRaises(ValueError):
            release.verify_package(self.path, self.label, self.payload)

    def test_failed_verification_never_publishes_a_final_archive(self):
        with patch.object(release, 'verify_package', side_effect=ValueError('CRC failure')):
            with self.assertRaises(ValueError):
                release.write_package(self.path, self.label, self.payload)
        self.assertFalse(self.path.exists())


if __name__ == '__main__':
    unittest.main()
