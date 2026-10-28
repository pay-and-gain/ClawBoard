"""Recycle-bin persistence regression; temporary synthetic data, no App/clipboard."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_trash import TrashTests


def persisted_roundtrip():
    # This explicitly exercises a path-injected storage service. No App is
    # constructed, and the only writable library is inside this temporary dir.
    with tempfile.TemporaryDirectory(prefix='cb-trash-persistence-') as temporary:
        from clawboard import config, runtime
        config.BASE_DIR = temporary
        config.DATA_FILE = str(Path(temporary) / 'ClawBoard数据.json')
        config.CRASH_LOG = str(Path(temporary) / 'crash.log')
        runtime.NO_SAVE = True
        from clawboard.models import default_data
        from clawboard.storage import JsonStore
        from clawboard.trash import TrashService
        data = default_data()
        data['future'] = {'precise': 9007199254740993}
        data['clip'] = [dict(id='synthetic', text='Synthetic deleted 中文 😀',
                             created_at=1234, future={'keep': [1, 2]}),
                        dict(id='bad-known-fields', text='Synthetic bad fields', seq='bad',
                             created_at='bad', updated_at='bad', content_type=1,
                             copy_count='bad', future_bad={'keep': True})]
        data['groups'][0].update(future_group={'keep': True})
        data['groups'][0]['items'] = [dict(id='phrase', text='Synthetic phrase', trigger='cb_test')]
        service = TrashService(data, clock=lambda: 9999)
        moved = service.move(['synthetic', 'bad-known-fields']) + service.move(['phrase'], data['groups'][0])
        path = Path(config.DATA_FILE)
        JsonStore(path).save(data)
        expected_trash = deepcopy(data['trash'])
        child = r'''
import json, sys
from pathlib import Path
from clawboard.storage import JsonStore
from clawboard.trash import TrashService
from clawboard.history import HistoryService
path = Path(sys.argv[1])
loaded = JsonStore(path).load()
assert not loaded.recovery_required
data = loaded.data
assert data['future']['precise'] == 9007199254740993
assert len(data['trash']['items']) == 3 and data['clip'] == []
original = json.dumps(data['trash'], ensure_ascii=False, sort_keys=True)
service = TrashService(data)
assert json.dumps(data['trash'], ensure_ascii=False, sort_keys=True) == original
restored = service.restore([entry['id'] for entry in service.entries()])
assert len(restored) == 3 and not service.entries()
assert data['clip'][0]['future'] == {'keep': [1,2]}
bad = data['clip'][1]
assert isinstance(bad['seq'], int) and isinstance(bad['created_at'], int)
assert isinstance(bad['updated_at'], int) and bad['content_type'] == 'url'
assert bad['copy_count'] == 1 and bad['future_bad'] == {'keep': True}
assert isinstance(HistoryService(data).sequence, int)
assert data['groups'][0]['items'][0]['trigger'] == 'cb_test'
assert data['groups'][0]['future_group'] == {'keep': True}
JsonStore(path).save(data)
print('new process restore and re-save passed')
'''
        result = subprocess.run([sys.executable, '-c', child, str(path)], cwd=ROOT,
                                capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr
        reopened = JsonStore(path).load().data
        from clawboard.history import HistoryService
        assert isinstance(HistoryService(reopened).sequence, int)
        assert reopened['clip'][1]['content_type'] == 'url'
        assert reopened['clip'][0]['id'] == 'synthetic'
        assert reopened['clip'][0]['text'] == 'Synthetic deleted 中文 😀'
        assert reopened['future'] == data['future'] and reopened['trash']['items'] == []
        assert data['trash'] == expected_trash and len(moved) == 3
        assert sorted(item.name for item in Path(temporary).iterdir()) == ['ClawBoard数据.json']
    print('PASS: temporary JSON new-process reload/restore, unknown fields and no extra files')


if __name__ == '__main__':
    outcome = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(TrashTests))
    if not outcome.wasSuccessful():
        raise SystemExit(1)
    persisted_roundtrip()
