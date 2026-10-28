"""Merge import regression: temporary data, real save and a fresh reader process."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))


def run():
    from clawboard.import_service import ImportService
    with tempfile.TemporaryDirectory(prefix='cb-import-reload-') as temporary:
        base = Path(temporary)
        target = base / 'ClawBoard数据.json'
        data = dict(schema_version=3, clip=[dict(id='keep', text='KEEP current')],
                    groups=[dict(name='默认', items=[])],
                    settings=dict(max_items=500, theme='dark'), future={'keep': True})
        target.write_text(json.dumps(data), encoding='utf-8')
        source = base / 'export.json'
        source.write_text(json.dumps(dict(version=3, items=[dict(
            id='keep', text='Synthetic imported 中文 😀', future={'keep': 'new'})])), encoding='utf-8')
        service = ImportService(target)
        preview = service.inspect(source, data)
        result = service.merge(source, preview.source.sha256, ['c:0'])
        assert result.imported_count == 1 and result.backup_path.is_file()
        code = ('import json,sys;from pathlib import Path;'
                'sys.path.insert(0,sys.argv[1]);from clawboard.storage import JsonStore;'
                'data=JsonStore(Path(sys.argv[2])).load().data;'
                'assert len(data["clip"])==2;'
                'assert len({x["id"] for x in data["clip"]})==2;'
                'assert data["future"]=={"keep":True};'
                'assert data["settings"]["theme"]=="dark";'
                'assert any(x["future"]=={"keep":"new"} for x in data["clip"] if "future" in x);'
                'print("PASS: fresh-process imported records, IDs, settings and unknown fields")')
        completed = subprocess.run([sys.executable, '-c', code, str(ROOT), str(target)],
                                   cwd=base, capture_output=True, text=True, timeout=30)
        assert completed.returncode == 0, completed.stderr
        print(completed.stdout.strip())
    suite = unittest.TestSuite()
    for module in ('test_import_source', 'test_import_merge', 'test_import_service', 'test_import_dialog'):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromName(module))
    if not unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful():
        raise SystemExit(1)


if __name__ == '__main__':
    run()
