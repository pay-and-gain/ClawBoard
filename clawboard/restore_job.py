# -*- coding: utf-8 -*-
"""完整恢复的独立进程协调；不导入 App、Tk 或运行时全局数据路径。

先等待原进程真正结束（包括后台 writer），再以产品同名 mutex 排除其它
日常实例。票据只描述已确认的归档，目标位置和重启命令始终由当前程序推导。
"""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
import uuid


JOB_VERSION = 1
JOB_TTL = 15 * 60
MUTEX_NAME = 'ClawBoard_SingleInstance_Mutex'
_UUID_FILE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.json$')
_SHA256 = re.compile(r'^[0-9a-fA-F]{64}$')
_MESSAGES = {
    'InvalidJob': '恢复请求无效或已经过期。',
    'AlreadyRunning': '此恢复请求已在处理或已经完成。',
    'ParentTimeout': '原程序尚未退出，本次恢复已取消。',
    'ParentWaitError': '无法确认原程序已经退出，本次恢复已取消。',
    'MutexTimeout': '资料仍被其它实例使用，本次恢复已取消。',
    'ArchiveChanged': '备份文件已发生变化，本次恢复已取消。',
    'Cancelled': '本次恢复已取消。',
    'RestoreFailed': '恢复未完成，请保留当前资料和恢复前备份。',
}


class RestoreJobError(Exception):
    """仅暴露固定错误码，异常文本不携带归档内正文。"""

    def __init__(self, code='InvalidJob'):
        self.code = code
        super().__init__(_MESSAGES.get(code, _MESSAGES['RestoreFailed']))


def _plain(path, directory=False):
    """Windows junction 和符号链接都不能把票据目录转向别处。"""
    try:
        info = Path(path).lstat()
    except OSError:
        raise RestoreJobError() from None
    mode_ok = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not mode_ok or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise RestoreJobError()
    return info


def _job_directory(base_dir, create=False):
    base = Path(base_dir).resolve(strict=True)
    _plain(base, directory=True)
    directory = base / '.restore-jobs'
    if create:
        directory.mkdir(exist_ok=True)
    _plain(directory, directory=True)
    if directory.resolve() != directory:
        raise RestoreJobError()
    return directory


def _job_path(job_path, base_dir=None):
    candidate = Path(job_path).absolute()
    if not _UUID_FILE.fullmatch(candidate.name):
        raise RestoreJobError()
    base = Path(base_dir) if base_dir is not None else candidate.parent.parent
    directory = _job_directory(base)
    if candidate.parent != directory or candidate.resolve() != candidate:
        raise RestoreJobError()
    _plain(candidate)
    return candidate


def _atomic_json(path, payload):
    """同目录替换避免掉电留下半截结果；任何异常都清理自己的临时文件。"""
    descriptor, temporary = tempfile.mkstemp(prefix='.restore-', dir=str(path.parent))
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(payload, stream, ensure_ascii=False, separators=(',', ':'))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _read_json(path):
    if _plain(path).st_size > 262144:
        raise RestoreJobError()
    try:
        with path.open('r', encoding='utf-8') as stream:
            payload = json.load(stream)
    except (OSError, ValueError, UnicodeError):
        raise RestoreJobError() from None
    if not isinstance(payload, dict):
        raise RestoreJobError()
    return payload


def _digest(value):
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise RestoreJobError()
    return value.lower()


def _reject_pending(directory):
    for candidate in directory.glob('*.json'):
        if not _UUID_FILE.fullmatch(candidate.name):
            continue
        try:
            path = _job_path(candidate, directory.parent)
            _validate_ticket(_read_json(path), reject_current_pid=False)
        except (OSError, RuntimeError, RestoreJobError):
            continue
        if (_cancelled(path) or os.path.lexists(str(path) + '.result')
                or os.path.lexists(str(path) + '.result.seen')):
            continue
        # 不限父 PID：新窗口/新实例不能把另一恢复请求排到现有 helper 后面。
        raise RestoreJobError('AlreadyRunning')


def prepare_restore_job(base_dir, archive, expected_sha256, parent_pid=None):
    """只在 base_dir/.restore-jobs 创建新票据；调用方先拦截 NO_SAVE。"""
    return _prepare_job(base_dir, archive, expected_sha256, parent_pid)


def prepare_import_job(base_dir, source, expected_sha256, selected, parent_pid=None):
    """Only additive import keys are authorized; target and commands stay fixed."""
    keys = _selection(selected)
    return _prepare_job(base_dir, source, expected_sha256, parent_pid,
                        operation='merge', selected=keys)


def _selection(values):
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 10000:
        raise RestoreJobError()
    if any(not isinstance(key, str) or not re.fullmatch(r'(c:[0-9]{1,5}|g:[0-9]{1,5}:[0-9]{1,5})', key)
           or len(key) > 32 for key in values) or len(set(values)) != len(values):
        raise RestoreJobError()
    return list(values)


def _prepare_job(base_dir, archive, expected_sha256, parent_pid=None, **extra):
    digest = _digest(expected_sha256)
    source = Path(archive).absolute()
    _plain(source)
    if source.resolve() != source:
        raise RestoreJobError()
    pid = os.getpid() if parent_pid is None else parent_pid
    if type(pid) is not int or not 0 < pid <= 0xffffffff:
        raise RestoreJobError()
    directory = _job_directory(base_dir, create=True)
    _reject_pending(directory)
    path = directory / (str(uuid.uuid4()) + '.json')
    _atomic_json(path, {'version': JOB_VERSION, 'parent_pid': pid,
                        'archive': str(source), 'expected_sha256': digest,
                        'created_at': time.time(), **extra})
    return path


def _program_command():
    if getattr(sys, 'frozen', False):
        return [sys.executable]
    return [sys.executable, str(Path(__file__).resolve().parent.parent / 'ClawBoard.py')]


def _spawn(command):
    options = dict(shell=False, close_fds=True, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.name == 'nt':
        options['creationflags'] = subprocess.CREATE_NO_WINDOW
    return subprocess.Popen(command, **options)


def launch_restore_job(job_path):
    """不从票据读取命令；调用方先拦截 NO_SAVE，再安排正常保存退出。"""
    path = _job_path(job_path)
    return _spawn(_program_command() + ['--restore-job', str(path)])


def cancel_restore_job(job_path, base_dir=None):
    """保存失败时立即撤销；即使原程序稍后退出，也不会执行旧恢复请求。"""
    path = _job_path(job_path, base_dir)
    _atomic_json(path.with_name(path.name + '.cancel'), {'version': JOB_VERSION})


def _cancelled(path):
    # 任何同名取消标记都保守取消；不跟随或删除未知标记。
    return os.path.lexists(str(path.with_name(path.name + '.cancel')))


def _check_cancel(path):
    if _cancelled(path):
        raise RestoreJobError('Cancelled')


def _kernel32():
    if os.name != 'nt':
        raise RestoreJobError('ParentWaitError')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    # 句柄必须保留指针宽度，默认 c_int 会在 64 位 Windows 上截断。
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel.ReleaseMutex.restype = wintypes.BOOL
    return kernel


def _wait_parent(pid, timeout, cancelled):
    kernel = _kernel32()
    handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not handle:
        if ctypes.get_last_error() == 87:  # ERROR_INVALID_PARAMETER: pid 已不存在
            return True
        raise RestoreJobError('ParentWaitError')
    try:
        deadline = time.monotonic() + timeout
        while not cancelled():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            state = kernel.WaitForSingleObject(handle, max(1, min(250, int(remaining * 1000))))
            if state == 0:  # WAIT_OBJECT_0: 进程所有线程已结束
                return True
            if state != 258:  # WAIT_TIMEOUT
                raise RestoreJobError('ParentWaitError')
        return False
    finally:
        kernel.CloseHandle(handle)


@contextmanager
def _product_lease(timeout):
    kernel = _kernel32()
    handle = kernel.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        raise RestoreJobError('MutexTimeout')
    owned = False
    try:
        # 父进程已经完全退出；若新实例正占用资料，立即取消而不排队等它退出。
        # timeout 参数仅为既有注入接口兼容保留。
        state = kernel.WaitForSingleObject(handle, 0)
        # 原实例由进程退出释放，WAIT_ABANDONED 是预期的安全接管状态。
        if state not in (0, 0x80):
            raise RestoreJobError('MutexTimeout')
        owned = True
        yield
    finally:
        if owned:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


def _validate_ticket(payload, *, reject_current_pid=True):
    # 禁止在未来扩展时误把未知 target/command 当成授权。
    fields = {'version', 'parent_pid', 'archive', 'expected_sha256', 'created_at'}
    if payload.get('operation') == 'merge':
        fields |= {'operation', 'selected'}
        _selection(payload.get('selected'))
    if set(payload) != fields:
        raise RestoreJobError()
    if type(payload['version']) is not int or payload['version'] != JOB_VERSION:
        raise RestoreJobError()
    pid = payload['parent_pid']
    if (type(pid) is not int or not 0 < pid <= 0xffffffff
            or reject_current_pid and pid == os.getpid()):
        raise RestoreJobError()
    created = payload['created_at']
    if (type(created) not in (int, float) or not math.isfinite(created)
            or not -30 <= time.time() - created <= JOB_TTL):
        raise RestoreJobError()
    payload['expected_sha256'] = _digest(payload['expected_sha256'])
    archive = payload['archive']
    if not isinstance(archive, str) or not Path(archive).is_absolute():
        raise RestoreJobError()
    return payload


def _check_archive(path, expected):
    from clawboard.backup_format import MAX_ARCHIVE_BYTES
    info = _plain(path)
    if info.st_size > MAX_ARCHIVE_BYTES:
        raise RestoreJobError('ArchiveChanged')
    if path.resolve() != path:
        raise RestoreJobError()
    digest = hashlib.sha256()
    total = 0
    with path.open('rb') as stream:
        while True:
            # stat 后文件仍可能增长或被替换，最多读取上限再加一字节确认越界。
            block = stream.read(min(1024 * 1024, MAX_ARCHIVE_BYTES - total + 1))
            if not block:
                break
            total += len(block)
            if total > MAX_ARCHIVE_BYTES:
                raise RestoreJobError('ArchiveChanged')
            digest.update(block)
    if digest.hexdigest() != expected:
        raise RestoreJobError('ArchiveChanged')


def _service(data_file, images_dir):
    from clawboard.backups import BackupService
    return BackupService(data_file, images_dir=images_dir)


def _error_result(exc):
    code = exc.code if isinstance(exc, RestoreJobError) else 'RestoreFailed'
    name = type(exc).__name__ if code == 'RestoreFailed' else code
    return {'status': 'cancelled' if code in ('Cancelled', 'ParentTimeout', 'MutexTimeout') else 'error',
            'error_class': name, 'message': _MESSAGES.get(code, _MESSAGES['RestoreFailed'])}


def run_restore_job(job_path, base_dir, *, wait_parent=None, lease=None,
                    restore_factory=None, restart=None, parent_timeout=120,
                    mutex_timeout=30):
    """CLI 显式入口；base_dir 必须由入口传 config.BASE_DIR。

    测试可注入 wait_parent(pid, timeout)->bool、lease(timeout) 上下文管理器、
    restore_factory(data_file, images_dir) 和 restart()，无需启动真实进程。
    """
    path = None
    claimed = False
    parent_exited = False
    result = None
    operation = 'restore'
    try:
        path = _job_path(job_path, base_dir)
        if os.path.lexists(str(path) + '.result') or os.path.lexists(str(path) + '.result.seen'):
            raise RestoreJobError('AlreadyRunning')
        try:
            descriptor = os.open(str(path) + '.running', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            raise RestoreJobError('AlreadyRunning') from None
        os.close(descriptor)
        claimed = True
        payload = _validate_ticket(_read_json(path))
        operation = payload.get('operation', 'restore')
        _check_cancel(path)
        if wait_parent is None:
            exited = _wait_parent(payload['parent_pid'], parent_timeout, lambda: _cancelled(path))
        else:
            exited = wait_parent(payload['parent_pid'], parent_timeout)
        # 不允许取消标记把尚未退出的父进程误报为已退出。
        parent_exited = exited is True
        _check_cancel(path)
        if not parent_exited:
            raise RestoreJobError('ParentTimeout')
        with (lease or _product_lease)(mutex_timeout):
            _check_cancel(path)
            source = Path(payload['archive'])
            _check_archive(source, payload['expected_sha256'])
            base = path.parent.parent
            _check_cancel(path)
            if operation == 'merge':
                from clawboard.import_service import ImportService
                service = ImportService(base / 'ClawBoard数据.json', base / 'images')
                _check_cancel(path)
                restored = service.merge(source, payload['expected_sha256'], payload['selected'],
                                         cancelled=lambda: _cancelled(path))
                result = {'status': 'success', 'operation': 'merge',
                          'backup_path': str(restored.backup_path) if restored.backup_path else None,
                          'imported_count': restored.imported_count,
                          'duplicate_count': restored.duplicate_count,
                          'disabled_trigger_count': restored.disabled_trigger_count,
                          'message': '所选资料已合并导入。'}
            else:
                service = (restore_factory or _service)(base / 'ClawBoard数据.json', base / 'images')
                _check_cancel(path)
                restored = service.restore(source, expected_sha256=payload['expected_sha256'])
                result = {'status': 'success', 'backup_path': str(restored.backup_path),
                          'message': '完整备份已恢复。'}
    except Exception as exc:
        result = _error_result(exc)
        if operation == 'merge':
            result['operation'] = 'merge'
            result['message'] = '合并导入未完成，当前资料已保留或回退，请重新预览。'
    result.update({'version': JOB_VERSION, 'job_id': path.stem if path else '',
                   'completed_at': time.time()})
    if claimed:
        try:
            _job_path(path, base_dir)
            _atomic_json(path.with_name(path.name + '.result'), result)
        except (OSError, RestoreJobError):
            # 不允许结果写入失败触发第二次恢复；原始票据和running标记保留取证。
            result['report_error'] = 'ResultWriteFailed'
    # lease 上下文已经关闭，正常入口才能成功获得同名产品 mutex。
    # 另一日常实例占用 mutex 时，本次 helper 不再额外拉起正常入口。
    if parent_exited and result.get('error_class') != 'MutexTimeout':
        try:
            (restart or (lambda: _spawn(_program_command())))()
        except Exception:
            result['restart_error'] = 'RestartFailed'
            if claimed:
                try:
                    _atomic_json(path.with_name(path.name + '.result'), result)
                except OSError:
                    pass
    return result


def consume_restore_result(base_dir):
    """交付最新一条结果一次；只标记合法结果，绝不删除未知目录内容。"""
    try:
        directory = _job_directory(base_dir)
    except (OSError, RestoreJobError):
        return None
    reports = []
    for candidate in directory.glob('*.json.result'):
        name = candidate.name[:-len('.result')]
        if not _UUID_FILE.fullmatch(name):
            continue
        try:
            report = _read_json(candidate)
            completed = report.get('completed_at')
            if (report.get('version') != JOB_VERSION or report.get('job_id') != name[:-5]
                    or report.get('status') not in ('success', 'error', 'cancelled')
                    or type(completed) not in (int, float) or not math.isfinite(completed)):
                continue
            reports.append((completed, candidate.name, candidate, report))
        except (OSError, RestoreJobError):
            continue
    if not reports:
        return None
    reports.sort(key=lambda item: item[:2], reverse=True)
    newest = reports[0]
    try:
        # 先消费最新条，只有这一原子改名成功的进程可以展示它。
        os.rename(newest[2], newest[2].with_name(newest[2].name + '.seen'))
    except OSError:
        return None
    for _, _, candidate, _ in reports[1:]:
        try:
            os.rename(candidate, candidate.with_name(candidate.name + '.seen'))
        except OSError:
            pass
    return newest[3]
