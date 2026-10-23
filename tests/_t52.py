"""Formal release ZIP allowlist and byte-integrity regression, synthetic files only."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_release_bundle import ReleaseBundleTests

if __name__ == '__main__':
    outcome = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ReleaseBundleTests))
    sys.exit(0 if outcome.wasSuccessful() else 1)
