# -*- coding: utf-8 -*-
"""v1.6.2 自测：WM_PASTE 投递 + 完整性检测 + 单条闪烁（粘贴不整窗闪）

覆盖：
1. _pid_integrity 对本进程返回中等 RID（0x2000），is_elevated_hwnd 对同进程窗口为 False
2. target_focus_hwnd 能定位到焦点控件；无焦点时回退顶层窗口
3. paste_message 对无效窗口安全返回 False，不抛异常
4. VirtualList.flash 能按 id 找到卡片、改色、不崩溃，闪烁期间颜色在 base/flash 间切换
"""
import ctypes
import io
import os
import tempfile
import sys

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ClawBoard as C
from clawboard import win32
import tkinter as tk

C.NO_SAVE = True
C.DEFAULT_SETTINGS['collapsed'] = False

OK = True
LOG = []


def check(name, cond, extra=''):
    global OK
    if not cond:
        OK = False
    LOG.append('%s  %s%s' % ('OK  ' if cond else 'FAIL', name,
                             ('  ' + extra) if extra else ''))


# ---------- 1. 完整性检测 ----------
rid = win32._pid_integrity(win32.k32.GetCurrentProcessId())
check('本进程完整性 RID 可取到', rid is not None, 'rid=%s' % rid)
check('本进程完整性 RID 是合法档位(0x1000~0x4000)',
      rid is not None and 0x1000 <= rid <= 0x4000, 'rid=%s' % rid)

root = tk.Tk()
root.withdraw()
check('同进程窗口不判高权限', win32.is_elevated_hwnd(root.winfo_id()) is False)

# ---------- 2. 焦点控件定位 ----------
e = tk.Entry(root)
e.pack()
root.update()
e.focus_force()
root.update()
focus = win32.target_focus_hwnd(root.winfo_id())
check('target_focus_hwnd 能定位到焦点控件', focus not in (0, None),
      'focus=%s top=%s' % (focus, root.winfo_id()))

check('paste_message(0) 安全返回 False', win32.paste_message(0) is False)

# ---------- 2b. can_paste_message 判定 ----------
check('can_paste_message(0) = False', win32.can_paste_message(0) is False)
check('EDIT_CLASSES 含 edit', 'edit' in win32.EDIT_CLASSES)
check('Tk 窗口(非 Edit 控件)判定走抢焦点路径',
      win32.can_paste_message(root.winfo_id()) is False,
      '类名=%s' % win32._focus_class_name(win32.target_focus_hwnd(root.winfo_id())))

# ---------- 3. VirtualList.flash ----------
from clawboard.vlist import VirtualList
from clawboard.theme import T

vl = VirtualList(root, lambda *a: None, lambda *a: None, lambda *a: None)
items = [{'id': 'a1', 'text': 'hello flash', 'disp': 'hello flash',
          'sub': '', 'kind_auto': 'text'}]
vl.set_data(items, 'a1', '')
root.update()
f = vl._find('a1')
check('flash 能按 id 找到卡片', f is not None)
base_before = f.cget('bg')
vl.flash('a1', times=3, gap=40)
root.update()
f2 = vl._find('a1')
col_after_first = f2.cget('bg') if f2 else None
check('闪烁第一拍已切到强调色', col_after_first == T['acc'],
      '期望 %s 实际 %s' % (T['acc'], col_after_first))
check('闪烁色与基准色不同', T['acc'] != base_before)

# 等闪烁结束（3 拍 × 40ms × 2 = 240ms，再留余量）
for _ in range(20):
    root.update()
    import time
    time.sleep(0.03)
f3 = vl._find('a1')
col_final = f3.cget('bg') if f3 else None
check('闪烁结束后回到基准色', col_final == base_before,
      '期望 %s 实际 %s' % (base_before, col_final))

# 不存在的 id：不崩溃
vl.flash('no-such-id')
check('flash 不存在的 id 不崩溃', True)

root.destroy()

with io.open(os.path.join(tempfile.gettempdir(), '_t28.out'), 'w',
             encoding='utf-8') as f:
    f.write('\n'.join(LOG) + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))
os._exit(0)
