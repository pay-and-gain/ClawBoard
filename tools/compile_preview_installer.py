"""开发工具，不参与产品运行：在仓库唯一临时目录编译安装包，不执行安装。"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).absolute().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_preview_bundle import SOURCE_PATHS, FIXED_SHA256, _plain_path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    compiler = Path(os.environ['LOCALAPPDATA']) / 'Programs/Inno Setup 6/ISCC.exe'
    if not compiler.is_file():
        raise ValueError('Inno Setup compiler not found')
    sources = {
        'dist/ClawBoard.exe': ROOT / SOURCE_PATHS['ClawBoard.exe'],
        'packaging/installer.iss': ROOT / 'packaging/installer.iss',
        'README.md': ROOT / 'README.md',
        'LICENSE': ROOT / 'LICENSE',
        'docs/使用说明.md': ROOT / 'docs/使用说明.md',
    }
    hashes = {}
    for name, path in sources.items():
        _plain_path(ROOT, path, file=True)
        hashes[name] = digest(path)
    if hashes['dist/ClawBoard.exe'] != FIXED_SHA256['ClawBoard.exe']:
        raise ValueError('portable executable differs from reviewed build')
    base = ROOT / 'dist/windows-validation'
    _plain_path(ROOT, base)
    output = base / ('installer-noicons-' + uuid.uuid4().hex)
    output.mkdir()
    stage = output / 'stage'
    stage.mkdir()
    for name, path in sources.items():
        target = stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        if digest(target) != hashes[name]:
            raise ValueError('staged source hash mismatch')
    (output / 'inputs.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
    started = time.monotonic()
    with (output / 'inno.log').open('xb') as log:
        result = subprocess.run([str(compiler), str(stage / 'packaging/installer.iss')],
                                cwd=stage, stdout=log, stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        raise ValueError('compiler failed; inspect this session log')
    for name, path in sources.items():
        if digest(path) != hashes[name]:
            raise ValueError('source changed during compile')
    installer = stage / 'release/ClawBoard-2.6.1-setup.exe'
    _plain_path(ROOT, installer, file=True)
    report = dict(installer=str(installer), sha256=digest(installer),
                  bytes=installer.stat().st_size, seconds=round(time.monotonic() - started, 3),
                  exit_code=result.returncode, sources_unchanged=True,
                  installer_executed=False)
    (output / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
