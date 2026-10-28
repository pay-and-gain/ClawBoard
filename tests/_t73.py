"""Top action bars on standalone synthetic Tk controls; never creates an App."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from tools import windows_test_guard


def run():
    windows_test_guard.acquire_desktop_test_lease()
    try:
        with tempfile.TemporaryDirectory(prefix='cb-top-actions-') as temporary:
            from clawboard import config, runtime
            config.BASE_DIR = temporary
            config.DATA_FILE = str(Path(temporary) / 'ClawBoard数据.json')
            config.CRASH_LOG = str(Path(temporary) / 'crash.log')
            runtime.NO_SAVE = True
            suite = unittest.defaultTestLoader.loadTestsFromName('test_top_actions')
            outcome = unittest.TextTestRunner(verbosity=1).run(suite)
            assert not list(Path(temporary).iterdir()), 'synthetic controls wrote files'
            if not outcome.wasSuccessful():
                raise SystemExit(1)
            result = dict(passed=True, tests=outcome.testsRun,
                          app_created=False, clipboard_accessed=False,
                          temporary_files_unchanged=True,
                          top_actions=True, callback_lifecycle=True,
                          split_enter_space_single_execution=True)
    finally:
        windows_test_guard._release()
    result['lease_released'] = True
    print(json.dumps(result))


if __name__ == '__main__':
    run()
