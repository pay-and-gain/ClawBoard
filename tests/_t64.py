# -*- coding: utf-8 -*-
"""真实 Win32 恢复生命周期回归；只用临时合成资料，不创建 App 或碰剪贴板。

开发测试，不参与产品运行。父进程/helper 都由本脚本持有的 Popen 创建；
异常清理只处理这些自家进程，不按名称或外部 PID 结束任何进程。
"""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clawboard import restore_job as jobs
from clawboard.backups import BackupService


def _write(path, value):
    jobs._atomic_json(path, value)


def _wait_file(path, timeout=15, process=None):
    deadline = time.monotonic() + timeout
    while not path.exists():
        if process is not None and process.poll() is not None:
            output = process.communicate()[0]
            raise AssertionError('own child exited before marker: ' + (output or ''))
        if time.monotonic() >= deadline:
            raise AssertionError('temporary test marker did not appear: ' + path.name)
        time.sleep(0.025)


def _parent_mode(base, scenario, archive, digest):
    kernel = jobs._kernel32()
    handle = kernel.CreateMutexW(None, True, jobs.MUTEX_NAME)
    if not handle or ctypes.get_last_error() == 183:
        if handle:
            kernel.CloseHandle(handle)
        raise RuntimeError('product mutex appeared; native test aborted')
    ticket = jobs.prepare_restore_job(base, archive, digest)
    old = (base / 'writer.json').read_bytes()
    if scenario == 'writer':
        def late_writer():
            _wait_file(base / 'writer-release')
            time.sleep(0.2)
            (base / 'ClawBoard数据.json').write_bytes(old)
            _write(base / 'writer-finished', {'at': time.time()})
        # Python 主流程返回后，此线程仍然存活；恢复必须等到整个进程退出。
        threading.Thread(target=late_writer, daemon=False).start()
    _write(base / 'parent-ready', {'ticket': str(ticket), 'pid': os.getpid()})
    _wait_file(base / ('leave-main' if scenario == 'writer' else 'stop-parent'))
    _write(base / 'parent-main-returning', {'at': time.time()})
    # 不提前释放 mutex；模拟产品由进程退出关闭句柄的生命周期。
    return 0


def _helper_mode(base, ticket, timeout):
    _write(base / 'helper-started', {'pid': os.getpid()})
    def restart_marker():
        _write(base / 'restart-marker', {'at': time.time(), 'pid': os.getpid()})
    result = jobs.run_restore_job(ticket, base, parent_timeout=timeout,
                                  mutex_timeout=2, restart=restart_marker)
    _write(base / 'helper-result', result)
    return 0


def _assert_no_product_instance():
    """只读检查：不创建 mutex，避免测试外层锁住自己的父进程。"""
    kernel = jobs._kernel32()
    kernel.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenMutexW.restype = wintypes.HANDLE
    handle = kernel.OpenMutexW(0x00100000, False, jobs.MUTEX_NAME)
    if handle:
        kernel.CloseHandle(handle)
        raise RuntimeError('检测到产品 mutex；请先正常退出 ClawBoard，再运行 _t64。')
    if ctypes.get_last_error() != 2:
        raise RuntimeError('无法确认产品 mutex 不存在；停止原生测试。')

    class ProcessEntry(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                    ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.c_size_t),
                    ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
                    ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', wintypes.LONG),
                    ('dwFlags', wintypes.DWORD), ('szExeFile', wintypes.WCHAR * 260)]
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32FirstW.restype = wintypes.BOOL
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32NextW.restype = wintypes.BOOL
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS
    if snapshot == ctypes.c_void_p(-1).value:
        raise RuntimeError('无法核对产品进程；停止原生测试。')
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        found = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            if entry.szExeFile.casefold().startswith('clawboard'):
                raise RuntimeError('检测到 ClawBoard 程序；请先正常退出，再运行 _t64。')
            found = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)


@unittest.skipUnless(os.name == 'nt', '真实父进程/产品互斥生命周期只在 Windows 验证')
class NativeRestoreLifecycleTests(unittest.TestCase):
    def setUp(self):
        _assert_no_product_instance()
        self.temporary = tempfile.TemporaryDirectory(prefix='clawboard-t64-')
        self.base = Path(self.temporary.name).resolve()
        self.children = []
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(self.close_children)
        self.source = self.base / 'backup-source'
        self.source.mkdir()
        (self.source / 'images').mkdir()
        self.new_raw = json.dumps({'schema_version': 3, 'clip': [
            {'id': 'new-text', 'text': 'restored synthetic fixture'},
            {'id': 'new-image', 'text': '[图片]', 'image_path': 'shared.png',
             'content_type': 'image'}], 'groups': [], 'settings': {'theme': 'light'},
            'future_fixture': ['must-preserve', 1]}, ensure_ascii=False).encode('utf-8')
        (self.source / 'ClawBoard数据.json').write_bytes(self.new_raw)
        (self.source / 'images' / 'shared.png').write_bytes(b'new synthetic image')
        self.archive = self.base / 'complete.zip'
        self.preview = BackupService(self.source / 'ClawBoard数据.json').create(self.archive)
        self.original = b'{"schema_version":3,"clip":[{"id":"old","text":"old fixture","image_path":"shared.png"}],"groups":[]}'
        self.writer_raw = b'{"schema_version":3,"clip":[{"id":"writer","text":"late old writer","image_path":"shared.png"}],"groups":[]}'
        self.data = self.base / 'ClawBoard数据.json'
        self.data.write_bytes(self.original)
        (self.base / 'writer.json').write_bytes(self.writer_raw)
        (self.base / 'images').mkdir()
        (self.base / 'images' / 'shared.png').write_bytes(b'old synthetic image')

    def close_children(self):
        # 先正常通知自己的父进程退出，helper 随后可以结束等待。
        for name in ('stop-parent', 'leave-main', 'writer-release'):
            (self.base / name).touch()
        for child in self.children:
            try:
                child.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                # 只结束此用例创建并持有的 Popen 对象，绝不查找或结束外部实例。
                child.terminate()
                child.communicate(timeout=5)

    def spawn(self, arguments):
        options = dict(shell=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, encoding='utf-8', errors='replace',
                       creationflags=subprocess.CREATE_NO_WINDOW)
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve())] + arguments,
                                 **options)
        self.children.append(child)
        return child

    def start_pair(self, scenario, timeout=10):
        parent = self.spawn(['--parent', str(self.base), scenario, str(self.archive),
                             self.preview.sha256])
        _wait_file(self.base / 'parent-ready', process=parent)
        ready = json.loads((self.base / 'parent-ready').read_text(encoding='utf-8'))
        self.assertEqual(parent.pid, ready['pid'])
        ticket = Path(ready['ticket'])
        helper = self.spawn(['--helper', str(self.base), str(ticket), str(timeout)])
        _wait_file(self.base / 'helper-started', process=helper)
        return parent, helper, ticket

    def helper_result(self, helper):
        output, _ = helper.communicate(timeout=15)
        self.assertEqual(helper.returncode, 0, output)
        return json.loads((self.base / 'helper-result').read_text(encoding='utf-8'))

    def finish_parent(self, parent):
        (self.base / 'stop-parent').touch()
        output, _ = parent.communicate(timeout=5)
        self.assertEqual(parent.returncode, 0, output)

    def assert_original(self):
        self.assertEqual(self.data.read_bytes(), self.original)
        self.assertEqual((self.base / 'images' / 'shared.png').read_bytes(), b'old synthetic image')
        self.assertFalse((self.base / 'restart-marker').exists())

    def test_default_wait_includes_non_daemon_writer_and_mutex_then_real_restore(self):
        parent, helper, ticket = self.start_pair('writer')
        (self.base / 'leave-main').touch()
        _wait_file(self.base / 'parent-main-returning', process=parent)
        time.sleep(0.35)
        self.assertIsNone(parent.poll(), 'non-daemon writer must keep the old process alive')
        self.assertIsNone(helper.poll(), 'helper must wait for actual process termination')
        self.assert_original()
        self.assertFalse(Path(str(ticket) + '.result').exists())
        (self.base / 'writer-release').touch()
        output, _ = parent.communicate(timeout=5)
        self.assertEqual(parent.returncode, 0, output)
        result = self.helper_result(helper)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(self.data.read_bytes(), self.new_raw)
        self.assertEqual((self.base / 'images' / 'shared.png').read_bytes(), b'new synthetic image')
        restart = json.loads((self.base / 'restart-marker').read_text(encoding='utf-8'))
        writer = json.loads((self.base / 'writer-finished').read_text(encoding='utf-8'))
        self.assertLessEqual(writer['at'], restart['at'])
        with zipfile.ZipFile(result['backup_path']) as before:
            self.assertEqual(before.read('data.json'), self.writer_raw)
            self.assertEqual(before.read('images/shared.png'), b'old synthetic image')
        time.sleep(0.2)
        self.assertEqual(self.data.read_bytes(), self.new_raw, 'old writer cannot overwrite restored data')
        _assert_no_product_instance()

    def test_alive_parent_timeout_cannot_replace_data_or_restart(self):
        parent, helper, ticket = self.start_pair('timeout', timeout=0.5)
        result = self.helper_result(helper)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['error_class'], 'ParentTimeout')
        self.assertIsNone(parent.poll())
        self.assert_original()
        self.finish_parent(parent)
        self.assert_original()

    def test_save_failure_cancel_while_parent_alive_blocks_later_restore(self):
        parent, helper, ticket = self.start_pair('cancel')
        jobs.cancel_restore_job(ticket, self.base)
        result = self.helper_result(helper)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['error_class'], 'Cancelled')
        self.assertIsNone(parent.poll())
        self.assert_original()
        self.finish_parent(parent)
        time.sleep(0.3)
        self.assert_original()


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--parent':
        raise SystemExit(_parent_mode(Path(sys.argv[2]), sys.argv[3],
                                     Path(sys.argv[4]), sys.argv[5]))
    if len(sys.argv) > 1 and sys.argv[1] == '--helper':
        raise SystemExit(_helper_mode(Path(sys.argv[2]), Path(sys.argv[3]), float(sys.argv[4])))
    unittest.main(verbosity=2)
