"""开发工具，不参与产品运行：桌面测试持有产品互斥体，拒绝真实实例并行采集。"""
import atexit
import ctypes
from ctypes import wintypes
import os

NAME = 'ClawBoard_SingleInstance_Mutex'
_leases = []


def acquire_desktop_test_lease(*, kernel=None, last_error=None):
    """测试进程退出前保持句柄；另一个真实程序不能在检查之后重新启动。

    不等待或结束现有实例，不获取其中的数据。构造 App 的测试直接调用类，
    不再调用产品入口 single_instance；冻结 exe 的启动烟测不能持有此租约。
    """
    if kernel is None:
        if os.name != 'nt':
            raise RuntimeError('desktop acceptance requires Windows')
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    error = last_error or ctypes.get_last_error
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateMutexW(None, False, NAME)
    status = error()
    if not handle:
        raise RuntimeError('cannot establish desktop test isolation')
    if status == 183:
        kernel.CloseHandle(handle)
        raise RuntimeError('Exit the running ClawBoard instance before desktop tests')
    _leases.append((kernel, handle))
    return handle


def _release():
    while _leases:
        kernel, handle = _leases.pop()
        kernel.CloseHandle(handle)


atexit.register(_release)
