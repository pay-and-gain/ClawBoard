"""Desktop isolation regression: fake contracts and real mutex; no App/clipboard."""
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import test_desktop_guard
from tools import windows_test_guard as guard


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromModule(test_desktop_guard))
    if not result.wasSuccessful():
        sys.exit(1)
    if os.name == 'nt':
        probe = ('from tools.windows_test_guard import acquire_desktop_test_lease\n'
                 'try:\n acquire_desktop_test_lease()\n'
                 'except RuntimeError:\n raise SystemExit(3)\n')
        guard.acquire_desktop_test_lease()
        try:
            assert subprocess.run([sys.executable, '-c', probe], cwd=ROOT).returncode == 3
        finally:
            guard._release()
        assert subprocess.run([sys.executable, '-c', probe], cwd=ROOT).returncode == 0
        print('native mutex: competing process blocked; released lease permits next process')
