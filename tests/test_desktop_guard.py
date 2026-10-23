"""Desktop test isolation contracts; fake handles only, no real clipboard/App."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import windows_test_guard as guard


class DesktopGuardTests(unittest.TestCase):
    def kernel(self, handle):
        return SimpleNamespace(CreateMutexW=Mock(return_value=handle), CloseHandle=Mock())

    def test_existing_instance_is_rejected_and_its_handle_closed(self):
        kernel = self.kernel(0x123456789)
        with self.assertRaises(RuntimeError):
            guard.acquire_desktop_test_lease(kernel=kernel, last_error=lambda: 183)
        kernel.CloseHandle.assert_called_once_with(0x123456789)
        kernel.CreateMutexW.assert_called_once_with(None, False, guard.NAME)

    def test_failed_isolation_is_rejected(self):
        kernel = self.kernel(None)
        with self.assertRaises(RuntimeError):
            guard.acquire_desktop_test_lease(kernel=kernel, last_error=lambda: 5)
        kernel.CloseHandle.assert_not_called()

    def test_success_retains_full_width_handle_until_release(self):
        kernel = self.kernel(0x123456789)
        with patch.object(guard, '_leases', []):
            self.assertEqual(guard.acquire_desktop_test_lease(kernel=kernel, last_error=lambda: 0),
                             0x123456789)
            kernel.CloseHandle.assert_not_called()
            guard._release()
            kernel.CloseHandle.assert_called_once_with(0x123456789)


if __name__ == '__main__':
    unittest.main()
