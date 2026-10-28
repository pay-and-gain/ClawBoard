"""Startup restore boundaries without constructing App or opening a real library."""
import ast
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clawboard.backup_startup import run_restore_mode, recover_before_start, consume_notice, recovery_notice


class BackupStartupTests(unittest.TestCase):
    def test_helper_dispatch_requires_exact_mode_and_obeys_no_save(self):
        with patch('clawboard.restore_job.run_restore_job', return_value={'status': 'success'}) as run:
            self.assertIsNone(run_restore_mode([], 'synthetic'))
            for arguments in (['--restore-job'], ['--bench', '--restore-job', 'ticket'],
                              ['--restore-job', 'ticket', 'extra']):
                self.assertEqual(run_restore_mode(arguments, 'synthetic'), 2)
            self.assertEqual(run_restore_mode(['--restore-job', 'ticket'], 'synthetic', no_save=True), 2)
            run.assert_not_called()
            self.assertEqual(run_restore_mode(['--restore-job', 'ticket'], 'synthetic'), 0)
            run.assert_called_once_with('ticket', 'synthetic')

    def test_helper_failure_returns_nonzero(self):
        with patch('clawboard.restore_job.run_restore_job', return_value={'status': 'error'}):
            self.assertEqual(run_restore_mode(['--restore-job', 'ticket'], 'synthetic'), 1)

    def test_recovery_only_for_existing_journal_and_never_in_no_save(self):
        with tempfile.TemporaryDirectory(prefix='cb-startup-') as temporary:
            base = Path(temporary)
            with patch('clawboard.backups.BackupService') as service:
                self.assertIsNone(recover_before_start(base))
                (base / '.clawboard-restore-journal.json').write_text('{}')
                self.assertIsNone(recover_before_start(base, no_save=True))
                service.assert_not_called()
                recover_before_start(base)
                service.assert_called_once_with(base / 'ClawBoard数据.json')
                service.return_value.recover_pending.assert_called_once_with()

    def test_notice_once_and_never_in_no_save(self):
        with tempfile.TemporaryDirectory(prefix='cb-startup-') as temporary:
            base = Path(temporary)
            (base / '.restore-jobs').mkdir()
            with patch('clawboard.restore_job.consume_restore_result',
                       return_value={'status': 'success', 'backup_path': str(base / 'before.zip')}) as consume:
                self.assertIsNone(consume_notice(base, no_save=True))
                consume.assert_not_called()
                title, text, warning = consume_notice(base)
                self.assertIn('完成', title)
                self.assertIn('before.zip', text)
                self.assertFalse(warning)

    def test_error_notice_does_not_echo_arbitrary_exception_content(self):
        with tempfile.TemporaryDirectory(prefix='cb-startup-') as temporary:
            base = Path(temporary)
            (base / '.restore-jobs').mkdir()
            with patch('clawboard.restore_job.consume_restore_result',
                       return_value={'status': 'error', 'message': 'synthetic-private-content'}):
                _, text, warning = consume_notice(base)
                self.assertNotIn('synthetic-private-content', text)
                self.assertTrue(warning)

    def test_interrupted_restore_reports_rollback_or_completed_commit(self):
        self.assertIsNone(recovery_notice(None))
        recovery = SimpleNamespace(status='rolled_back', backup_path=Path('synthetic-before.zip'),
                                   cleanup_pending=False)
        title, text, warning = recovery_notice(recovery)
        self.assertIn('回退', title)
        self.assertIn('synthetic-before.zip', text)
        self.assertTrue(warning)
        recovery.status = 'committed'
        self.assertFalse(recovery_notice(recovery)[2])
        recovery.cleanup_pending = True
        self.assertTrue(recovery_notice(recovery)[2])

    def _main(self):
        tree = ast.parse((ROOT / 'ClawBoard.py').read_text(encoding='utf-8'))
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
        root = SimpleNamespace(withdraw=Mock(), destroy=Mock())
        namespace = dict(sys=SimpleNamespace(argv=['ClawBoard.py']), BASE_DIR='synthetic',
                         runtime=SimpleNamespace(NO_SAVE=False), init_dpi_awareness=Mock(),
                         install_excepthook=Mock(), single_instance=Mock(return_value=True),
                         tk=SimpleNamespace(Tk=Mock(return_value=root)), bench=Mock(),
                         ClawBoard=Mock(side_effect=AssertionError('App must not be constructed')))
        exec(compile(ast.Module(body=[main], type_ignores=[]), 'startup-contract', 'exec'), namespace)
        return namespace, root

    def test_unrecoverable_transaction_stops_before_app_load(self):
        namespace, root = self._main()
        with (patch('clawboard.backup_startup.recover_before_start', side_effect=OSError('synthetic')),
              patch('tkinter.messagebox.showerror') as message):
            self.assertEqual(namespace['main'](), 1)
        namespace['ClawBoard'].assert_not_called()
        root.destroy.assert_called_once_with()
        message.assert_called_once()

    def test_bench_bypasses_library_recovery(self):
        namespace, _ = self._main()
        namespace['sys'].argv.append('--bench')
        with patch('clawboard.backup_startup.recover_before_start') as recover:
            namespace['main']()
        recover.assert_not_called()
        namespace['bench'].assert_called_once_with()
        namespace['single_instance'].assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
