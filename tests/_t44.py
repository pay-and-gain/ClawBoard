"""Service-refactor regression entry; synthetic data only, no Windows App created.

Run: python tests/_t44.py. Windows re-export compatibility is additionally loaded
on Windows; native desktop scenarios still need the dedicated GUI scripts.
"""
import os
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))


class NativeCompatibility(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows re-export compatibility needs winreg/Win32')
    def test_native_compatibility(self):
        # The native module's full suite is included below on Windows.
        pass


def suite():
    loader = unittest.TestLoader()
    tests = unittest.TestSuite()
    for path in sorted(HERE.glob('test_*.py')):
        if path.stem == 'test_refactor' and os.name != 'nt':
            continue
        tests.addTests(loader.loadTestsFromName(path.stem))
    if os.name != 'nt':
        tests.addTests(loader.loadTestsFromTestCase(NativeCompatibility))
    return tests


if __name__ == '__main__':
    outcome = unittest.TextTestRunner(verbosity=2).run(suite())
    sys.exit(0 if outcome.wasSuccessful() else 1)
