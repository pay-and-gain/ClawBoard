"""开发工具，不参与产品运行：临时合成库的托盘、保存重启与持续负载验收。

App 构造与持续负载保持 NO_SAVE。用户授权的保存/退出阶段只对本次合成库
短暂开启写盘，并用存储写入护栏核对路径；从不采集真实剪贴板或写自启动项。
"""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
from unittest.mock import patch

ROOT = Path(__file__).absolute().parents[1]
sys.path.insert(0, str(ROOT))
BASE = ROOT / 'dist/windows-validation'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def real_hashes():
    return {str(base / 'ClawBoard数据.json'): digest(base / 'ClawBoard数据.json')
            for base in (ROOT, Path.home() / 'Desktop/cut',
                         Path(os.environ['APPDATA']) / 'ClawBoard')}


def atomic_json(path, value):
    staged = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with staged.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=True, indent=2)
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def reload_in_fresh_process(session, *, verify_after_exit=False):
    session = session.absolute()
    if session.parent != BASE or not session.name.startswith('final-acceptance-'):
        raise ValueError('invalid reload session')
    for path in (session, *session.parents):
        if path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('reparse reload path')
    owner = json.loads((session / 'owner.json').read_text())
    if verify_after_exit:
        completed = json.loads((session / 'result.json').read_text())
        if not completed.get('soak_passed') or not completed.get('ui_save_verified'):
            raise ValueError('completed persistence/soak evidence required')
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        previous = kernel.OpenProcess(0x1000, False, owner['pid'])
        if previous:
            try:
                code = wintypes.DWORD()
                if not kernel.GetExitCodeProcess(previous, ctypes.byref(code)) or code.value == 259:
                    raise ValueError('acceptance owner must exit before independent restart verification')
            finally:
                kernel.CloseHandle(previous)
        elif ctypes.get_last_error() != 87:
            raise ValueError('cannot confirm acceptance owner exit')
    elif owner['pid'] != os.getppid():
        raise ValueError('reload must be launched by its acceptance owner')
    from tools.windows_test_guard import acquire_desktop_test_lease
    acquire_desktop_test_lease()
    from clawboard import config, runtime
    config.BASE_DIR = str(session / 'synthetic')
    config.DATA_FILE = str(Path(config.BASE_DIR) / 'ClawBoard数据.json')
    config.CRASH_LOG = str(Path(config.BASE_DIR) / 'events.log')
    runtime.NO_SAVE = True
    import ClawBoard as C
    C.NO_SAVE = True
    import tkinter as tk
    from clawboard.storage import JsonStore
    from clawboard.win32 import init_dpi_awareness
    before = real_hashes()
    saved_hash = digest(Path(config.DATA_FILE))
    init_dpi_awareness()
    root = tk.Tk()
    with patch.object(JsonStore, 'save', side_effect=AssertionError('NO_SAVE reload attempted save')):
        app = C.ClawBoard(root)
        root.title('ClawBoard restart verification — synthetic data')
        root.update()
        assert app.data['clip'][0]['text'] == 'CB-FINAL-PERSISTED 中文 😀'
        assert app.data['validation_unknown'] == {'keep': [3, 1, 2]}
        assert not app.st['listen'] and not app.st['trigger_enabled']
        # Invoke the actual native Tk menu binding; this is functional menu
        # validation, separate from the physical tray-open evidence.
        menus = []
        original_menu = tk.Menu
        def remember_menu(*values, **options):
            menu = original_menu(*values, **options)
            menus.append(menu)
            return menu
        # Native popup waits for a user selection on Windows. Suppress only its
        # display; retain the real Tk menu entries and invoke the product binding.
        with patch.object(tk, 'Menu', side_effect=remember_menu), \
                patch.object(original_menu, 'tk_popup', return_value=None):
            app.tray_menu()
        assert menus and '退出' in menus[-1].entrycget('end', 'label')
        menus[-1].invoke('end')
        app.hw.join(3)
    assert digest(Path(config.DATA_FILE)) == saved_hash
    assert real_hashes() == before
    atomic_json(session / 'fresh-process-reload.json', dict(pid=os.getpid(), passed=True,
                no_save_fixture_unchanged=True, real_hashes_unchanged=True,
                actual_tray_menu_exit_binding_invoked=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--minutes', type=float, default=15)
    parser.add_argument('--automated', action='store_true', help='no manual tray evidence; auto exit after soak')
    parser.add_argument('--reload', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--verify-after-exit', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--session', type=Path)
    parser.add_argument('--command', choices=('start-soak', 'inspect-tray', 'prepare-exit', 'stop'))
    args = parser.parse_args()
    if args.reload or args.verify_after_exit:
        reload_in_fresh_process(args.session, verify_after_exit=args.verify_after_exit)
        return
    if args.command:
        from tools.upgrade_portable import _safe_path
        session = _safe_path(args.session, directory=True)
        if session.parent != BASE or not session.name.startswith('final-acceptance-'):
            raise ValueError('invalid acceptance session')
        _safe_path(session / 'owner.json')
        atomic_json(session / 'command.json', dict(command=args.command))
        print('queued=' + args.command)
        return
    if not 0.01 <= args.minutes <= 60:
        raise ValueError('minutes must be between 0.01 and 60')
    from tools.windows_test_guard import acquire_desktop_test_lease
    acquire_desktop_test_lease()
    session = BASE / ('final-acceptance-' + uuid.uuid4().hex)
    session.mkdir()
    atomic_json(session / 'owner.json', dict(pid=os.getpid(), nonce=uuid.uuid4().hex))
    before = real_hashes()
    data_dir = session / 'synthetic'
    data_dir.mkdir()
    from clawboard import config, runtime
    config.BASE_DIR = str(data_dir)
    config.DATA_FILE = str(data_dir / 'ClawBoard数据.json')
    config.CRASH_LOG = str(data_dir / 'events.log')
    runtime.NO_SAVE = True
    settings = dict(config.DEFAULT_SETTINGS, listen=False, trigger_enabled=False,
                    update_check=False, show_toast=False, show_preview=False,
                    sound_copy=False, sound_paste=False, edge_hide=False, collapsed=False,
                    theme='dark', ui_scale=1.0, max_items=10000)
    fixture = dict(schema_version=3, settings=settings, gi=0,
                   geom='520x680+150+150', validation_unknown={'keep': [3, 1, 2]},
                   clip=[dict(id='final-%d' % n, text='Synthetic record %d 中文 example %s' % (n, 'x' * 140),
                              seq=5000-n, content_type='text', created_at=1700000000000+n,
                              future_field={'value': n}) for n in range(5000)],
                   groups=[dict(name='Synthetic phrases', items=[dict(
                       id='final-phrase', text='Synthetic phrase preserved', trigger='cbfinal',
                       created_at=1700000000000)])])
    data_path = Path(config.DATA_FILE)
    atomic_json(data_path, fixture)
    fixture_hash = digest(data_path)
    import tkinter as tk
    import ClawBoard as C
    C.NO_SAVE = True
    from clawboard.storage import JsonStore
    from clawboard.hotkey import HiddenWindow
    from clawboard.win32 import init_dpi_awareness, sh32, NOTIFYICONDATA, NIM_MODIFY, NIF_TIP
    init_dpi_awareness()
    lock = threading.RLock()
    status = dict(session=str(session), pid=os.getpid(), phase='starting', real_hashes_unchanged=True,
                  tray_left=0, tray_right=0, tray_menu=0, quit_calls=0,
                  taskbar_created_messages=0, tray_add_success=0, guarded_save_count=0,
                  soak_minutes=args.minutes, cycles=0, callback_errors=[])
    allowed_save = [False]
    latencies = []
    metrics = []
    old_save = JsonStore.save
    old_wndproc = HiddenWindow.wndproc
    old_add = HiddenWindow._add_tray
    old_tray = C.ClawBoard.on_tray
    old_menu = C.ClawBoard.tray_menu
    old_quit = C.ClawBoard.quit_app
    def guarded_save(store, data):
        if not allowed_save[0] or Path(store.path).absolute() != data_path:
            raise AssertionError('save outside explicit synthetic persistence scope')
        with lock:
            status['guarded_save_count'] += 1
        return old_save(store, data)
    def wndproc(hidden, hwnd, message, wp, lp):
        if hidden._taskbar_created and message == hidden._taskbar_created:
            with lock:
                status['taskbar_created_messages'] += 1
        return old_wndproc(hidden, hwnd, message, wp, lp)
    def add_tray(hidden):
        success = old_add(hidden)
        if success:
            with lock:
                status['tray_add_success'] += 1
        return success
    def on_tray(app, event):
        with lock:
            status['tray_' + event] += 1
        return old_tray(app, event)
    def tray_menu(app):
        status['tray_menu'] += 1
        return old_menu(app)
    def quit_app(app):
        status['quit_calls'] += 1
        if status['phase'] == 'await-quit':
            allowed_save[0] = True
            C.NO_SAVE = False
        try:
            return old_quit(app)
        finally:
            C.NO_SAVE = True
            allowed_save[0] = False
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    process = kernel.GetCurrentProcess()
    kernel.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetGuiResources.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    user.GetGuiResources.restype = wintypes.DWORD
    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ('peak_ws', 'working_set', 'peak_paged', 'paged',
                'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile', 'private')]
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    def metric():
        count = wintypes.DWORD()
        memory = Counters()
        memory.cb = ctypes.sizeof(memory)
        if not (kernel.GetProcessHandleCount(process, ctypes.byref(count)) and
                psapi.GetProcessMemoryInfo(process, ctypes.byref(memory), memory.cb)):
            raise RuntimeError('resource metric unavailable')
        return dict(seconds=round(time.monotonic()-started, 2), handles=count.value,
                    gdi=int(user.GetGuiResources(process, 0)), user=int(user.GetGuiResources(process, 1)),
                    private_bytes=memory.private, working_set=memory.working_set,
                    cpu_seconds=round(time.process_time(), 3))
    root = tk.Tk()
    app = None
    started = time.monotonic()
    soak_started = [None]
    last_metric = [0.0]
    expected_text = 'CB-FINAL-PERSISTED 中文 😀'
    def write_status():
        with lock:
            status['real_hashes_unchanged'] = real_hashes() == before
            status['metrics'] = list(metrics)
            status['visible'] = bool(app is not None and not app.hidden)
            status['last_heartbeat'] = time.time()
            if latencies:
                status['heartbeat_p95_ms'] = round(sorted(latencies)[int(.95*(len(latencies)-1))], 3)
                status['heartbeat_max_ms'] = round(max(latencies), 3)
            atomic_json(session / 'status.json', status)
    def callback_error(kind, error, trace):
        status['callback_errors'].append(kind.__name__)
        write_status()
    root.report_callback_exception = callback_error
    def heartbeat(expected):
        now = time.monotonic()
        latencies.append(max(0, now-expected)*1000)
        if len(latencies) > 5000:
            del latencies[:1000]
        due = time.monotonic()+.02
        root.after(20, lambda: heartbeat(due))
    def persist():
        if real_hashes() != before:
            raise AssertionError('real data changed outside this harness')
        allowed_save[0] = True
        C.NO_SAVE = False
        try:
            assert app.ingest(expected_text, manual=True, quiet=True)
            assert app.save_now()
            data = json.loads(data_path.read_text(encoding='utf-8'))
            assert data['clip'][0]['text'] == expected_text
            assert data['validation_unknown'] == fixture['validation_unknown']
            assert data['groups'][0]['items'][0]['text'] == 'Synthetic phrase preserved'
            status['ui_save_verified'] = True
        finally:
            C.NO_SAVE = True
            allowed_save[0] = False
    def inspect_tray():
        record = NOTIFYICONDATA()
        record.cbSize, record.hWnd, record.uID = ctypes.sizeof(record), app.hw.hwnd, 1
        record.uFlags, record.szTip = NIF_TIP, 'ClawBoard · 临时验收'
        status['shell_icon_present'] = bool(sh32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(record)))
    def tick():
        path = session / 'command.json'
        if path.exists():
            command = json.loads(path.read_text())['command']
            path.unlink()
            if command == 'start-soak':
                soak_started[0] = time.monotonic()
                status['phase'] = 'soak'
                if app.hidden:
                    app.toggle_show()
                metrics.append(metric())
            elif command == 'inspect-tray':
                inspect_tray()
            elif command == 'prepare-exit':
                persist()
                status['phase'] = 'await-quit'
            elif command == 'stop':
                status['phase'] = 'stopped'
                app.quit_app()
                return
        if status['phase'] == 'soak':
            status['cycles'] += 1
            n = status['cycles']
            if n % 5 == 0:
                app.search.set(('Synthetic', 'example', '中文', 'record 12', 'type:text', '')[(n//5) % 6])
            app.vlist.canvas.yview_moveto((n % 41)/40)
            status['max_pending'] = max(status.get('max_pending', 0), app.application.tasks.pending)
            if time.monotonic()-soak_started[0] >= args.minutes*60:
                assert digest(data_path) == fixture_hash, 'NO_SAVE soak changed fixture'
                persist()
                status['soak_passed'] = True
                status['phase'] = 'await-quit'
                if args.automated:
                    root.after(400, app.quit_app)
        if time.monotonic()-last_metric[0] >= 15:
            metrics.append(metric())
            last_metric[0] = time.monotonic()
            write_status()
            print(json.dumps({k:v for k,v in status.items() if k not in ('session','metrics')})[:1300], flush=True)
        root.after(250, tick)
    patches = [patch.object(JsonStore, 'save', guarded_save), patch.object(HiddenWindow, 'wndproc', wndproc),
               patch.object(HiddenWindow, '_add_tray', add_tray), patch.object(C.ClawBoard, 'on_tray', on_tray),
               patch.object(C.ClawBoard, 'tray_menu', tray_menu), patch.object(C.ClawBoard, 'quit_app', quit_app)]
    for item in patches:
        item.start()
    try:
        app = C.ClawBoard(root)
        root.title('ClawBoard Windows Final Acceptance')
        app.title_lb.configure(text='ClawBoard · 临时验收')
        if args.automated:
            status['phase'] = 'soak'
            soak_started[0] = time.monotonic()
        else:
            root.after(800, app.hide)
            status['phase'] = 'manual-tray-open'
        root.after(1000, write_status)
        due = time.monotonic()+.02
        root.after(20, lambda: heartbeat(due))
        root.after(1200, tick)
        print(json.dumps(dict(session=str(session), pid=os.getpid(), stage='ready')), flush=True)
        root.mainloop()
        app.hw.join(3)
        if status['phase'] == 'await-quit':
            saved = json.loads(data_path.read_text(encoding='utf-8'))
            assert saved['clip'][0]['text'] == expected_text
            assert saved['validation_unknown'] == fixture['validation_unknown']
            from tools.windows_test_guard import _release
            _release()
            with (session / 'reload.log').open('xb') as output:
                subprocess.run([sys.executable, __file__, '--reload', '--session', str(session)],
                               cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, check=True, timeout=30)
            assert json.loads((session / 'fresh-process-reload.json').read_text())['passed']
            status['restart_load_verified'] = True
            status['phase'] = 'complete'
        metrics.append(metric())
        assert real_hashes() == before
        assert not status['callback_errors']
        write_status()
        atomic_json(session / 'result.json', status)
        print(json.dumps(dict(stage=status['phase'], result=str(session / 'result.json'))), flush=True)
    finally:
        C.NO_SAVE = True
        allowed_save[0] = False
        if app is not None:
            try:
                app.close_paste()
                app.bridge.close()
                app.hw.stop()
                app.hw.join(3)
            except Exception:
                pass
        try:
            root.destroy()
        except tk.TclError:
            pass
        for item in reversed(patches):
            item.stop()
        if real_hashes() != before:
            raise AssertionError('real data hash changed')


if __name__ == '__main__':
    main()
