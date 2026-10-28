"""Complete backup regression entry; synthetic temporary libraries, no App."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_backups import BackupTests


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BackupTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
