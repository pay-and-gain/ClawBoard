"""开发工具，不参与产品运行：记录独立目录安装验收，不执行安装、提权或删除。

prepare 仅创建本次会话；check-installed 写入合成数据并验证存储往返；
check-uninstalled 核对保留数据及安装登记清理。任何阶段都不构造 App。
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
import winreg

ROOT = Path(__file__).absolute().parents[1]
sys.path.insert(0, str(ROOT))
from tools.upgrade_portable import _safe_path

APP_ID = '{8A3F2B14-6C7D-4E59-9F21-3B8D5A7C4E16}_is1'
UNINSTALL = 'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\' + APP_ID
RUN = 'Software\\Microsoft\\Windows\\CurrentVersion\\Run'
VALIDATION = ROOT / 'dist' / 'windows-validation'


def digest(path):
    return hashlib.sha256(_safe_path(path).read_bytes()).hexdigest()


def registry():
    entries = []
    for hive_name, hive in (('HKCU', winreg.HKEY_CURRENT_USER), ('HKLM', winreg.HKEY_LOCAL_MACHINE)):
        for bits, view in ((32, winreg.KEY_WOW64_32KEY), (64, winreg.KEY_WOW64_64KEY)):
            try:
                with winreg.OpenKey(hive, UNINSTALL, 0, winreg.KEY_READ | view) as key:
                    values = {}
                    for name in ('InstallLocation', 'UninstallString', 'DisplayName'):
                        values[name] = winreg.QueryValueEx(key, name)[0]
                    entries.append(dict(hive=hive_name, bits=bits, **values))
            except FileNotFoundError:
                pass
    return entries


def run_value():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN) as key:
            value, kind = winreg.QueryValueEx(key, 'ClawBoard')
        return dict(value=value, kind=kind)
    except FileNotFoundError:
        return None


def shortcuts():
    paths = [Path(os.environ['ProgramData']) / 'Microsoft/Windows/Start Menu/Programs/ClawBoard',
             Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/ClawBoard',
             Path.home() / 'Desktop/ClawBoard.lnk',
             Path(os.environ['PUBLIC']) / 'Desktop/ClawBoard.lnk']
    return {str(path): path.exists() or path.is_symlink() for path in paths}


def real_data():
    result = {}
    for base in (ROOT, Path.home() / 'Desktop/cut', Path(os.environ['APPDATA']) / 'ClawBoard'):
        data = base / 'ClawBoard数据.json'
        result[str(data)] = digest(data) if data.exists() else None
        images = base / 'images'
        if images.exists():
            _safe_path(images, directory=True)
            for path in sorted(images.iterdir()):
                result[str(path)] = digest(path)
        result[str(images)] = images.exists()
    return result


def write_new(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=True, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())


def unchanged(document):
    if real_data() != document['real_data'] or run_value() != document['run']:
        raise ValueError('real data or original startup setting changed')
    if shortcuts() != document['shortcuts']:
        raise ValueError('unexpected shortcut was created')


def session_document(session):
    session = _safe_path(session, directory=True)
    if session.parent != VALIDATION or not re.fullmatch(r'install-cycle-[0-9a-f]{32}', session.name):
        raise ValueError('session must be this repository validation child')
    document = json.loads(_safe_path(session / 'manifest.json').read_text(encoding='utf-8'))
    if document['target'] != str(session / 'installed'):
        raise ValueError('installation target is outside this session')
    return session, document


def prepare(installer, installer_sha256, exe_sha256):
    from tools.windows_test_guard import acquire_desktop_test_lease
    acquire_desktop_test_lease()
    installer = _safe_path(installer)
    if not any(installer.is_relative_to(base) for base in
               (VALIDATION, ROOT / 'dist/release-builds')):
        raise ValueError('installer must be inside repository validation or release build directory')
    if not all(re.fullmatch('[0-9a-f]{64}', value) for value in (installer_sha256, exe_sha256)):
        raise ValueError('full reviewed SHA256 values are required')
    if digest(installer) != installer_sha256:
        raise ValueError('installer hash differs from reviewed build')
    if registry() or any(shortcuts().values()):
        raise ValueError('existing installation or shortcut prevents isolated local validation')
    # The fixed AppId and data-preserving uninstall behavior are audited before launch.
    script = (ROOT / 'packaging/installer.iss').read_text(encoding='utf-8')
    if ('if UninstallSilent then' not in script or 'CompareText(RunCommand, InstalledExe)' not in script
            or 'AllowNoIcons=yes' not in script):
        raise ValueError('safe uninstall source guards are missing')
    _safe_path(VALIDATION, directory=True)
    baseline = dict(real_data=real_data(), run=run_value(), shortcuts=shortcuts())
    session = VALIDATION / ('install-cycle-' + uuid.uuid4().hex)
    session.mkdir()
    target = session / 'installed'
    arguments = ['/VERYSILENT', '/SP-', '/SUPPRESSMSGBOXES', '/NORESTART',
                 '/NOCLOSEAPPLICATIONS', '/NORESTARTAPPLICATIONS', '/NOICONS',
                 '/TASKS=""', '/LANG=english', '/DIR="' + str(target) + '"',
                 '/LOG="' + str(session / 'install.log') + '"']
    document = dict(format=1, installer=str(installer), installer_sha256=installer_sha256,
                    exe_sha256=exe_sha256, target=str(target), arguments=arguments, **baseline)
    write_new(session / 'manifest.json', document)
    return dict(session=str(session), installer=str(installer), arguments=arguments,
                target=str(target), writes_only_in_session=True)


def installed(session):
    session, document = session_document(session)
    target = _safe_path(Path(document['target']), directory=True)
    if digest(target / 'ClawBoard.exe') != document['exe_sha256']:
        raise ValueError('installed executable differs from reviewed build')
    entries = registry()
    if not entries:
        raise ValueError('installation registration is missing')
    uninstaller = str(target / 'unins000.exe')
    for entry in entries:
        if (Path(entry['InstallLocation']) != target or
                entry['UninstallString'].strip('"').casefold() != uninstaller.casefold()):
            raise ValueError('installation registration points elsewhere')
    _safe_path(target / 'unins000.exe')
    unchanged(document)
    if (target / 'ClawBoard数据.json').exists() or (target / 'images').exists():
        raise ValueError('synthetic fixture destination already exists')
    from clawboard.storage import JsonStore
    from clawboard.models import default_data
    data = default_data()
    data['settings'].update(listen=False, trigger_enabled=False, update_check=False)
    data['clip'] = [dict(id='installer-clip', text='Synthetic install validation 😀',
                         content_type='text', created_at=1700000000000, unknown={'keep': True})]
    data['groups'] = [dict(name='Synthetic group', items=[dict(
        id='installer-phrase', text='Synthetic phrase', trigger='cbinstall', created_at=1700000000001)])]
    data['validation_unknown'] = ['preserve', {'ordered': [3, 1, 2]}]
    path = target / 'ClawBoard数据.json'
    store = JsonStore(path)
    store.save(data)
    first = JsonStore(path).load()
    if first.recovery_required or first.data['validation_unknown'] != data['validation_unknown']:
        raise ValueError('synthetic storage reload failed')
    store.save(first.data)
    second = JsonStore(path).load()
    if second.recovery_required or second.data != first.data:
        raise ValueError('synthetic second reload failed')
    images = target / 'images'
    images.mkdir()
    with (images / 'synthetic.png').open('xb') as stream:
        stream.write(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='))
    fixture = {str(p.relative_to(target)): digest(p) for p in (path, images / 'synthetic.png')}
    unchanged(document)
    result = dict(state='installed-verified', synthetic_fixture=fixture,
                  storage_save_reload_passed=True, real_data_unchanged=True,
                  startup_unchanged=True, shortcuts_unchanged=True, registration=entries,
                  uninstaller=uninstaller)
    write_new(session / 'installed-result.json', result)
    return dict(state=result['state'], uninstaller=uninstaller,
                uninstall_arguments=['/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                                     '/LOG="' + str(session / 'uninstall.log') + '"'],
                storage_save_reload_passed=True, real_data_unchanged=True, startup_unchanged=True)


def uninstalled(session, *, aborted=False):
    session, document = session_document(session)
    target = Path(document['target'])
    if target.exists():
        _safe_path(target, directory=True)
    result = ({} if aborted else json.loads(
        _safe_path(session / 'installed-result.json').read_text(encoding='utf-8')))
    if registry() or any(target.glob('*.exe')) or any(target.glob('unins*')):
        raise ValueError('installation files or registration remain')
    for relative, expected in result.get('synthetic_fixture', {}).items():
        if digest(target / relative) != expected:
            raise ValueError('synthetic data was not retained')
    unchanged(document)
    report = dict(state='aborted-cycle-cleaned' if aborted else 'uninstalled-verified',
                  synthetic_data_retained=None if aborted else True,
                  registration_removed=True, real_data_unchanged=True,
                  startup_unchanged=True, shortcuts_unchanged=True)
    write_new(session / 'uninstalled-result.json', report)
    return report


def smoke(session):
    session, document = session_document(session)
    target = _safe_path(Path(document['target']), directory=True)
    verified = json.loads(_safe_path(session / 'installed-result.json').read_text(encoding='utf-8'))
    exe = target / 'ClawBoard.exe'
    if digest(exe) != document['exe_sha256']:
        raise ValueError('installed executable hash changed')
    unchanged(document)
    environment = os.environ.copy()
    for name in ('APPDATA', 'LOCALAPPDATA', 'TEMP', 'TMP'):
        directory = session / ('child-' + name.lower())
        directory.mkdir(exist_ok=True)
        _safe_path(directory, directory=True)
        environment[name] = str(directory)
    # --bench sets runtime.NO_SAVE before App construction. The existing synthetic
    # fixture disables capture, triggers and update checks; child paths are isolated.
    started = time.monotonic()
    with (session / 'smoke.log').open('xb') as output:
        process = subprocess.Popen([str(exe), '--bench'], cwd=target, env=environment,
                                   stdout=output, stderr=subprocess.STDOUT)
        try:
            code = process.wait(timeout=45)
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            process.wait(timeout=10)
            raise ValueError('owned smoke process timed out')
    if code != 0 or (target / 'crash.log').exists():
        raise ValueError('installed executable smoke failed')
    for relative, expected in verified['synthetic_fixture'].items():
        if digest(target / relative) != expected:
            raise ValueError('NO_SAVE synthetic fixture changed')
    unchanged(document)
    result = dict(state='installed-smoke-passed', exit_code=code,
                  seconds=round(time.monotonic() - started, 3), no_save_fixture_unchanged=True,
                  real_data_unchanged=True, startup_unchanged=True)
    write_new(session / 'smoke-result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    start = commands.add_parser('prepare')
    start.add_argument('--installer', required=True, type=Path)
    start.add_argument('--installer-sha256', required=True)
    start.add_argument('--exe-sha256', required=True)
    for name in ('check-installed', 'check-uninstalled', 'check-aborted', 'smoke'):
        commands.add_parser(name).add_argument('--session', required=True, type=Path)
    args = parser.parse_args()
    if args.command == 'prepare':
        result = prepare(args.installer, args.installer_sha256, args.exe_sha256)
    elif args.command == 'smoke':
        result = smoke(args.session)
    else:
        result = (installed(args.session) if args.command == 'check-installed'
                  else uninstalled(args.session, aborted=args.command == 'check-aborted'))
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
