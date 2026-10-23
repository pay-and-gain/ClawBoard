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
        sent = u32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) == 1
    except Exception:
        return False
    if gap:
        time.sleep(gap)
    return sent


def _send_batch(events):
    """同一批次不被其它 SendInput 插入；只把完整注入当作成功。"""
    if not events:
        return True
    try:
        batch = (INPUT * len(events))(*events)
        return u32.SendInput(len(events), batch, ctypes.sizeof(INPUT)) == len(events)
    except Exception:
        return False

def all_keys_up(gap=0.005):
    """发键前先抬起所有还按着的修饰键。
    Ditto SendKeys.cpp:237 的 AllKeysUp：用户按着 Ctrl 唤起面板时，残留的 Ctrl
    会把我们的 Ctrl+V 变成 Ctrl+Ctrl+V，目标程序收到的是裸 V，粘贴就"失灵"了。"""
    events = []
    for vk in MODIFIER_VKS:
        try:
            if u32.GetAsyncKeyState(vk) & 0x8000:
                events.append(_kbd(vk, up=True))
        except Exception:
            return False
    sent = _send_batch(events)
    if events and gap:
        time.sleep(gap)
    return sent

def send_ctrl_v():
    """Ctrl+V；返回系统是否接受全部事件，不保证目标程序已处理。"""
    return send_replacement(0)


def send_replacement(backspaces, *, guard=None):
    """触发词删除与粘贴放在一个批次，避免两个注入序列彼此穿插。"""
    if not all_keys_up():
        return False
    events = []
    for _ in range(max(0, int(backspaces))):
        events.extend((_kbd(VK_BACK), _kbd(VK_BACK, up=True)))
    events.extend((_kbd(VK_CONTROL), _kbd(VK_V),
                   _kbd(VK_V, up=True), _kbd(VK_CONTROL, up=True)))
    if guard is not None:
        try:
            if not guard():
                return False
        except Exception:
            return False
    sent = _send_batch(events)
    if not sent:
        # 部分注入可能留下按住的 Ctrl/V/退格；清理不能把失败改报成功。
        _send_batch([_kbd(vk, up=True) for vk in (VK_BACK, VK_V, VK_CONTROL)])
    return sent

def send_backspaces(n, gap=0.018):
    """连发 n 次退格（触发词替换：删掉刚输入的触发词 + 分隔符）。"""
    for _ in range(max(0, int(n))):
        if not _send_batch([_kbd(VK_BACK), _kbd(VK_BACK, up=True)]):
            send_key(VK_BACK, up=True, gap=0)
            return False
        if gap:
            time.sleep(gap)
    return True
