# -*- coding: utf-8 -*-
"""C 前置：检测命名互斥体 ClawBoard_SingleInstance_Mutex 是否被占用，
并枚举 ClawBoard-2.2.2.exe 实例。"""
import ctypes
import sys
from ctypes import wintypes

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
k32.CreateMutexW.restype = wintypes.HANDLE
h = k32.CreateMutexW(None, True, 'ClawBoard_SingleInstance_Mutex')
err = ctypes.get_last_error()
print('CreateMutex err =', err, '(183 = ERROR_ALREADY_EXISTS → 已有实例占单实例锁)')
print('=> single_instance() 会返回 False' if err == 183 else '=> 单实例锁空闲，可启动')
