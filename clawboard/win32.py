# -*- coding: utf-8 -*-
"""兼容入口；Win32 适配器按职责分离，旧导出与测试替换点保持有效。

DLL/ABI 声明只在 windows_api；各功能模块不反向导入本入口。
属性通过定义模块读取，键盘 hook 的可变状态始终只有一份。
"""
import ctypes
import os
import sys
import time
import threading
import types
import winreg
from ctypes import wintypes

from clawboard.config import APP_NAME, BASE_DIR
from clawboard import (
    windows_api, windows_input, windows_focus, windows_geometry,
    windows_system, windows_effects, windows_hooks,
)

_MODULES = (windows_api, windows_input, windows_focus, windows_geometry,
            windows_system, windows_effects, windows_hooks)
_OWNER_NAMES = {
    'ACCENTPOLICY': 'windows_api',
    'ACCENT_DISABLED': 'windows_api',
    'ACCENT_ENABLE_ACRYLICBLURBEHIND': 'windows_api',
    'ACCENT_ENABLE_BLURBEHIND': 'windows_api',
    'CF_HDROP': 'windows_api',
    'CF_NAME_EXCLUDE': 'windows_api',
    'CF_NAME_INCLUDE_HISTORY': 'windows_api',
    'CF_UNICODETEXT': 'windows_api',
    'DWMWA_WINDOW_CORNER_PREFERENCE': 'windows_api',
    'DWMWCP_DEFAULT': 'windows_api',
    'DWMWCP_DONOTROUND': 'windows_api',
    'DWMWCP_ROUND': 'windows_api',
    'EDIT_CLASSES': 'windows_focus',
    'GMEM_MOVEABLE': 'windows_api',
    'GUITHREADINFO': 'windows_api',
    'GWL_STYLE': 'windows_api',
    'HARDWAREINPUT': 'windows_api',
    'HOOKPROC': 'windows_api',
    'HWND_MESSAGE': 'windows_api',
    'IMAGE_ICON': 'windows_api',
    'INPUT': 'windows_api',
    'INPUT_KEYBOARD': 'windows_api',
    'KBDLLHOOKSTRUCT': 'windows_api',
    'KEYBDINPUT': 'windows_api',
    'KEYEVENTF_KEYUP': 'windows_api',
    'LRESULT': 'windows_api',
    'LR_DEFAULTSIZE': 'windows_api',
    'LR_LOADFROMFILE': 'windows_api',
    'MODIFIER_VKS': 'windows_api',
    'MOD_ALT': 'windows_api',
    'MOD_CONTROL': 'windows_api',
    'MOD_SHIFT': 'windows_api',
    'MONITORENUMPROC': 'windows_api',
    'MONITORINFO': 'windows_api',
    'MONITOR_DEFAULTTONEAREST': 'windows_api',
    'MOUSEINPUT': 'windows_api',
    'MUTEX': 'windows_system',
    'NIF_ICON': 'windows_api',
    'NIF_INFO': 'windows_api',
    'NIF_MESSAGE': 'windows_api',
    'NIF_TIP': 'windows_api',
    'NIIF_INFO': 'windows_api',
    'NIM_ADD': 'windows_api',
    'NIM_DELETE': 'windows_api',
    'NIM_MODIFY': 'windows_api',
    'NOTIFYICONDATA': 'windows_api',
    'PROCESS_MEMORY_COUNTERS': 'windows_api',
    'PROCESS_QUERY_LIMITED_INFORMATION': 'windows_api',
    'RUN_KEY': 'windows_system',
    'RUN_NAME': 'windows_system',
    'SECURITY_MANDATORY_HIGH_RID': 'windows_api',
    'TITLE_BAD_WORDS': 'windows_system',
    'TOKEN_INTEGRITY_LEVEL': 'windows_api',
    'TOKEN_QUERY': 'windows_api',
    'VK_BACK': 'windows_api',
    'VK_CAPITAL': 'windows_api',
    'VK_CONTROL': 'windows_api',
    'VK_MENU': 'windows_api',
    'VK_RETURN': 'windows_api',
    'VK_SHIFT': 'windows_api',
    'VK_SPACE': 'windows_api',
    'VK_TAB': 'windows_api',
    'VK_V': 'windows_api',
    'WCA_ACCENT_POLICY': 'windows_api',
    'WH_KEYBOARD_LL': 'windows_api',
    'WINCOMPATTRDATA': 'windows_api',
    'WM_APP_REG': 'windows_api',
    'WM_APP_UNREG': 'windows_api',
    'WM_DESTROY': 'windows_api',
    'WM_HOTKEY': 'windows_api',
    'WM_KEYDOWN': 'windows_api',
    'WM_KEYUP': 'windows_api',
    'WM_LBUTTONUP': 'windows_api',
    'WM_PASTE': 'windows_api',
    'WM_RBUTTONUP': 'windows_api',
    'WM_SYSKEYDOWN': 'windows_api',
    'WM_SYSKEYUP': 'windows_api',
    'WM_TRAY': 'windows_api',
    'WM_USER': 'windows_api',
    'WNDCLASS': 'windows_api',
    'WNDPROC': 'windows_api',
    'WS_CAPTION': 'windows_api',
    '_DESKTOP_CLASSES': 'windows_geometry',
    '_INPUTUNION': 'windows_api',
    '_OEM_BASE': 'windows_hooks',
    '_OEM_SHIFT': 'windows_hooks',
    '_dwm': 'windows_api',
    'gdi32': 'windows_api',
    'shcore': 'windows_api',
    '_focus_class_name': 'windows_focus',
    '_hook': 'windows_hooks',
    '_hook_cb': 'windows_hooks',
    '_hook_stop': 'windows_hooks',
    '_hook_thread': 'windows_hooks',
    '_hook_tid': 'windows_hooks',
    '_hook_lock': 'windows_hooks',
    'HOOK_START_TIMEOUT': 'windows_hooks',
    'HOOK_STOP_TIMEOUT': 'windows_hooks',
    'PASTE_MESSAGE_TIMEOUT_MS': 'windows_focus',
    'SMTO_ABORTIFHUNG': 'windows_api',
    'WM_QUIT': 'windows_api',
    'PM_NOREMOVE': 'windows_api',
    '_integrity_of': 'windows_focus',
    '_kbd': 'windows_input',
    '_pid_integrity': 'windows_focus',
    'advapi': 'windows_api',
    'all_keys_up': 'windows_input',
    'apply_window_effects': 'windows_effects',
    'autostart_cmd': 'windows_system',
    'can_paste_message': 'windows_focus',
    'capture_source': 'windows_system',
    'class_name_of': 'windows_geometry',
    'cpu_ms': 'windows_system',
    'dpi_scale': 'windows_system',
    'force_foreground': 'windows_focus',
    'get_autostart': 'windows_system',
    'has_caption': 'windows_geometry',
    'init_dpi_awareness': 'windows_system',
    'is_elevated_hwnd': 'windows_focus',
    'is_fullscreen_window': 'windows_geometry',
    'is_zoomed': 'windows_geometry',
    'k32': 'windows_api',
    'mem_mb': 'windows_system',
    'monitor_rect_of': 'windows_geometry',
    'monitors': 'windows_geometry',
    'paste_message': 'windows_focus',
    'proc_name_of': 'windows_system',
    'psapi': 'windows_api',
    'rect_covers': 'windows_geometry',
    'rects_overlap': 'windows_geometry',
    'send_backspaces': 'windows_input',
    'send_ctrl_v': 'windows_input',
    'send_key': 'windows_input',
    'set_acrylic': 'windows_effects',
    'set_autostart': 'windows_system',
    'set_rounded': 'windows_effects',
    'sh32': 'windows_api',
    'shell32': 'windows_api',
    'single_instance': 'windows_system',
    'start_keyboard_hook': 'windows_hooks',
    'stop_keyboard_hook': 'windows_hooks',
    'system_dpi': 'windows_system',
    'target_focus_hwnd': 'windows_focus',
    'top_hwnd': 'windows_geometry',
    'u32': 'windows_api',
    'visible_ratio': 'windows_geometry',
    'vk_to_char': 'windows_hooks',
    'window_rect': 'windows_geometry',
    'window_title_of': 'windows_system'
}
_OWNERS = {name: globals()[module] for name, module in _OWNER_NAMES.items()}
__all__ = sorted({name for name in _OWNERS if not name.startswith('_')} | {
    'ctypes', 'os', 'sys', 'time', 'threading', 'winreg', 'wintypes', 'APP_NAME', 'BASE_DIR',
})


def __getattr__(name):
    owner = _OWNERS.get(name)
    if owner is not None:
        return getattr(owner, name)
    raise AttributeError("module %r has no attribute %r" % (__name__, name))


def __dir__():
    return sorted(set(globals()) | set(_OWNERS))


class _CompatibilityModule(types.ModuleType):
    def __setattr__(self, name, value):
        owner = _OWNERS.get(name)
        if owner is None:
            super().__setattr__(name, value)
            if name in ('ctypes', 'os', 'sys', 'time', 'threading', 'winreg',
                        'wintypes', 'APP_NAME', 'BASE_DIR'):
                for module in _MODULES:
                    if name in vars(module):
                        setattr(module, name, value)
            return
        # 旧回归会替换 W.monitors/W.window_rect；同时更新引用它的适配器，
        # 避免 facade 名称变了、实际函数却仍调用导入时旧对象的隐蔽分叉。
        setattr(owner, name, value)
        for module in _MODULES:
            if module is not owner and name in vars(module):
                setattr(module, name, value)

    def __delattr__(self, name):
        owner = _OWNERS.get(name)
        if owner is None:
            return super().__delattr__(name)
        # mock.patch 把 __getattr__ 导出视为非本地属性：退出时先 delattr，
        # 再用 setattr 恢复。只删定义端，保留消费者引用，让恢复时的转发
        # 仍能找到并更新它们；避免内层 patch 留下外层/内层的临时对象。
        delattr(owner, name)


sys.modules[__name__].__class__ = _CompatibilityModule
