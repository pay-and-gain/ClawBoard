"""Preview bundle contracts: synthetic files and temporary/in-memory ZIPs only."""
import contextlib
from dataclasses import replace
import hashlib
import importlib.util
import io
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('preview_bundle_contract', ROOT / 'tools/build_preview_bundle.py')
BUNDLE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BUNDLE
SPEC.loader.exec_module(BUNDLE)
REVISION = '0123456789abcdef' * 2 + '01234567'


class PreviewBundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='cb-preview-contract-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name, relative in BUNDLE.SOURCE_PATHS.items():
            source = self.root / relative
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(('synthetic public file: ' + name).encode())
        config = self.root / 'clawboard/config.py'
        config.parent.mkdir()
        config.write_text("APP_VER = '2.6.1'\n", encoding='utf-8')
        expected = {name: hashlib.sha256((self.root / BUNDLE.SOURCE_PATHS[name]).read_bytes()).hexdigest()
                    for name in BUNDLE.FIXED_SHA256}
        self.addCleanup(patch.stopall)
        patch.dict(BUNDLE.FIXED_SHA256, expected).start()

    def plan(self):
        return BUNDLE.make_plan(self.root, REVISION)

    def memory_zip(self, plan, payload, *, extra=None, corrupt=None, symlink=None, duplicate=None):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as package:
            for name, data in payload.items():
                info = zipfile.ZipInfo(plan.archive_root + '/' + name)
                info.external_attr = ((stat.S_IFLNK if name == symlink else stat.S_IFREG) | 0o644) << 16
                package.writestr(info, b'changed' if name == corrupt else data)
            if extra:
                package.writestr(plan.archive_root + '/' + extra, b'synthetic rejected member')
            if duplicate:
                with contextlib.redirect_stderr(io.StringIO()):
                    package.writestr(plan.archive_root + '/' + duplicate, payload[duplicate])
        stream.seek(0)
        return stream

    def test_check_plan_is_read_only_unique_and_stays_under_repository_dist(self):
        before = set(self.root.rglob('*'))
        first, second = self.plan(), self.plan()
        self.assertEqual(set(self.root.rglob('*')), before)
        self.assertNotEqual(first.output_dir, second.output_dir)
        self.assertEqual(first.output_dir.parent, self.root / 'dist/delivery')
        self.assertIn('2.6.1-refactor-preview', first.archive_name)
        self.assertEqual(BUNDLE.describe_plan(first)['public_files'], list(BUNDLE.PUBLIC_NAMES))
        self.assertFalse(BUNDLE.describe_plan(first)['writes_performed'])

    def test_revision_and_runtime_version_are_checked_without_importing_app(self):
        for invalid in ('', 'a' * 39, 'g' * 40, '../' + 'a' * 40):
            with self.subTest(revision=invalid), self.assertRaises(BUNDLE.BundleError):
                BUNDLE.make_plan(self.root, invalid)
        (self.root / 'clawboard/config.py').write_text("APP_VER='2.6.2'\n", encoding='utf-8')
        with self.assertRaises(BUNDLE.BundleError):
            self.plan()

    def test_fixed_binary_hashes_reject_changed_candidate(self):
        for name in BUNDLE.FIXED_SHA256:
            source = self.root / BUNDLE.SOURCE_PATHS[name]
            original = source.read_bytes()
            source.write_bytes(b'not the reviewed candidate')
            with self.subTest(name=name), self.assertRaises(BUNDLE.BundleError):
                self.plan()
            source.write_bytes(original)
        self.assertFalse((self.root / 'dist/delivery').exists())

    def test_changed_template_after_check_is_rejected_before_any_output(self):
        plan = self.plan()
        (self.root / BUNDLE.SOURCE_PATHS['README.en.txt']).write_text('changed', encoding='utf-8')
        with self.assertRaises(BUNDLE.BundleError):
            BUNDLE.payload_bytes(plan)
        self.assertFalse(plan.output_dir.exists())

    def test_symlink_and_windows_reparse_components_are_rejected(self):
        self.assertTrue(BUNDLE._reparse(SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0)))
        self.assertTrue(BUNDLE._reparse(SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)))
        target = self.root / 'dist'
        original = BUNDLE._reparse
        def reparse(info):
            return original(info) or info.st_ino == target.lstat().st_ino
        with patch.object(BUNDLE, '_reparse', reparse), self.assertRaises(BUNDLE.BundleError):
            self.plan()

    def test_parent_traversal_and_external_output_are_rejected(self):
        with self.assertRaises(BUNDLE.BundleError):
            BUNDLE._plain_path(self.root, self.root / '../outside', missing=True)
        plan = replace(self.plan(), output_dir=self.root.parent / 'outside')
        with self.assertRaises(BUNDLE.BundleError):
            BUNDLE._new_output(plan)

    def test_exact_manifest_ignores_neighboring_fixture_backup_and_logs(self):
        neighbor = (self.root / BUNDLE.SOURCE_PATHS['ClawBoard.exe']).parent
        for name, data in [('ClawBoard数据.json', '{"schema_version":3,"clip":[]}'),
                           ('ClawBoard数据.json.bak', 'synthetic backup'), ('crash.log', 'synthetic log')]:
            (neighbor / name).write_text(data, encoding='utf-8')
        plan = self.plan()
        payload = BUNDLE.payload_bytes(plan)
        self.assertEqual(set(payload), set(BUNDLE.PUBLIC_NAMES))
        self.assertEqual(len(payload), 7)
        self.assertFalse(any(name.endswith(('.json', '.bak', '.log')) for name in payload))
        checksums = payload['SHA256SUMS.txt'].decode().splitlines()
        self.assertEqual(len(checksums), 6)
        for line in checksums:
            digest, name = line.split('  ', 1)
            self.assertEqual(hashlib.sha256(payload[name]).hexdigest(), digest)
        BUNDLE.verify_archive(self.memory_zip(plan, payload), plan, payload)

    def test_final_archive_rejects_extra_json_missing_or_duplicate_files(self):
        plan = self.plan()
        payload = BUNDLE.payload_bytes(plan)
        bad = [self.memory_zip(plan, payload, extra='private.json'),
               self.memory_zip(plan, {k: v for k, v in payload.items() if k != 'LICENSE.txt'}),
               self.memory_zip(plan, payload, duplicate='LICENSE.txt')]
        for archive in bad:
            with self.assertRaises(BUNDLE.BundleError):
                BUNDLE.verify_archive(archive, plan, payload)

    def test_final_archive_rejects_changed_content_and_symlink_members(self):
        plan = self.plan()
        payload = BUNDLE.payload_bytes(plan)
        for archive in (self.memory_zip(plan, payload, corrupt='ClawBoard.exe'),
                        self.memory_zip(plan, payload, symlink='ClawBoard.exe')):
            with self.assertRaises(BUNDLE.BundleError):
                BUNDLE.verify_archive(archive, plan, payload)

    def test_synthetic_build_verifies_partial_before_publishing_matching_final_sha(self):
        plan = self.plan()
        archive = plan.output_dir / plan.archive_name
        verify = BUNDLE.verify_archive
        def verify_partial(path, checked_plan, payload):
            self.assertEqual(path.suffix, '.partial')
            self.assertFalse(archive.exists())
            verify(path, checked_plan, payload)
        with patch.object(BUNDLE, 'verify_archive', side_effect=verify_partial) as checked:
            result = BUNDLE.build_bundle(plan)
        checked.assert_called_once()
        self.assertEqual(result['archive'], str(archive))
        self.assertEqual(result['sha256'], hashlib.sha256(archive.read_bytes()).hexdigest())
        self.assertEqual(list(plan.output_dir.iterdir()), [archive])
        BUNDLE.verify_archive(archive, plan, BUNDLE.payload_bytes(plan))

    def test_synthetic_write_failure_leaves_no_final_zip_or_unrelated_changes(self):
        plan = self.plan()
        sentinel = self.root / 'dist' / 'keep.txt'
        sentinel.write_bytes(b'unrelated content')
        with patch.object(zipfile.ZipFile, 'writestr', side_effect=OSError('synthetic write failure')):
            with self.assertRaises(OSError):
                BUNDLE.build_bundle(plan)
        self.assertFalse((plan.output_dir / plan.archive_name).exists())
        self.assertEqual(len(list(plan.output_dir.glob('*.partial'))), 1)
        self.assertEqual(sentinel.read_bytes(), b'unrelated content')

    def test_synthetic_verification_failure_leaves_no_final_zip(self):
        plan = self.plan()
        with patch.object(BUNDLE, 'verify_archive', side_effect=BUNDLE.BundleError('synthetic mismatch')):
            with self.assertRaises(BUNDLE.BundleError):
                BUNDLE.build_bundle(plan)
        self.assertFalse((plan.output_dir / plan.archive_name).exists())
        self.assertEqual(len(list(plan.output_dir.glob('*.partial'))), 1)

    def test_publication_never_overwrites_a_destination_created_during_verification(self):
        plan = self.plan()
        archive = plan.output_dir / plan.archive_name
        verify = BUNDLE.verify_archive
        def create_conflict(path, checked_plan, payload):
            verify(path, checked_plan, payload)
            archive.write_bytes(b'other writer')
        with patch.object(BUNDLE, 'verify_archive', side_effect=create_conflict):
            with self.assertRaises(FileExistsError):
                BUNDLE.build_bundle(plan)
        self.assertEqual(archive.read_bytes(), b'other writer')
        self.assertEqual(len(list(plan.output_dir.glob('*.partial'))), 1)

    def test_cli_requires_an_explicit_mode(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                BUNDLE.make_parser().parse_args(['--revision', REVISION])
            with self.assertRaises(SystemExit):
                BUNDLE.make_parser().parse_args(['--check', '--build', '--revision', REVISION])
        args = BUNDLE.make_parser().parse_args(['--check', '--revision', REVISION])
        self.assertTrue(args.check)
        self.assertFalse(args.build)


if __name__ == '__main__':
    unittest.main(verbosity=2)
