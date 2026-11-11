"""Long-email privacy regression entry; synthetic services only, no App/clipboard."""
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromName('test_privacy_email')
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if outcome.wasSuccessful() else 1)
