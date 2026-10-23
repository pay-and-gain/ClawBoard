"""开发工具，不参与产品运行：从干净提交构建、校验固定白名单的正式 Windows 包。

不启动安装器或真实历史库。输出只在仓库 dist/release-builds 的唯一目录。
"""
import argparse
import ast
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile

ROOT = Path(__file__).absolute().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_preview_bundle import _plain_path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return _plain_path(ROOT, path, file=True).read_bytes()


def version():
    tree = ast.parse(read(ROOT / 'clawboard/config.py').decode('utf-8'))
    value = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == 'APP_VER' for target in node.targets))
    if not re.fullmatch(r'\d+\.\d+\.\d+', value):
        raise ValueError('release version must have three numeric components')
    return value


def checksum(payload):
    return ''.join(sha(data) + '  ' + name + '\n' for name, data in payload.items()).encode('utf-8')


def verify_package(path, label, payload):
    expected = {label + '/' + name for name in payload}
    with zipfile.ZipFile(path) as package:
        entries = package.infolist()
        if len(entries) != len(expected) or {entry.filename for entry in entries} != expected:
            raise ValueError('release ZIP differs from its exact public allowlist')
        if package.testzip() is not None:
            raise ValueError('release ZIP CRC failed')
        for entry in entries:
            if entry.is_dir() or package.read(entry) != payload[Path(entry.filename).name]:
                raise ValueError('release ZIP content differs from reviewed public bytes')


def write_package(path, label, payload):
    if not re.fullmatch(r'ClawBoard-\d+\.\d+\.\d+', label):
        raise ValueError('invalid release archive root')
    common = {'ClawBoard.exe', 'LICENSE.txt', 'README.zh-CN.txt', 'README.en.txt',
              'BUILD-INFO.txt', 'SHA256SUMS.txt'}
    if set(payload) not in (common, common | {label + '-setup.exe'}):
        raise ValueError('release payload differs from the fixed public file allowlist')
    partial = path.with_name(path.name + '.' + uuid.uuid4().hex + '.partial')
    with partial.open('xb') as output:
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as package:
            for name, data in payload.items():
                package.writestr(label + '/' + name, data)
    verify_package(partial, label, payload)
    if os.name == 'nt':
        os.rename(partial, path)
    else:
        os.link(partial, path)
        partial.unlink()
    return dict(name=path.name, bytes=path.stat().st_size, sha256=sha(path.read_bytes()))


def command(arguments, cwd, log):
    started = time.monotonic()
    with log.open('xb') as stream:
        result = subprocess.run(arguments, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT, timeout=180)
    if result.returncode:
        raise RuntimeError('build failed; inspect ' + log.name)
    return round(time.monotonic()-started, 3)


def build():
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True)
    if dirty or not re.fullmatch('[0-9a-f]{40}', revision):
        raise ValueError('commit all intended public changes before a release build')
    ver = version()
    iss = read(ROOT / 'packaging/installer.iss').decode('utf-8')
    if '#define MyAppVersion "' + ver + '"' not in iss:
        raise ValueError('installer version does not match APP_VER')
    notes = ROOT / ('release/release-notes-' + ver + '.md')
    read(notes)
    compiler = Path(os.environ['LOCALAPPDATA']) / 'Programs/Inno Setup 6/ISCC.exe'
    if not compiler.is_file():
        raise ValueError('Inno Setup 6 compiler missing')
    sources = sorted((ROOT / 'clawboard').glob('*.py')) + [ROOT / name for name in (
        'ClawBoard.py', 'query.py', 'transform.py', 'packaging/ClawBoard.spec',
        'packaging/installer.iss', 'packaging/ClawBoard.ico', 'README.md', 'LICENSE',
        'docs/使用说明.md', 'packaging/distribution/README.zh-CN.txt',
        'packaging/distribution/README.en.txt')] + [notes]
    hashes = {str(path.relative_to(ROOT)): sha(read(path)) for path in sources}
    base = ROOT / 'dist/release-builds'
    _plain_path(ROOT, base, missing=True)
    base.mkdir(exist_ok=True)
    stage = base / (ver + '-' + uuid.uuid4().hex)
    stage.mkdir()
    timings = {}
    timings['pyinstaller_seconds'] = command([sys.executable, '-m', 'PyInstaller',
        str(ROOT / 'packaging/ClawBoard.spec'), '--noconfirm', '--clean',
        '--distpath', str(stage / 'dist'), '--workpath', str(stage / 'build')], ROOT, stage / 'pyinstaller.log')
    exe = stage / 'dist/ClawBoard.exe'
    executable = read(exe)
    installer_stage = stage / 'installer-stage'
    for name, data in {'dist/ClawBoard.exe': executable,
                       'packaging/installer.iss': iss.encode('utf-8'),
                       'README.md': read(ROOT / 'README.md'), 'LICENSE': read(ROOT / 'LICENSE'),
                       'docs/使用说明.md': read(ROOT / 'docs/使用说明.md')}.items():
        target = installer_stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as output:
            output.write(data)
    timings['inno_seconds'] = command([str(compiler), str(installer_stage / 'packaging/installer.iss')],
                                      installer_stage, stage / 'inno.log')
    for path in sources:
        if sha(read(path)) != hashes[str(path.relative_to(ROOT))]:
            raise ValueError('source changed during release build')
    assets = stage / 'assets'
    assets.mkdir()
    setup_name = 'ClawBoard-' + ver + '-setup.exe'
    installer = read(installer_stage / 'release' / setup_name)
    (assets / setup_name).write_bytes(installer)
    label = 'ClawBoard-' + ver
    info = ('ClawBoard ' + ver + '\nSource: ' + revision + '\n'
            'Runtime: Python standard library, tkinter, ctypes/Win32\n'
            'Python build: ' + platform.python_version() + '\n'
            'PyInstaller: ' + importlib.metadata.version('pyinstaller') + '\n'
            'Data schema: 3\nLicense: MIT\n'
            'https://github.com/pay-and-gain/ClawBoard/releases/tag/v' + ver + '\n')
    common = {'ClawBoard.exe': executable, 'LICENSE.txt': read(ROOT / 'LICENSE'),
              'README.zh-CN.txt': read(ROOT / 'packaging/distribution/README.zh-CN.txt').replace(
                  b'{version}', ver.encode()),
              'README.en.txt': read(ROOT / 'packaging/distribution/README.en.txt').replace(
                  b'{version}', ver.encode()), 'BUILD-INFO.txt': info.encode()}
    portable = dict(common, **{'SHA256SUMS.txt': checksum(common)})
    complete = dict(common, **{setup_name: installer})
    complete['SHA256SUMS.txt'] = checksum(complete)
    reports = [write_package(assets / (label + '-portable.zip'), label, portable),
               write_package(assets / (label + '-windows.zip'), label, complete)]
    reports.append(dict(name=setup_name, bytes=len(installer), sha256=sha(installer)))
    sums = ''.join(item['sha256'] + '  ' + item['name'] + '\n' for item in reports)
    (assets / 'SHA256SUMS.txt').write_text(sums, encoding='utf-8')
    report = dict(version=ver, source_revision=revision, stage=str(stage), assets=str(assets),
                  executable=str(exe), exe_sha256=sha(executable), sources=hashes,
                  source_unchanged=True, artifacts=reports, **timings)
    (stage / 'build-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'sources'}, indent=2))


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    build()
