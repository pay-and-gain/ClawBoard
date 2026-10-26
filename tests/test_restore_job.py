# -*- coding: utf-8 -*-
"""恢复辅助进程回归：只使用临时目录和注入服务，不创建 App 或真实子进程。"""
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clawboard import restore_job as jobs
from clawboard import backup_format as backup_format


class RestoreJobTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.data = self.base / 'ClawBoard数据.json'
        self.data.write_text('{"clip":[{"text":"current fixture"}]}', encoding='utf-8')
        self.original = self.data.read_bytes()
        self.archive = self.base / 'fixture.zip'
        self.archive.write_bytes(b'complete backup fixture')
        self.digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.events = []
        self.active = False
        self.ticket = jobs.prepare_restore_job(self.base, self.archive, self.digest,
                                                parent_pid=0x12345678)

    @contextmanager
    def lease(self, timeout):
        self.assertIn('parent-exited', self.events)
        self.events.append('lease-enter')
        self.active = True
        try:
            yield
        finally:
            self.active = False
            self.events.append('lease-exit')

    def wait(self, pid, timeout):
        self.assertEqual(pid, 0x12345678)
        self.assertEqual(self.data.read_bytes(), self.original)
        self.events.append('parent-exited')
        return True

    def factory(self, data_file, images_dir):
        self.assertTrue(self.active)
        self.assertEqual(data_file, self.data)
        self.assertEqual(images_dir, self.base / 'images')

        def restore(archive, *, expected_sha256):
            self.assertTrue(self.active)
            self.assertEqual(archive, self.archive)
            self.assertEqual(expected_sha256, self.digest)
            self.events.append('restore')
            self.data.write_bytes(b'restored fixture')
            return SimpleNamespace(backup_path=self.base / 'before-restore.zip')
        return SimpleNamespace(restore=restore)

    def restart(self):
        self.assertFalse(self.active)
        self.assertTrue(Path(str(self.ticket) + '.result').is_file())
        self.events.append('restart')

    def run_job(self, **overrides):
        options = dict(wait_parent=self.wait, lease=self.lease,
                       restore_factory=self.factory, restart=self.restart)
        options.update(overrides)
        return jobs.run_restore_job(self.ticket, self.base, **options)

    def edit_ticket(self, **changes):
        payload = json.loads(self.ticket.read_text(encoding='utf-8'))
        payload.update(changes)
        self.ticket.write_text(json.dumps(payload), encoding='utf-8')

    def test_prepare_is_bounded_and_contains_no_target_or_command(self):
        payload = json.loads(self.ticket.read_text(encoding='utf-8'))
        self.assertEqual(self.ticket.parent, self.base / '.restore-jobs')
        self.assertEqual(set(payload), {'version', 'parent_pid', 'archive',
                                        'expected_sha256', 'created_at'})
        self.assertEqual(payload['expected_sha256'], self.digest)
        self.assertEqual(payload['archive'], str(self.archive))
        self.assertEqual(self.data.read_bytes(), self.original)

    def test_success_waits_for_process_then_mutex_then_restore_and_restart(self):
        result = self.run_job()
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['backup_path'], str(self.base / 'before-restore.zip'))
        self.assertEqual(self.events, ['parent-exited', 'lease-enter', 'restore',
                                       'lease-exit', 'restart'])
        report = json.loads(Path(str(self.ticket) + '.result').read_text(encoding='utf-8'))
        self.assertEqual(report, result)

    def test_parent_save_failure_timeout_never_restores_or_restarts(self):
        result = self.run_job(wait_parent=lambda pid, timeout: False)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['error_class'], 'ParentTimeout')
        self.assertEqual(self.events, [])
        self.assertEqual(self.data.read_bytes(), self.original)

    def test_cancel_before_wait_does_not_touch_data_or_restart(self):
        jobs.cancel_restore_job(self.ticket, self.base)
        result = self.run_job()
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['error_class'], 'Cancelled')
        self.assertEqual(self.events, [])
        self.assertEqual(self.data.read_bytes(), self.original)

    def test_cancel_while_parent_alive_does_not_restore_or_restart(self):
        def wait(pid, timeout):
            jobs.cancel_restore_job(self.ticket)
            return False
        result = self.run_job(wait_parent=wait)
        self.assertEqual(result['error_class'], 'Cancelled')
        self.assertEqual(self.events, [])
        self.assertEqual(self.data.read_bytes(), self.original)

    def test_cancel_after_lease_keeps_original_and_restarts_only_after_parent_exit(self):
        @contextmanager
        def cancelling_lease(timeout):
            with self.lease(timeout):
                jobs.cancel_restore_job(self.ticket)
                yield
        result = self.run_job(lease=cancelling_lease)
        self.assertEqual(result['error_class'], 'Cancelled')
        self.assertEqual(self.events, ['parent-exited', 'lease-enter', 'lease-exit', 'restart'])
        self.assertEqual(self.data.read_bytes(), self.original)

    def test_cancellation_between_service_setup_and_restore_is_honoured(self):
        def factory(data_file, images_dir):
            service = self.factory(data_file, images_dir)
            jobs.cancel_restore_job(self.ticket)
            return service
        result = self.run_job(restore_factory=factory)
        self.assertEqual(result['error_class'], 'Cancelled')
        self.assertNotIn('restore', self.events)
        self.assertEqual(self.data.read_bytes(), self.original)

    def test_changed_archive_is_rejected_with_original_data_and_safe_report(self):
        self.archive.write_bytes(b'changed after confirmation')
        result = self.run_job()
        self.assertEqual(result['error_class'], 'ArchiveChanged')
        self.assertEqual(self.data.read_bytes(), self.original)
        self.assertNotIn('restore', self.events)
        self.assertEqual(self.events[-1], 'restart')

    def test_archive_over_size_limit_is_rejected_before_opening(self):
        with patch.object(backup_format, 'MAX_ARCHIVE_BYTES', 16), \
                patch.object(jobs, '_plain', return_value=SimpleNamespace(st_size=17)), \
                patch.object(Path, 'open') as opened:
            with self.assertRaises(jobs.RestoreJobError) as caught:
                jobs._check_archive(self.archive, self.digest)
        self.assertEqual(caught.exception.code, 'ArchiveChanged')
        opened.assert_not_called()

    def test_archive_growing_after_stat_reads_only_limit_plus_one_byte(self):
        stream = io.BytesIO(b'x' * 64)
        with patch.object(backup_format, 'MAX_ARCHIVE_BYTES', 8), \
                patch.object(jobs, '_plain', return_value=SimpleNamespace(st_size=4)), \
                patch.object(Path, 'open', return_value=stream), \
                patch.object(stream, 'read', wraps=stream.read) as read:
            with self.assertRaises(jobs.RestoreJobError) as caught:
                jobs._check_archive(self.archive, self.digest)
        self.assertEqual(caught.exception.code, 'ArchiveChanged')
        read.assert_called_once_with(9)

    def test_restore_error_is_fixed_message_without_exception_content(self):
        class FixtureFailure(Exception):
            pass

        def factory(data_file, images_dir):
            def restore(*args, **kwargs):
                raise FixtureFailure('private clipboard fixture must not appear')
            return SimpleNamespace(restore=restore)
        result = self.run_job(restore_factory=factory)
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error_class'], 'FixtureFailure')
        self.assertNotIn('private', json.dumps(result))
        self.assertEqual(self.events[-1], 'restart')

    def test_unknown_target_and_command_are_rejected(self):
        self.edit_ticket(command=['untrusted.exe'], target=str(self.base / 'other.json'))
        result = self.run_job()
        self.assertEqual(result['error_class'], 'InvalidJob')
        self.assertEqual(self.events, [])
        self.assertEqual(self.data.read_bytes(), self.original)

    def test_invalid_ticket_fields_are_rejected(self):
        for change in ({'version': 99}, {'version': True}, {'parent_pid': 0},
                       {'parent_pid': os.getpid()}, {'parent_pid': True},
                       {'expected_sha256': 'a' * 63}, {'archive': '../fixture.zip'},
                       {'created_at': time.time() - jobs.JOB_TTL - 10},
                       {'created_at': time.time() + 90}, {'created_at': float('nan')}):
            with self.subTest(change=change):
                original = self.ticket.read_bytes()
                self.edit_ticket(**change)
                result = self.run_job()
                self.assertEqual(result['error_class'], 'InvalidJob')
                self.assertEqual(self.events, [])
                Path(str(self.ticket) + '.running').unlink()
                Path(str(self.ticket) + '.result').unlink()
                self.ticket.write_bytes(original)

    def test_outside_or_non_uuid_ticket_is_not_read_and_no_result_is_created(self):
        outside = self.base / self.ticket.name
        outside.write_bytes(self.ticket.read_bytes())
        result = jobs.run_restore_job(outside, self.base)
        self.assertEqual(result['status'], 'error')
        self.assertFalse(Path(str(outside) + '.result').exists())
        named = self.ticket.with_name('other.json')
        named.write_bytes(self.ticket.read_bytes())
        with self.assertRaises(jobs.RestoreJobError):
            jobs.cancel_restore_job(named, self.base)

    def test_replay_cannot_restore_twice_or_overwrite_report(self):
        self.run_job()
        report = Path(str(self.ticket) + '.result').read_bytes()
        self.events.clear()
        result = self.run_job()
        self.assertEqual(result['error_class'], 'AlreadyRunning')
        self.assertEqual(Path(str(self.ticket) + '.result').read_bytes(), report)
        self.assertEqual(self.events, [])

    def test_mutex_contention_never_calls_restore(self):
        @contextmanager
        def busy(timeout):
            raise jobs.RestoreJobError('MutexTimeout')
            yield
        result = self.run_job(lease=busy)
        self.assertEqual(result['error_class'], 'MutexTimeout')
        self.assertNotIn('restore', self.events)
        self.assertEqual(self.data.read_bytes(), self.original)
        self.assertEqual(self.events, ['parent-exited'])

    def test_parent_wait_error_never_restarts(self):
        def broken_wait(pid, timeout):
            raise jobs.RestoreJobError('ParentWaitError')
        result = self.run_job(wait_parent=broken_wait)
        self.assertEqual(result['error_class'], 'ParentWaitError')
        self.assertEqual(self.events, [])

    def test_launch_uses_current_program_and_no_shell_or_visible_console(self):
        with patch.object(jobs.subprocess, 'Popen') as popen:
            returned = jobs.launch_restore_job(self.ticket)
        args, options = popen.call_args
        self.assertIs(returned, popen.return_value)
        self.assertEqual(args[0][0], sys.executable)
        self.assertEqual(args[0][-2:], ['--restore-job', str(self.ticket)])
        self.assertFalse(options['shell'])
        self.assertEqual(options['stdout'], subprocess.DEVNULL)
        if os.name == 'nt':
            self.assertTrue(options['creationflags'] & subprocess.CREATE_NO_WINDOW)
        with patch.object(jobs.sys, 'frozen', True, create=True):
            self.assertEqual(jobs._program_command(), [sys.executable])

    def test_restart_failure_preserves_successful_restore_and_records_failure(self):
        def fail_restart():
            raise OSError('sensitive fixture error')
        result = self.run_job(restart=fail_restart)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['restart_error'], 'RestartFailed')
        saved = json.loads(Path(str(self.ticket) + '.result').read_text(encoding='utf-8'))
        self.assertEqual(saved, result)
        self.assertNotIn('sensitive', json.dumps(saved))

    def test_consume_latest_once_and_keep_unknown_or_broken_files(self):
        self.run_job()
        first_report = Path(str(self.ticket) + '.result')
        first = json.loads(first_report.read_text(encoding='utf-8'))
        other_ticket = jobs.prepare_restore_job(self.base, self.archive, self.digest,
                                                parent_pid=0x12345678)
        second_report = Path(str(other_ticket) + '.result')
        second = dict(first, completed_at=first['completed_at'] + 1, job_id=other_ticket.stem)
        second_report.write_text(json.dumps(second), encoding='utf-8')
        unknown = self.ticket.parent / 'unknown.json.result'
        unknown.write_text('{"private":"fixture"}', encoding='utf-8')
        broken_ticket = jobs.prepare_restore_job(self.base, self.archive, self.digest,
                                                 parent_pid=0x12345678)
        broken = Path(str(broken_ticket) + '.result')
        broken.write_text('not json', encoding='utf-8')
        consumed = jobs.consume_restore_result(self.base)
        self.assertEqual(consumed, second)
        self.assertIsNone(jobs.consume_restore_result(self.base))
        self.assertTrue(Path(str(first_report) + '.seen').exists())
        self.assertTrue(Path(str(second_report) + '.seen').exists())
        self.assertTrue(unknown.exists())
        self.assertTrue(broken.exists())

    def test_consume_missing_directory_has_no_side_effect(self):
        other = self.base / 'empty'
        other.mkdir()
        self.assertIsNone(jobs.consume_restore_result(other))
        self.assertEqual(list(other.iterdir()), [])

    def test_prepare_rejects_invalid_hash_without_creating_ticket(self):
        before = set(self.ticket.parent.iterdir())
        with self.assertRaises(jobs.RestoreJobError):
            jobs.prepare_restore_job(self.base, self.archive, 'bad')
        self.assertEqual(set(self.ticket.parent.iterdir()), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
