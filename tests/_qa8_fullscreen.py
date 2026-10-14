# -*- coding: utf-8 -*-
"""QA 独立验证 —— 「全屏程序前台时面板不再置顶」(commit 2aa33e2 + 539cc9d)

QA: 严过关 (software-qa-engineer-3)
独立于工程师的 tests/_t41.py：换角度 / 边界 / 错误路径 / 真实双屏 / 真实最大化窗口。
含 539cc9d 的两项修复回归：① 有标题栏的最大化普通窗口不算全屏；② 粘贴「让位」
进行中（_topmost_yield）不被 poll_bg 的 sync_topmost 撤销。

约定：
- **不改产品源码**；测试里 **绝不真进全屏**（monkeypatch 取数或构造矩形）。
- 构造 App 前把 app_services.DATA_FILE 与 timefmt.DATA_FILE **两个**都指向临时目录，
  并置 runtime.NO_SAVE = True。
- 本机为**真实双屏**：主屏 (0,0,2560,1440)，副屏 (2560,157,5120,1757)（不同分辨率）。
"""
import ctypes
import glob
import hashlib
import os
import subprocess
import sys
import tempfile
import time
import types

# 与产品一致的 DPI 感知（必须在读窗口几何之前）
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ---- 重定向落盘目标（必须在 import 业务模块之前）----
TMP_DIR = tempfile.mkdtemp(prefix='cb_qa8_')
TMP_DATA = os.path.join(TMP_DIR, 'ClawBoard数据.json')

import clawboard.app_services as S            # noqa: E402
S.DATA_FILE = TMP_DATA
S.CRASH_LOG = os.path.join(TMP_DIR, 'crash.log')

import clawboard.timefmt as TF                # noqa: E402
TF.DATA_FILE = TMP_DATA

from clawboard import runtime as RT           # noqa: E402
RT.NO_SAVE = True

import clawboard.win32 as W                    # noqa: E402
from clawboard.win32 import (rect_covers, is_fullscreen_window, monitor_rect_of,
                             class_name_of, window_rect, top_hwnd, monitors)  # noqa: E402
from ctypes import wintypes                    # noqa: E402

OK = True
LOG = []


def check(name, cond, extra=''):
    global OK
    if not cond:
        OK = False
    LOG.append('%s  %s%s' % ('OK  ' if cond else 'FAIL', name,
                             ('  ' + extra) if extra else ''))


def note(msg):
    LOG.append('....  ' + msg)


def section(t):
    LOG.append('')
    LOG.append('== %s ==' % t)


REAL_DATA = os.path.join(ROOT, 'ClawBoard数据.json')


def file_hash(p):
    try:
        with open(p, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return None


def sidecars():
    return sorted(os.path.basename(p) for p in glob.glob(REAL_DATA + '*'))


HASH0 = file_hash(REAL_DATA)
FILES0 = sidecars()

# ============================================================
# A. rect_covers 纯逻辑（逐边 / 容差 / 半覆盖 / 空矩形 / 反向）
# ============================================================
section('A. rect_covers 纯逻辑')
MON = (0, 0, 2560, 1440)
check('A1 完全重合 → True', rect_covers(MON, MON) is True)
check('A2 每边内缩 1px → True', rect_covers((1, 1, 2559, 1439), MON) is True)
check('A3 每边内缩 2px（容差边界）→ True',
      rect_covers((2, 2, 2558, 1438), MON) is True)
check('A4 每边内缩 3px（超容差）→ False',
      rect_covers((3, 3, 2557, 1437), MON) is False)
# 逐边单侧，确认四个方向对称
check('A5 仅上边多 2px → True', rect_covers((0, 2, 2560, 1440), MON) is True)
check('A6 仅上边多 3px → False', rect_covers((0, 3, 2560, 1440), MON) is False)
check('A7 仅右边少 2px → True', rect_covers((0, 0, 2558, 1440), MON) is True)
check('A8 仅右边少 3px → False', rect_covers((0, 0, 2557, 1440), MON) is False)
check('A9 仅下边少 2px → True', rect_covers((0, 0, 2560, 1438), MON) is True)
check('A10 仅下边少 3px → False', rect_covers((0, 0, 2560, 1437), MON) is False)
check('A11 仅左边多出 2px → True', rect_covers((2, 0, 2560, 1440), MON) is True)
check('A12 仅左边多出 3px → False', rect_covers((3, 0, 2560, 1440), MON) is False)
# 半覆盖
check('A13 只覆盖左半 → False', rect_covers((0, 0, 1280, 1440), MON) is False)
check('A14 只覆盖上半 → False', rect_covers((0, 0, 2560, 720), MON) is False)
check('A15 只覆盖右下角 1x1 → False', rect_covers((2559, 1439, 2560, 1440), MON) is False)
# 空 / 零尺寸
check('A16 空矩形 (0,0,0,0) → False', rect_covers((0, 0, 0, 0), MON) is False)
check('A17 零宽 → False', rect_covers((10, 10, 10, 1440), MON) is False)
# 反转矩形（left>right）不应被判为覆盖
check('A18 反转矩形 → False', rect_covers((2000, 1000, 100, 100), MON) is False)
# 比显示器更大（含负坐标）
check('A19 比显示器大 1px → True', rect_covers((-1, -1, 2561, 1441), MON) is True)
check('A20 比显示器大很多 → True', rect_covers((-500, -500, 4000, 3000), MON) is True)
# 偏移但不越界
check('A21 整体右移 2px → True（容差内）', rect_covers((2, 0, 2562, 1440), MON) is True)
check('A22 整体右移 5px → False', rect_covers((5, 0, 2565, 1440), MON) is False)
# None / 非法输入
check('A23 None 输入 → False', rect_covers(None, MON) is False
      and rect_covers(MON, None) is False)

# ============================================================
# A2. 真实多屏：monitor_rect_of 取「窗口所在显示器」
# ============================================================
section('A2. 真实多屏（本机双屏，不同分辨率）')
MONS = monitors()
note('本机显示器: %r' % (MONS,))
check('A24 至少两块显示器（真实多屏前提）', len(MONS) >= 2, 'got=%d' % len(MONS))


def _mon_containing(x, y):
    for (l, t, r, b) in MONS:
        if l <= x < r and t <= y < b:
            return (l, t, r, b)
    return None


import tkinter as tk          # noqa: E402


def _make_window(geom):
    r = tk.Tk()
    r.geometry(geom)
    r.update()
    r.update_idletasks()
    time.sleep(0.25)
    r.update()
    return r


# 把窗口放到「第二块显示器」上（其左上角原点非 0）
second = max(MONS, key=lambda m: m[0])       # x 原点最大者 = 副屏
primary = _mon_containing(1, 1)              # 含 (0,0) 者 = 主屏
note('主屏=%r 副屏=%r' % (primary, second))
gx, gy = second[0] + 40, second[1] + 40
r_sec = _make_window('500x360+%d+%d' % (gx, gy))
h_sec = top_hwnd(r_sec)
mr_sec = monitor_rect_of(h_sec)
exp_sec = _mon_containing(gx + 250, gy + 180)
check('A25 副屏窗口 monitor_rect_of == 窗口所在显示器（非主屏）',
      bool(exp_sec) and mr_sec == exp_sec and mr_sec != primary,
      'got=%r expected=%r primary=%r' % (mr_sec, exp_sec, primary))

# 副屏窗口即使「覆盖副屏」→ True；用主屏尺寸比 → False
_owr, _omr, _ocn = W.window_rect, W.monitor_rect_of, W.class_name_of
_oiz, _ohc = W.is_zoomed, W.has_caption      # 539cc9d 新增的两个判据
W.window_rect = lambda h: second
W.monitor_rect_of = lambda h: second
W.class_name_of = lambda h: 'chrome_widgetwin_1'
W.is_zoomed = lambda h: False                # 本段只测几何，中性化状态判据
W.has_caption = lambda h: False
check('A26 副屏全屏（用所在显示器）→ True',
      W.is_fullscreen_window(0x1234, 0) is True)
W.monitor_rect_of = lambda h: primary
check('A27 副屏窗口误用主屏尺寸 → False（证明必须用所在显示器）',
      W.is_fullscreen_window(0x1234, 0) is False)
W.window_rect, W.monitor_rect_of, W.class_name_of = _owr, _omr, _ocn
W.is_zoomed, W.has_caption = _oiz, _ohc
try:
    r_sec.destroy()
except Exception:
    pass

# ============================================================
# A3. 排除项：句柄 0 / 面板自己 / 桌面与 Shell（大小写）
# ============================================================
section('A3. 排除项与类名大小写')
check('A28 句柄 0 → False', is_fullscreen_window(0) is False)
check('A29 面板自己（self_hwnd 相等）→ False',
      W.is_fullscreen_window(0x1234, 0x1234) is False)


def _sim(win, mon, cls):
    W.window_rect = lambda h: win
    W.monitor_rect_of = lambda h: mon
    W.class_name_of = lambda h: cls
    W.is_zoomed = lambda h: False             # 本段只测排除类名，中性化状态判据
    W.has_caption = lambda h: False
    return W.is_fullscreen_window(0x1234, 0)


for cls in ('progman', 'Progman', 'PROGMAN', 'workerw', 'WorkerW',
            'shell_traywnd', 'Shell_TrayWnd', 'SHELL_TRAYWND',
            'shell_secondarytraywnd', 'Shell_SecondaryTrayWnd'):
    check('A30 排除类 %-24s → False' % cls,
          _sim(MON, MON, cls) is False)
check('A31 普通类 chrome_widgetwin_1 满屏 → True',
      _sim(MON, MON, 'chrome_widgetwin_1') is True)
W.window_rect, W.monitor_rect_of, W.class_name_of = _owr, _omr, _ocn
W.is_zoomed, W.has_caption = _oiz, _ohc

# 真实 class_name_of 是否真返回「小写」并可被正确匹配
_desktop = ctypes.windll.user32.GetDesktopWindow()
cn = class_name_of(_desktop)
check('A32 真实 class_name_of 返回 str 且已小写', isinstance(cn, str) and cn == cn.lower(),
      'class=%r' % cn)

# ============================================================
# A4. 错误路径：任何取数失败都不得抛，且判为 False
# ============================================================
section('A4. 错误路径（不抛 + False）')
# 4a window_rect 取不到
W.window_rect = lambda h: None
W.monitor_rect_of = lambda h: MON
W.class_name_of = lambda h: 'chrome_widgetwin_1'
check('A33 window_rect=None → False 且不抛',
      W.is_fullscreen_window(0x1234, 0) is False)
# 4b monitor_rect_of 取不到
W.window_rect = lambda h: MON
W.monitor_rect_of = lambda h: None
check('A34 monitor_rect_of=None → False 且不抛',
      W.is_fullscreen_window(0x1234, 0) is False)
W.window_rect, W.monitor_rect_of, W.class_name_of = _owr, _omr, _ocn

# 4c 真实 monitor_rect_of：MonitorFromWindow 返回 0
_omfw = W.u32.MonitorFromWindow
W.u32.MonitorFromWindow = lambda *a, **k: 0
try:
    check('A35 MonitorFromWindow=0 → monitor_rect_of 返回 None 且不抛',
          W.monitor_rect_of(0x1234) is None)
finally:
    W.u32.MonitorFromWindow = _omfw
# 4d 真实 monitor_rect_of：GetMonitorInfoW 失败
_omfw = W.u32.MonitorFromWindow
_ogmi = W.u32.GetMonitorInfoW
W.u32.MonitorFromWindow = lambda *a, **k: 1        # 非 0 句柄
W.u32.GetMonitorInfoW = lambda *a, **k: 0          # 失败
try:
    check('A36 GetMonitorInfoW 失败 → monitor_rect_of 返回 None 且不抛',
          W.monitor_rect_of(0x1234) is None)
finally:
    W.u32.MonitorFromWindow = _omfw
    W.u32.GetMonitorInfoW = _ogmi
# 4e 异常 hwnd 值不抛
weird_ok = True
for hv in (0, -1, 2 ** 63, 0xDEADBEEF):
    try:
        v = is_fullscreen_window(hv, 0)
        assert isinstance(v, bool)
    except Exception as e:
        weird_ok = False
        note('hwnd=%r 抛异常: %r' % (hv, e))
check('A37 异常 hwnd（0/-1/huge）→ 返回 bool 不抛', weird_ok)
check('A38 monitor_rect_of(0) → None', monitor_rect_of(0) is None)
check('A39 class_name_of(0) → str 不抛', isinstance(class_name_of(0), str))
# 539cc9d 新增判据的错误路径
check('A40 is_zoomed(0)/has_caption(0) → False 且不抛',
      W.is_zoomed(0) is False and W.has_caption(0) is False)
check('A41 is_zoomed/has_caption 异常 hwnd → 返回 bool 不抛',
      all(isinstance(W.is_zoomed(v), bool) and isinstance(W.has_caption(v), bool)
          for v in (0, -1, 2 ** 63, 0xDEADBEEF)))

# ============================================================
# B. ⚠️ 副作用实测：真实「最大化窗口」是否被误判为全屏
# ============================================================
section('B. 副作用实测（真实最大化窗口 / 任务栏自动隐藏）')
note('标注：[真机] = 真实窗口实测；[构造] = stub 构造矩形/状态')
u32 = W.u32
mi = W.MONITORINFO()
mi.cbSize = ctypes.sizeof(W.MONITORINFO)

r_max = _make_window('600x420+%d+%d' % (gx, gy))
h_max = top_hwnd(r_max)
u32.ShowWindow(wintypes.HWND(h_max), 3)          # SW_MAXIMIZE
time.sleep(0.4)
r_max.update()
wr = window_rect(h_max)
mr = monitor_rect_of(h_max)
hmon = u32.MonitorFromWindow(wintypes.HWND(h_max), 2)
u32.GetMonitorInfoW(hmon, ctypes.byref(mi))
work = (mi.rcWork.left, mi.rcWork.top, mi.rcWork.right, mi.rcWork.bottom)
note('最大化窗口 GetWindowRect = %r' % (wr,))
note('所在显示器 rcMonitor     = %r' % (mr,))
note('所在显示器 rcWork        = %r' % (work,))
covers_mon = rect_covers(wr, mr)
covers_work = rect_covers(wr, work)
note('rect_covers(win, rcMonitor) = %s ; rect_covers(win, rcWork) = %s'
     % (covers_mon, covers_work))
check('B1 任务栏可见时，真实最大化窗口 不 被判为全屏（covers_mon=False）',
      covers_mon is False)
check('B2 最大化窗口矩形覆盖工作区（covers_work=True，机制成立）',
      covers_work is True)
note('真实 is_fullscreen_window(最大化窗口) = %s' % is_fullscreen_window(h_max))
_z, _c = W.is_zoomed(h_max), W.has_caption(h_max)
note('最大化窗口 is_zoomed=%s has_caption=%s' % (_z, _c))

# 旧口径（仅几何）在任务栏自动隐藏时会误判
W.window_rect = lambda h: wr
W.monitor_rect_of = lambda h: work            # 模拟 rcWork == rcMonitor（自动隐藏）
W.class_name_of = lambda h: 'chrome_widgetwin_1'
W.is_zoomed = lambda h: False                 # 关掉新排除 → 复原旧口径
W.has_caption = lambda h: False
old_rule = W.is_fullscreen_window(0x1234, 0)
# 新口径（539cc9d）：有标题栏的最大化窗口应被排除
W.is_zoomed = lambda h: True
W.has_caption = lambda h: True
new_rule = W.is_fullscreen_window(0x1234, 0)
note('模拟自动隐藏：旧口径=%s  新口径(zoomed+caption)=%s' % (old_rule, new_rule))
check('B3 复现旧口径副作用：自动隐藏时最大化普通窗口被误判为全屏',
      old_rule is True)
check('B4 新排除生效：有标题栏的最大化普通窗口不再被判全屏',
      new_rule is False)
check('B5 真实最大化普通窗口 is_zoomed=True 且 有标题栏',
      _z is True and _c is True)

# 三类真全屏不得被新排除误伤（窗口正好覆盖所在显示器）
W.window_rect = lambda h: mr
W.monitor_rect_of = lambda h: mr
W.class_name_of = lambda h: 'chrome_widgetwin_1'
W.is_zoomed = lambda h: False
W.has_caption = lambda h: False
check('B6 独占 / F11 全屏（非 zoomed）→ True', W.is_fullscreen_window(0x1234, 0) is True)
W.is_zoomed = lambda h: True
W.has_caption = lambda h: False
check('B7 无边框窗口化全屏（zoomed 但无标题栏）→ True',
      W.is_fullscreen_window(0x1234, 0) is True)
W.is_zoomed = lambda h: False
W.has_caption = lambda h: True
check('B8 有标题栏但非 zoomed 的满屏窗口 → True',
      W.is_fullscreen_window(0x1234, 0) is True)
note('[构造] 取舍评估：若判据只用 IsZoomed（不加 has_caption），B7 的'
     '「无边框窗口化全屏」会被误杀为"非全屏"；加 has_caption 后恰好保号 → 该取舍成立')
# 真实的「有标题栏、未最大化」普通窗口：has_caption=True 且 is_zoomed=False
# → 不会命中新排除（新排除只吃 zoomed 的情形）。
# 注：Tk 的 overrideredirect 顶层窗口经 top_hwnd 取到的是包装窗口，样式不稳定，
#     故「无边框窗口」这一类用上面的 stub 用例（B6/B7）覆盖，不用真实 Tk 窗口取样式。
r_norm = _make_window('300x200+%d+%d' % (gx, gy))
h_norm = top_hwnd(r_norm)
check('B9 真实普通（非最大化）窗口 has_caption=True 且 is_zoomed=False',
      W.has_caption(h_norm) is True and W.is_zoomed(h_norm) is False,
      'cap=%s zoom=%s' % (W.has_caption(h_norm), W.is_zoomed(h_norm)))
try:
    r_norm.destroy()
except Exception:
    pass
# 还原取数
W.window_rect, W.monitor_rect_of, W.class_name_of = _owr, _omr, _ocn
W.is_zoomed, W.has_caption = _oiz, _ohc
try:
    r_max.destroy()
except Exception:
    pass

# ============================================================
# C. 置顶状态机（GUI，stub 全屏检测，绝不真进全屏）
# ============================================================
section('C. 置顶状态机')
import ClawBoard as C          # noqa: E402
C.NO_SAVE = True

# 独立检查 config.AppState 默认语义
from clawboard.config import AppState        # noqa: E402
_d = AppState()
check('C0 AppState 默认: _topmost_user=True / _user_pulled=False / '
      '_fg_fullscreen=False / _topmost_yield=False / _topmost_applied=None',
      _d._topmost_user is True and _d._user_pulled is False
      and _d._fg_fullscreen is False and _d._topmost_yield is False
      and _d._topmost_applied is None)

FS = {'on': False}
S.is_fullscreen_window = lambda *a, **k: FS['on']
S.top_hwnd = lambda r: 1                      # 面板顶层句柄：永不等于真实前台
# 冻结后台轮询对状态的干扰：本段只手动驱动 sync_topmost
_S_poll = S.SystemMixin.poll_bg               # poll_bg 定义在 SystemMixin
S.SystemMixin.poll_bg = lambda self: None     # 关掉自动轮询，测试完全可控

root = tk.Tk()
root.geometry('420x560+80+80')
app = C.ClawBoard(root)
root.update()


def topmost():
    try:
        return bool(int(app.root.attributes('-topmost')))
    except Exception:
        return bool(app.root.attributes('-topmost'))


def set_fs(on):
    FS['on'] = on
    app._fg_fullscreen = on
    app.sync_topmost()


# --- 去重验证：包一层统计真正写 attributes 的次数 ---
_writes = []
_orig_attr = app.root.attributes


def _spy(*a, **k):
    if a and a[0] == '-topmost' and len(a) > 1:
        _writes.append(a[1])
    return _orig_attr(*a, **k)


app.root.attributes = _spy

app._topmost_user = True
app._user_pulled = False
set_fs(False)
check('C1 初始（非全屏）→ 实际置顶 True', topmost() is True)
n0 = len(_writes)
for _ in range(5):
    app.sync_topmost()
check('C2 _topmost_applied 去重：状态不变时 5 次 sync 不重复写',
      len(_writes) == n0, 'writes=%r' % _writes)

# 进/出全屏
set_fs(True)
check('C3 进全屏（未呼出）→ -topmost 变 False', topmost() is False)
check('C4 进全屏后面板仍可见（未隐藏）',
      app.root.winfo_ismapped() and app.hidden is False)
set_fs(False)
check('C5 退全屏 → 恢复 True', topmost() is True)

# ⚠️ 关键：用户先取消置顶，再进/出全屏，不得被强行改回 True
app.toggle_pin()
check('C6 toggle_pin 取消置顶 → False & _topmost_user=False',
      topmost() is False and app._topmost_user is False)
set_fs(True)
check('C7 取消置顶 + 进全屏 → 仍 False', topmost() is False)
set_fs(False)
check('C8 取消置顶 + 出全屏 → 仍 False（不被强行改回）',
      topmost() is False and app._topmost_user is False)
# 来回切一致性
app.toggle_pin()
check('C9 toggle_pin 恢复 → True & 一致',
      topmost() is True and app._topmost_user is True)
app.toggle_pin()
check('C10 toggle_pin 再取消 → False & 一致',
      topmost() is False and app._topmost_user is False)
app.toggle_pin()
check('C11 toggle_pin 再恢复 → True & 一致',
      topmost() is True and app._topmost_user is True)

# 539cc9d 新增：_topmost_yield（让位进行中）纳入抑制
app._topmost_user = True
app._user_pulled = False
app._fg_fullscreen = False
app._topmost_yield = True
app._topmost_applied = True
app.root.attributes('-topmost', True)
app.sync_topmost()
check('C12 非全屏但「让位进行中」→ 取消置顶', topmost() is False)
app._topmost_yield = False
app.sync_topmost()
check('C13 让位结束（非全屏）→ 恢复置顶', topmost() is True)

# ============================================================
# D. 呼出 / 隐藏交互
# ============================================================
section('D. 呼出 / 隐藏交互')
# 全屏中呼出 → 置顶可见
app._topmost_user = True
app._topmost_applied = True
app.root.attributes('-topmost', True)
app._fg_fullscreen = True
app.hidden = True
app._user_pulled = False
app.sync_topmost()
check('D1 全屏 + 隐藏 → 不置顶', topmost() is False)
app.toggle_show()
root.update()
check('D2 全屏中呼出 → 置顶可见 & 未隐藏',
      topmost() is True and app.hidden is False and app._user_pulled is True)
app.hide()
check('D3 呼出后 hide() → _user_pulled 清除 & 又被抑制',
      app._user_pulled is False and topmost() is False)
# reset_position 置 _user_pulled
app._user_pulled = False
app._fg_fullscreen = True
app.sync_topmost()
app.reset_position()
check('D4 reset_position → _user_pulled=True & 置顶可见',
      app._user_pulled is True and topmost() is True)
app.hide()
# _need_show 路径（真实 poll_bg 单次迭代）
S.SystemMixin.poll_bg = _S_poll               # 临时恢复真实 poll_bg
app._user_pulled = False
app._fg_fullscreen = True
app.hidden = True
app.root.withdraw()
app.sync_topmost()
app._need_show = True
app.poll_bg()                                 # 走一次真实迭代后即关闭
S.SystemMixin.poll_bg = lambda self: None
check('D5 _need_show → _user_pulled=True（后台请求显示=主动呼出）',
      app._user_pulled is True)
# 边界：_user_pulled=True 时用户又取消置顶 → 用户意图优先（False）
app._user_pulled = True
app._topmost_user = True
app.sync_topmost()
check('D6 呼出且未取消置顶 → True', topmost() is True)
app.toggle_pin()                              # 取消置顶
check('D7 呼出中取消置顶 → False（用户意图优先于 _user_pulled）',
      topmost() is False and app._topmost_user is False)
app.toggle_pin()                              # 还原置顶意图
app._user_pulled = False

# D8/D9：走**真实 poll_bg**（非手动 sync_topmost），验证前台变化→内部状态→置顶
S.SystemMixin.poll_bg = _S_poll
_ogfw = S.u32.GetForegroundWindow
S.u32.GetForegroundWindow = lambda: 0xABCDEF   # 任意非面板句柄
S.is_fullscreen_window = lambda *a, **k: True
FS['on'] = True
app._topmost_user = True
app._user_pulled = False
app._fg_fullscreen = False
app._topmost_applied = True
app.root.attributes('-topmost', True)
app.poll_bg()
check('D8 真实 poll_bg：前台=全屏程序 → _fg_fullscreen=True 且取消置顶',
      app._fg_fullscreen is True and topmost() is False)
S.u32.GetForegroundWindow = lambda: 0          # 前台句柄取不到
app._fg_fullscreen = True
app.poll_bg()
check('D9 GetForegroundWindow 返回 0 → _fg_fullscreen=False（不抛）',
      app._fg_fullscreen is False)
S.u32.GetForegroundWindow = _ogfw
S.is_fullscreen_window = lambda *a, **k: FS['on']
S.SystemMixin.poll_bg = lambda self: None

# ============================================================
# E. 粘贴让位路径（重点）
# ============================================================
section('E. 粘贴让位路径')
import clawboard.app_interact as AI          # noqa: E402
import clawboard.config as CFG               # noqa: E402


class _FakeThread:
    def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
        self.target = target
        self.args = args

    def start(self):
        pass                                    # 不真起线程：避免副作用


def _install_paste_stubs():
    AI.threading = types.SimpleNamespace(Thread=_FakeThread)
    AI.can_paste_message = lambda h: False      # 强制走「抢焦点 + Ctrl/V（让位）」分支
    app.write_clip = lambda t: True
    app.trim_for_paste = lambda t: t
    app._panel_overlaps = lambda h: True
    app.save = lambda *a, **k: None
    app.st['autopaste'] = True
    app.hidden = False
    app.prev_hwnd = 0x9999
    app._topmost_user = True
    app._fg_fullscreen = False
    app._user_pulled = False
    app._topmost_yield = False
    app._topmost_applied = True
    app.root.attributes('-topmost', True)


_install_paste_stubs()
res = app.paste('hello', force=True)
check('E1 paste() 返回 True', res is True)
check('E2 让位：_topmost_applied 被同步为 False（否则后续 sync 会漏写）',
      app._topmost_applied is False)
check('E3 让位：实际 -topmost 变 False', topmost() is False)

# 关键：粘贴完成时若正在全屏，_restore_topmost 不得无脑恢复置顶
app._fg_fullscreen = True
app._user_pulled = False
app._topmost_applied = False
app.root.attributes('-topmost', False)
app._restore_topmost()
check('E4 全屏中粘贴完成 → 仍被抑制，不恢复置顶',
      topmost() is False and app._topmost_applied is False)
# 非全屏中恢复
app._fg_fullscreen = False
app._restore_topmost()
check('E5 非全屏粘贴完成 → 恢复置顶', topmost() is True)

# 不重叠：不影响置顶
_install_paste_stubs()
app._panel_overlaps = lambda h: False
app.paste('hi', force=True)
check('E6 面板不覆盖目标 → 置顶保持不变（True）',
      topmost() is True and app._topmost_applied is True)

# 图片粘贴让位（第二条让位点 app_interact:379-381）
_install_paste_stubs()
AI.png_to_dib = lambda png: (b'\x00', 8, 8)
AI.write_clipboard_dib = lambda dib: True
AI.os = types.SimpleNamespace(path=types.SimpleNamespace(
    join=os.path.join, exists=lambda p: True))
AI.io = types.SimpleNamespace(open=lambda *a, **k: types.SimpleNamespace(read=lambda: b'x'))
img_item = {'id': 'img-1', 'image_path': '_qa8_probe.png',
            'last_used_at': 0, 'use_count': 0}
res_img = app.paste_image(img_item, force=True)
check('E7 paste_image() 让位：_topmost_applied=False & -topmost=False',
      res_img is True and app._topmost_applied is False and topmost() is False)

# E8（539cc9d 已修复）：让位进行中，poll_bg 的 sync_topmost 不得把它改回置顶
_install_paste_stubs()
app.paste('yield-text', force=True)
check('E8 让位开始 → _topmost_yield=True 且 不置顶',
      app._topmost_yield is True and topmost() is False)
_w_at = len(_writes)                           # 让位已落地后的写入计数
for _ in range(5):                             # 模拟 poll_bg 120ms 轮询 ×5
    app.sync_topmost()
check('E8b 让位进行中：连续 5 次 poll_bg 的 sync_topmost 均不得改回置顶',
      topmost() is False and app._topmost_applied is False)
check('E8c 让位期间去重：5 次 sync 未产生任何 -topmost 写入',
      len(_writes) == _w_at, 'delta=%d' % (len(_writes) - _w_at))
# 让位结束：_restore_topmost 清除标志并按状态机决定
app._restore_topmost()
check('E9 让位结束（非全屏）→ 清除 _topmost_yield 并恢复置顶',
      app._topmost_yield is False and topmost() is True)
check('E9b 让位结束 → 恰好写一次 -topmost（去重正确）',
      len(_writes) - _w_at == 1, 'delta=%d' % (len(_writes) - _w_at))

# 让位结束但正在全屏 → 仍不恢复
_install_paste_stubs()
app.paste('yield-fs', force=True)
app._fg_fullscreen = True
app._user_pulled = False
app._restore_topmost()
check('E10 让位结束 + 前台全屏 → 不恢复置顶（抑制保留）',
      app._topmost_yield is False and topmost() is False)

# 让位进行中面板已被隐藏 → 仍清除标志且不抛
_install_paste_stubs()
app.paste('yield-hidden', force=True)
app.hidden = True
app.root.withdraw()
app._restore_topmost()
check('E11 让位中面板已隐藏 → 清除 _topmost_yield 且不抛（不置顶）',
      app._topmost_yield is False and topmost() is False)

# ============================================================
# 收尾：还原 stub + 销毁 GUI
# ============================================================
try:
    app.hw.unreg_hotkey()
    app.hw.tray_del()
    app.hw.stop()
except Exception:
    pass
try:
    root.destroy()
except Exception:
    pass

# ============================================================
# F. 回归 + 数据不污染
# ============================================================
section('F. 回归 + 数据不污染')
PY = sys.executable
SUITES = [
    ('tests/test_core.py', ()),
    ('tests/test_refactor.py', ()),
    ('tests/_t38.py', ()),
    ('tests/_t39.py', ()),
    ('tests/_t40.py', ()),
    ('tests/_t41.py', ()),
]
for rel, extra in SUITES:
    try:
        p = subprocess.run([PY, rel] + list(extra), cwd=ROOT,
                           capture_output=True, text=True, timeout=180)
        out = (p.stdout or '') + (p.stderr or '')
        bad = (p.returncode != 0 or 'FAIL' in out.upper()
               or '有失败项' in out or 'Traceback' in out)
        check('F %s 通过' % rel, not bad,
              'rc=%d tail=%r' % (p.returncode, out.strip().splitlines()[-1:]))
    except Exception as e:
        check('F %s 通过' % rel, False, 'exc=%r' % e)

check('F 真实数据 sha256 未变', HASH0 == file_hash(REAL_DATA),
      'before=%s after=%s' % (HASH0, file_hash(REAL_DATA)))
# _t41（工程师本提交已更新）自测项数应与主理人所述一致
try:
    _t41out = open(os.path.join(ROOT, 'tests', '_t41.out'), encoding='utf-8').read()
    _n41 = _t41out.count('OK  ')
    check('F _t41 自测项数 == 52', _n41 == 52, 'got=%d' % _n41)
except Exception as e:
    check('F _t41 自测项数 == 52', False, 'exc=%r' % e)
check('F 真实目录无新增 .bak / 旁车文件', sidecars() == FILES0,
      'before=%r after=%r' % (FILES0, sidecars()))
check('F 临时数据文件未被写入（NO_SAVE 生效）', not os.path.exists(TMP_DATA))

try:
    import shutil
    shutil.rmtree(TMP_DIR, ignore_errors=True)
except Exception:
    pass

out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_qa8_fullscreen.out')
with open(out_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(LOG) + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))
print('\n'.join(LOG), flush=True)
print('全部通过' if OK else '有失败项', flush=True)
os._exit(0)
