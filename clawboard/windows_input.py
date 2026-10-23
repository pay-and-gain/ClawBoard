# -*- coding: utf-8 -*-
"""键盘输入原语：SendInput 结构、修饰键释放与按键序列。"""
import ctypes
import time

from clawboard.windows_api import (
    INPUT, INPUT_KEYBOARD, KEYEVENTF_KEYUP, MODIFIER_VKS, VK_BACK, VK_CONTROL, VK_V,
    u32,
)


def _kbd(vk, up=False):
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.u.ki.wVk = vk
    inp.u.ki.wScan = u32.MapVirtualKeyW(vk, 0)      # 带扫描码，兼容性更好
    inp.u.ki.dwFlags = KEYEVENTF_KEYUP if up else 0
    return inp

def send_key(vk, up=False, gap=0.01):
    try:
        inp = _kbd(vk, up)
        u32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    except Exception:
        return
    if gap:
        time.sleep(gap)

def all_keys_up(gap=0.005):
    """发键前先抬起所有还按着的修饰键。
    Ditto SendKeys.cpp:237 的 AllKeysUp：用户按着 Ctrl 唤起面板时，残留的 Ctrl
    会把我们的 Ctrl+V 变成 Ctrl+Ctrl+V，目标程序收到的是裸 V，粘贴就"失灵"了。"""
    for vk in MODIFIER_VKS:
        try:
            if u32.GetAsyncKeyState(vk) & 0x8000:
                send_key(vk, up=True, gap=gap)
        except Exception:
            pass

def send_ctrl_v():
    """Ctrl+V。改用 SendInput：一次一个事件、带扫描码，比已废弃的 keybd_event 可靠"""
    all_keys_up()
    send_key(VK_CONTROL, gap=0.008)
    send_key(VK_V, gap=0.012)
    send_key(VK_V, up=True, gap=0.008)
    send_key(VK_CONTROL, up=True, gap=0)

def send_backspaces(n, gap=0.018):
    """连发 n 次退格（触发词替换：删掉刚输入的触发词 + 分隔符）。"""
    for _ in range(max(0, int(n))):
        send_key(VK_BACK, gap=gap)
