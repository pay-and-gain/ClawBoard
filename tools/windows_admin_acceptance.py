"""开发工具，不参与产品运行：普通权限驱动与管理员合成靶窗口验收。

prepare 创建临时会话；launch 请求 UAC（由用户确认）；check 测试真实粘贴后端。
不构造 ClawBoard App，不加载历史库，不安装任何程序。
"""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import msvcrt
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
TARGET = Path(__file__).with_name('windows_elevated_target.py')
CURRENT = Path(tempfile.gettempdir()) / 'ClawBoard-admin-current.json'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def real_hashes():
    paths = [ROOT / 'ClawBoard数据.json',
             Path.home() / 'Desktop' / 'cut' / 'ClawBoard数据.json',
             Path(os.environ['APPDATA']) / 'ClawBoard' / 'ClawBoard数据.json']
    return {str(path): digest(path) for path in paths}


def save(path, value):
    stage = path.with_suffix('.tmp')
    stage.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    os.replace(stage, path)


def prepare():
    if not TARGET.is_file():
        raise RuntimeError('administrator target source is missing')
    session = Path(tempfile.mkdtemp(prefix='ClawBoard-elevated-')).resolve()
    request = dict(token=secrets.token_hex(16), target_sha256=digest(TARGET),
                   real_hashes_before=real_hashes(), created_at=time.time())
    save(session / 'target-request.json', request)
    # High-token newly created files can be owned by Administrators, leaving a
    # medium token without OWNER RIGHTS. Preserve this medium-created file.
    save(session / 'target-status.json', dict(ready=False, closed=False))
    save(CURRENT, dict(session=str(session)))
    print(json.dumps(dict(session=str(session), prepared=True)), flush=True)


def load_session(session_arg):
    from windows_elevated_target import validate_session
    session = Path(session_arg or json.loads(CURRENT.read_text(encoding='utf-8'))['session'])
    request = json.loads((session / 'target-request.json').read_text(encoding='utf-8'))
    session = validate_session(session, request['token'])
    if digest(TARGET) != request['target_sha256']:
        raise RuntimeError('administrator target source changed after preparation')
    return session, request


def launch(session, request):
    from windows_elevated_target import read_integrity_level
    integrity = read_integrity_level()
    if not 0x2000 <= integrity < 0x3000:
        raise RuntimeError('driver must run at ordinary medium integrity')
    pythonw = Path(sys.executable).with_name('pythonw.exe')
    if not pythonw.is_file():
        raise RuntimeError('pythonw executable is missing')
    params = subprocess.list2cmdline(['-I', str(TARGET), '--session', str(session),
                                     '--token', request['token']])
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    shell.ShellExecuteW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                   wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int]
    shell.ShellExecuteW.restype = ctypes.c_void_p
    save(session / 'launch-request.json', dict(source_integrity=integrity,
                                              requested_at=time.time()))
    print('Requesting Windows UAC for the isolated synthetic target only.', flush=True)
    result = int(shell.ShellExecuteW(None, 'runas', str(pythonw), params,
                                    str(ROOT), 1) or 0)
    save(session / 'launch-result.json', dict(shell_result=result,
                                             requested=result > 32))
    if result <= 32:
        raise RuntimeError('Windows did not launch the target (result %d)' % result)
    print('Windows accepted the elevation launch request.', flush=True)


def read_status(session):
    with (session / 'target-status.json').open('r+b') as stream:
        deadline = time.monotonic() + .3
        while True:
            try:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.01)
        try:
            status = json.loads(stream.read(8192).decode('utf-8'))
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    if not status.get('ready') or status.get('closed'):
        raise RuntimeError('administrator target is not ready')
    if not 0 <= time.time() - status['updated_at'] < 4:
        raise RuntimeError('administrator target status is stale')
    return status


def check(session, request):
    from windows_elevated_target import ADMIN_TEXT, read_integrity_level
    source_integrity = read_integrity_level()
    if not 0x2000 <= source_integrity < 0x3000:
        raise RuntimeError('driver must remain at ordinary medium integrity')
    # All path-bound adapters see only this temporary directory on first import.
    sys.path.insert(0, str(ROOT))
    from clawboard import config, runtime
    config.BASE_DIR = str(session)
    config.DATA_FILE = str(session / 'ClawBoard数据.json')
    config.CRASH_LOG = str(session / 'driver-crash.log')
    runtime.NO_SAVE = True
    import ClawBoard as C
    C.NO_SAVE = True
    from clawboard.paste_adapter import PasteRequest, windows_backend
    from clawboard.windows_api import u32
    from clawboard.windows_focus import _integrity_of, target_focus_hwnd
    from clawboard.windows_input import send_replacement

    status = read_status(session)
    target, edit, pid = (int(status[key]) for key in ('hwnd', 'edit_hwnd', 'pid'))
    if status['token'] != request['token'] or not status['initial_matches']:
        raise RuntimeError('unexpected administrator target state')
    target_integrity = _integrity_of(target)
    if (target_integrity is None or target_integrity < 0x3000
            or target_integrity != status['integrity'] or target_integrity <= source_integrity):
        raise RuntimeError('target is not verifiably higher integrity than driver')

    def identity_valid(*, require_focus=False):
        try:
            state = read_status(session)
            process_id = wintypes.DWORD()
            edit_pid = wintypes.DWORD()
            u32.GetWindowThreadProcessId(target, ctypes.byref(process_id))
            u32.GetWindowThreadProcessId(edit, ctypes.byref(edit_pid))
            title = ctypes.create_unicode_buffer(256)
            u32.GetWindowTextW(target, title, len(title))
            return bool(state['token'] == request['token'] and state['pid'] == pid
                        and state['hwnd'] == target and state['edit_hwnd'] == edit
                        and process_id.value == pid and edit_pid.value == pid
                        and int(u32.GetAncestor(edit, 2) or 0) == target
                        and title.value == 'ClawBoard Admin Acceptance - ' + request['token']
                        and (not require_focus
                             or int(target_focus_hwnd(target) or 0) == edit))
        except (OSError, ValueError, KeyError, RuntimeError):
            return False

    if not identity_valid():
        raise RuntimeError('administrator target identity or focused editor changed')
    backend = windows_backend()
    injection_allowed = (bool(backend.can_inject(target))
                         if getattr(backend, 'can_inject', None) else True)
    message_allowed = bool(backend.can_message(target))
    if message_allowed:
        raise RuntimeError('higher-integrity target unexpectedly permits message path')
    # The harness admits only this synthetic editor at the last native input call.
    key_attempt = dict(entered=False, guard_passed=False, native_accepted=None)

    def guarded_keys():
        key_attempt['entered'] = True

        def guard():
            allowed = identity_valid(require_focus=True) and int(u32.GetForegroundWindow() or 0) == target
            key_attempt['guard_passed'] = allowed
            return allowed

        accepted = send_replacement(0, guard=guard)
        key_attempt['native_accepted'] = accepted
        return accepted

    backend.send_keys = guarded_keys
    started = time.time()
    result = backend.perform(PasteRequest(1, text=ADMIN_TEXT, target=target, should_paste=True))
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        status = read_status(session)
        if status['updated_at'] > started + .3:
            break
        time.sleep(.05)
    after = real_hashes()
    report = dict(copied=result.copied, pasted=result.pasted, error=result.error,
                  sequence=result.sequence, source_integrity=source_integrity,
                  target_integrity=target_integrity, message_allowed=message_allowed,
                  injection_policy_allowed=injection_allowed,
                  target_initial_matches=status['initial_matches'],
                  target_expected_matches=status['expected_matches'],
                  target_length=status['length'], no_save=runtime.NO_SAVE,
                  real_hashes_unchanged=after == request['real_hashes_before'],
                  temporary_json_absent=not Path(config.DATA_FILE).exists(),
                  key_attempt=key_attempt,
                  completed_at=time.time())
    report['safe_rejection'] = bool(report['copied'] and not report['pasted']
        and report['target_initial_matches'] and report['real_hashes_unchanged']
        and report['temporary_json_absent'])
    report['rejection_stage'] = ('permission' if not injection_allowed
        else 'injection' if key_attempt['guard_passed'] else 'scope'
        if key_attempt['entered'] else 'focus') if not result.pasted else 'none'
    save(session / 'automatic-result.json', report)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    if not report['safe_rejection']:
        raise RuntimeError('administrator paste did not meet safe rejection expectations')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'launch', 'check'))
    parser.add_argument('--session')
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare()
    else:
        session, request = load_session(args.session)
        (launch if args.action == 'launch' else check)(session, request)


if __name__ == '__main__':
    main()
