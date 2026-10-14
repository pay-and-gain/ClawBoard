# -*- coding: utf-8 -*-
"""QA 独立验证：ClawBoard 多屏适配修复（commit 507d691 + d826819）。

作者：严过关（QA）。与工程师自测 _t43.py **独立**：换 harness、换用例组织、换断言角度，
并额外覆盖 _t43 未覆盖的边界（修复前卡死的**实证复现**、visible_ratio 全仓库调用点审计、
跨四屏 / 重叠显示器 / 空显示器 / 宽高为 0 或负、CopyToast 行为微调的遮挡量化评估、
张 80x40 可见时标题栏可抓性、单屏全链路不丢窗……）。

本机是**真实双屏**：主屏 (0,0,2560,1440)，副屏 (2560,157,5120,1757)（副屏在主屏右侧、
顶边低 157px）。因此 A/B/D 三组直接跑**真机真枚举**（不 mock monitors），是最强证据；
需要确定性或无法物理构造的情形（跨四屏、单屏、重叠屏）再显式喂坐标。

设计要点：
- A 组把 `git show 21b3d67:clawboard/app_geometry.py`（修复前）加载成**独立模块**，
  用与产品同序的拖动序列（平移 → clamp）跑真机显示器，复现 2210 / 2560 卡死；
  再在当前修复版上跑同一序列，应能连续跨屏。这证明是**代码修好了**，不是测试被改绿。
- clamp/edge 这类几何逻辑读的是 root.winfo_x/y/width/height，必须真开 Tk 窗口、真做
  geometry 往返才能复现"拖动后被改回去"的现场；显示器集合尽量用真枚举。
- 数据安全：import 业务模块前把 app_services.DATA_FILE / CRASH_LOG / BASE_DIR 与
  timefmt.DATA_FILE 全部指向 %TEMP% 临时目录，且 runtime.NO_SAVE=True。
- 绝不修改产品源码；不使用 os._exit（避免丢 stdout）。
"""
import ast
import ctypes
import glob
import hashlib
import importlib.util
import inspect
import os
import subprocess
import sys
import tempfile
import textwrap

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # 与产品一致的 per-monitor DPI 感知
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ---- 重定向落盘目标（必须在 import 业务模块之前）----
TMP_DIR = tempfile.mkdtemp(prefix='cb_qa10_')
TMP_DATA = os.path.join(TMP_DIR, 'ClawBoard数据.json')

import clawboard.app_services as S            # noqa: E402
S.DATA_FILE = TMP_DATA
S.CRASH_LOG = os.path.join(TMP_DIR, 'crash.log')
S.BASE_DIR = TMP_DIR

import clawboard.timefmt as TF                # noqa: E402
TF.DATA_FILE = TMP_DATA

from clawboard import runtime as RT           # noqa: E402
RT.NO_SAVE = True

import clawboard.app_geometry as G            # noqa: E402
import clawboard.win32 as W                    # noqa: E402
import clawboard.widgets as WG                 # noqa: E402
from clawboard.config import (AppState, MIN_W, MIN_H, BAR_H,  # noqa: E402
                              scaled, UI_SCALE_LEVELS)
import clawboard.config as C                    # noqa: E402

OK = True
LOG = []
_LOGF = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          '_qa10_multiscreen.out'), 'w', encoding='utf-8')


def _emit(line):
    LOG.append(line)
    try:
        _LOGF.write(line + '\n')
        _LOGF.flush()
    except Exception:
        pass
    print(line, flush=True)


def check(name, cond, extra=''):
    global OK
    if not cond:
        OK = False
    _emit('%s  %s%s' % ('OK  ' if cond else 'FAIL', name,
                        ('  ' + extra) if extra else ''))


def section(t):
    _emit('')
    _emit('== %s ==' % t)


REAL_DATA = os.path.join(ROOT, 'ClawBoard数据.json')
EXPECT_HASH = '5c21d32f5c8a5173646c7b0927a0a2149d6f2db5b6b35758f5e12c8150314079'


def file_hash(p):
    try:
        with open(p, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return None


def sidecars():
    return sorted(os.path.basename(p) for p in glob.glob(REAL_DATA + '*'))


HASH_BEFORE = file_hash(REAL_DATA)
FILES_BEFORE = sidecars()

# ============================================================
# 显示器矩形常量（真机值）
# ============================================================
PRIMARY = (0, 0, 2560, 1440)
SECOND = (2560, 157, 5120, 1757)
REAL = [PRIMARY, SECOND]
SINGLE = [(0, 0, 2560, 1440)]

# ============================================================
# 加载「修复前」模块：git show 21b3d67:clawboard/app_geometry.py
# ============================================================
PREFIX_PATH = os.path.join(TMP_DIR, 'app_geometry_prefix.py')
_prefix_src = None
try:
    _prefix_src = subprocess.check_output(
        ['git', 'show', '21b3d67:clawboard/app_geometry.py'],
        cwd=ROOT).decode('utf-8')
    with open(PREFIX_PATH, 'w', encoding='utf-8') as f:
        f.write(_prefix_src)
except Exception as e:                                    # pragma: no cover
    _emit('WARN  无法取到修复前 app_geometry：%s' % e)

GP = None
if _prefix_src:
    _spec = importlib.util.spec_from_file_location('app_geometry_prefix', PREFIX_PATH)
    GP = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(GP)

# ============================================================
# 真机显示器枚举自检
# ============================================================
section('0. 环境自检：真机显示器枚举')
_real = W.monitors()
check('真机枚举到 2 台显示器', len(_real) == 2, 'real=%s' % (_real,))
check('主屏 = (0,0,2560,1440)', PRIMARY in _real, 'real=%s' % (_real,))
check('副屏 = (2560,157,5120,1757)（顶边低 157）', SECOND in _real,
      'real=%s' % (_real,))

# ============================================================
# harness：只借 GeometryMixin 的几何方法，其余依赖打成桩
# ============================================================
class Harness(G.GeometryMixin):
    def __init__(self, root):
        state = AppState()
        for f in state.__dataclass_fields__:
            setattr(self, f, getattr(state, f))
        self.root = root
        self.st = {'edge_hide': False, 'edge_delay': 3}
        self._edge_mon = None
        self.tips = []

    def render(self):
        pass

    def tip(self, m):
        self.tips.append(m)

    def sync_topmost(self):
        pass

    def save(self, *a, **k):
        pass

    def quit_app(self):
        pass

    def min_size(self):
        return MIN_W, MIN_H

    def close_preview(self):
        pass


class HarnessPre(GP.GeometryMixin if GP else object):
    """修复前 harness：结构同 Harness，但不依赖 AppState（老模块没有 _edge_mon）。"""
    def __init__(self, root):
        state = AppState()
        for f in state.__dataclass_fields__:
            setattr(self, f, getattr(state, f))
        self.root = root
        self.st = {'edge_hide': False, 'edge_delay': 3}
        self.tips = []

    def render(self):
        pass

    def tip(self, m):
        self.tips.append(m)

    def sync_topmost(self):
        pass

    def save(self, *a, **k):
        pass

    def quit_app(self):
        pass

    def min_size(self):
        return MIN_W, MIN_H

    def close_preview(self):
        pass


import tkinter as tk          # noqa: E402
root = tk.Tk()
root.overrideredirect(True)
root.geometry('350x480+100+300')
root.update()
app = Harness(root)
pw, ph = 350, 480          # 与用户报告一致的窗口尺寸


def win_pos():
    root.update()
    return root.winfo_x(), root.winfo_y()


def place(x, y, w=pw, h=ph):
    root.geometry('%dx%d+%d+%d' % (w, h, x, y))
    root.update()


def drag(owner, step_x, n, w=pw, h=ph):
    """与产品 do_move 同序：先平移当前窗口并让位置落地，再调 clamp_to_screen。"""
    xs = [root.winfo_x()]
    for _ in range(n):
        root.geometry('+%d+%d' % (root.winfo_x() + step_x, root.winfo_y()))
        root.update()
        owner.clamp_to_screen()
        root.update()
        xs.append(root.winfo_x())
    return xs


# ============================================================
# A. 独立复现「修复前的卡死」 —— 证明不是改了测试让它变绿
# ============================================================
section('A. 修复前必失败 / 修复后必通过的拖动序列（真机显示器）')

if GP is None:
    check('修复前模块可加载', False, 'git show 失败')
else:
    # A-1 修复前：主屏 → 副屏，应卡在 2210（=2560-350）
    app_pre = HarnessPre(root)
    place(100, 300)
    xs_pre = drag(app_pre, +50, 70)
    check('A1 修复前 主屏→副屏 卡死在 x=2210（=2560-350）',
          max(xs_pre) == 2210,
          'max=%d 轨迹头=%s 尾=%s' % (max(xs_pre), xs_pre[:3], xs_pre[-3:]))
    check('A1b 修复前 永远跨不过主屏右边界（max 不 > 2210）',
          xs_pre[-1] <= 2210)

    # A-2 修复前：副屏 → 主屏，应卡在 2560（副屏左边界）
    place(4000, 300)
    xs_pre2 = drag(app_pre, -50, 70)
    check('A2 修复前 副屏→主屏 卡死在 x=2560（副屏左边界）',
          min(xs_pre2) == 2560,
          'min=%d 轨迹头=%s 尾=%s' % (min(xs_pre2), xs_pre2[:3], xs_pre2[-3:]))

    # A-3 当前修复版：同一序列必须能连续跨过去
    place(100, 300)
    xs_cur = drag(app, +50, 70)
    check('A3 修复后 主屏→副屏 越过 2560 且无回跳',
          xs_cur == sorted(xs_cur) and xs_cur[-1] >= 2600,
          '终点 x=%d（旧实现卡 2210）' % xs_cur[-1])

    place(4000, 300)
    xs_cur2 = drag(app, -50, 70)
    check('A4 修复后 副屏→主屏 越过 2560 且无回跳',
          xs_cur2 == sorted(xs_cur2, reverse=True) and xs_cur2[-1] <= 2500,
          '终点 x=%d（旧实现卡 2560）' % xs_cur2[-1])

    # A-5 直接对照：同一起点、同样 1 步 +50，修复前被弹回、修复后保持
    place(2250, 300)
    x_before_pre, _ = win_pos()
    app_pre.clamp_to_screen()
    root.update()
    pre_after = root.winfo_x()
    place(2250, 300)
    app.clamp_to_screen()
    root.update()
    cur_after = root.winfo_x()
    check('A5 单步对照：x=2250 修复前弹回 2210、修复后保持 2250',
          pre_after == 2210 and cur_after == 2250,
          'pre=%d cur=%d' % (pre_after, cur_after))

# ============================================================
# B. 真机双向拖动
# ============================================================
section('B. 真机双向拖动（连续 / 单调 / 无弹回 / 停得住）')

place(100, 300)
b1 = drag(app, +50, 60)
check('B1 主屏→副屏 单调不回跳', b1 == sorted(b1), '尾=%s' % b1[-4:])
check('B2 主屏→副屏 终点在副屏', b1[-1] >= SECOND[0], 'x=%d' % b1[-1])
check('B3 主屏→副屏 全程无「打回主屏内部」(min 未出现 <0 或骤降)',
      all(b >= 0 for b in b1) and b1[-1] >= 2900)

place(4000, 300)
b2 = drag(app, -50, 60)
check('B4 副屏→主屏 单调不回跳', b2 == sorted(b2, reverse=True), '尾=%s' % b2[-4:])
check('B5 副屏→主屏 终点在主屏', b2[-1] < SECOND[0], 'x=%d' % b2[-1])

# 能停在副屏任意位置：抽 5 个位置，clamp 后必须原样不动
stopped = True
for tx in (2600, 3000, 3600, 4200, 4700):
    place(tx, 500)
    before = win_pos()
    app.clamp_to_screen()
    if win_pos() != before:
        stopped = False
        _emit('     停不住：x=%d -> %s' % (tx, win_pos()))
check('B6 副屏任意位置都能停住（clamp 一笔不动）', stopped)

# 跨在两屏中间（2500~2910 骑在 2560 上）：停得住，ensure_onscreen 也不拉回
place(2500, 300)
before = win_pos()
app.clamp_to_screen()
c_ok = win_pos() == before
ret = app.ensure_onscreen()
root.update()
check('B7 跨屏正中 · clamp 不动 且 ensure_onscreen 不拉回',
      c_ok and ret is False and win_pos() == before,
      'clamp_ok=%s ret=%r pos=%s' % (c_ok, ret, win_pos()))

# 拖到 x=6000（完全出屏）→ 才回推，且回推到最近屏（副屏）
place(6000, 400)
app.clamp_to_screen()
root.update()
bx, by = win_pos()
check('B8 x=6000 完全出屏 → 回推到最近的副屏（非固定主屏）',
      SECOND[0] <= bx and bx + pw <= SECOND[2],
      'x=%d（主屏右界=2560）' % bx)
check('B9 回推后窗口完整可见', app._enough_visible(bx, by, pw, ph))

# ensure_onscreen 对出屏窗口也拉到最近屏
place(6000, 400)
ret = app.ensure_onscreen()
root.update()
ex, ey = win_pos()
check('B10 ensure_onscreen 出屏 → 拉到最近副屏', ret is True and ex >= SECOND[0],
      'x=%d' % ex)

# ============================================================
# C. visible_ratio 语义改动的影响面
# ============================================================
section('C. visible_ratio：调用点审计 + 语义边界')


def set_monitors_current(mons):
    G.monitors = lambda: list(mons)
    W.monitors = lambda: list(mons)


# C-0 独立 AST 审计：clawboard/ 下 visible_ratio 的**调用点**是否只有 ensure_onscreen
# （用 AST 找 Call(Name='visible_ratio')，天然排除 docstring / 注释 / import / 自身 def）
call_sites = []
for dirpath, _dirs, files in os.walk(os.path.join(ROOT, 'clawboard')):
    for fn in files:
        if not fn.endswith('.py'):
            continue
        fp = os.path.join(dirpath, fn)
        with open(fp, encoding='utf-8') as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == 'visible_ratio'):
                call_sites.append('%s:%d' % (os.path.relpath(fp, ROOT), node.lineno))
check('C0 clawboard/ 下 visible_ratio 逻辑调用点唯一（仅 app_geometry.ensure_onscreen）',
      len(call_sites) == 1 and 'app_geometry.py' in call_sites[0],
      'call_sites=%s' % call_sites)

# ClawBoard.py 只是 re-export（AST：from clawboard.win32 import ... visible_ratio ...）
with open(os.path.join(ROOT, 'ClawBoard.py'), encoding='utf-8') as f:
    cb_tree = ast.parse(f.read())
reexport = False
for node in ast.walk(cb_tree):
    if isinstance(node, ast.ImportFrom):
        for a in node.names:
            if a.name == 'visible_ratio':
                reexport = True
check('C0b ClawBoard.py 的 visible_ratio 仅为 re-export（ImportFrom 符号）',
      reexport)

set_monitors_current(REAL)
# C-1 跨屏 = 1.0
check('C1 跨屏（骑 2560）→ 1.0',
      abs(W.visible_ratio(2300, 300, 350, 480) - 1.0) < 1e-9,
      'got=%.6f' % W.visible_ratio(2300, 300, 350, 480))
# C-2 屏内 = 1.0
check('C2 主屏内 → 1.0', abs(W.visible_ratio(100, 100, 350, 480) - 1.0) < 1e-9)
check('C2b 副屏内 → 1.0', abs(W.visible_ratio(3000, 400, 350, 480) - 1.0) < 1e-9)
# C-3 完全出屏 = 0
check('C3 完全出屏 → 0.0', W.visible_ratio(6000, 300, 350, 480) == 0.0)
check('C3b 上方完全出屏 → 0.0', W.visible_ratio(300, -900, 350, 480) == 0.0)
# C-4 w/h 为 0 或负不得除零崩溃
check('C4 w=0 → 0.0（不崩）', W.visible_ratio(100, 100, 0, 480) == 0.0)
check('C4b h=0 → 0.0（不崩）', W.visible_ratio(100, 100, 350, 0) == 0.0)
check('C4c w/h 负 → 0.0（不崩）', W.visible_ratio(100, 100, -350, -480) == 0.0)
# C-5 显示器列表为空
set_monitors_current([])
check('C5 无显示器 → 0.0（不崩）', W.visible_ratio(100, 100, 350, 480) == 0.0)
# C-6 两屏各一半 → 1.0
set_monitors_current([(0, 0, 1920, 1080), (1920, 0, 3840, 1080)])
check('C6 跨左右两屏各一半 → 1.0',
      abs(W.visible_ratio(1770, 300, 300, 480) - 1.0) < 1e-9,
      'got=%.6f' % W.visible_ratio(1770, 300, 300, 480))
# C-7 跨四屏（2x2）→ 四块各 1/4 → 1.0
set_monitors_current([(0, 0, 1000, 1000), (1000, 0, 2000, 1000),
                      (0, 1000, 1000, 2000), (1000, 1000, 2000, 2000)])
check('C7 跨四屏正中（各占 1/4）→ 1.0',
      abs(W.visible_ratio(500, 500, 1000, 1000) - 1.0) < 1e-9,
      'got=%.6f' % W.visible_ratio(500, 500, 1000, 1000))
# C-8 显示器矩形重叠 → clamp 到 1.0（防 >1）
set_monitors_current([(0, 0, 1000, 1000), (0, 0, 1000, 1000)])
check('C8 显示器矩形重叠 → 仍 clamp 到 1.0',
      W.visible_ratio(100, 100, 300, 300) == 1.0,
      'got=%.6f' % W.visible_ratio(100, 100, 300, 300))
# C-9 与修复前语义对比（旧 = 各屏 max）
set_monitors_current(REAL)


def _visible_ratio_old(x, y, w, h):
    best = 0.0
    for (l, t, r, b) in W.monitors():
        iw = min(x + w, r) - max(x, l)
        ih = min(y + h, b) - max(y, t)
        if iw > 0 and ih > 0:
            best = max(best, (iw * ih) / float(w * h))
    return best


check('C9 跨屏：旧语义 <0.999（必被 ensure_onscreen 误判拉回） vs 新语义 1.0',
      _visible_ratio_old(2300, 300, 350, 480) < 0.999 and
      abs(W.visible_ratio(2300, 300, 350, 480) - 1.0) < 1e-9,
      'old=%.4f new=%.4f（旧的 max 语义对 2560 处骑跨=0.743，非均匀 50/50 时才是 0.5；'
      '关键是恒 <0.999 → 被拉回）' %
      (_visible_ratio_old(2300, 300, 350, 480),
       W.visible_ratio(2300, 300, 350, 480)))
# 50/50 骑跨（窗口左半在主屏、右半在副屏）→ 旧 0.5
check('C9b 均匀 50/50 骑跨：旧=0.5、新=1.0',
      abs(_visible_ratio_old(2385, 300, 350, 480) - 0.5) < 1e-9 and
      abs(W.visible_ratio(2385, 300, 350, 480) - 1.0) < 1e-9,
      'old=%.4f new=%.4f' % (_visible_ratio_old(2385, 300, 350, 480),
                             W.visible_ratio(2385, 300, 350, 480)))
set_monitors_current(REAL)

# ============================================================
# D. edge_hide（靠边隐藏）在副屏的正确性
# ============================================================
section('D. edge_hide：副屏不被误判「贴右」、收起位置基于所在屏')


class _FakeU32:
    def __init__(self):
        self.x = self.y = 0

    def GetCursorPos(self, ref):
        ref._obj.x = self.x
        ref._obj.y = self.y
        return 1


fake = _FakeU32()
real_u32 = G.u32
G.u32 = fake
try:
    app.st['edge_hide'] = True
    app.hidden = False
    app.collapsed = False

    # D1 副屏内部（不在任何边）→ 绝不判贴边（旧实现因主屏宽 2560 恒判「贴右」）
    place(2700, 400)
    app._edge_tick = 0
    app._edge_hidden = False
    fake.x, fake.y = 100, 400
    app.edge_update()
    check('D1 副屏内部 → 不判贴边（旧实现误判贴右）',
          app._edge_tick == 0 and app._edge_hidden is False,
          'tick=%d hidden=%r' % (app._edge_tick, app._edge_hidden))

    # D2 副屏右边缘 → 收起位置基于副屏右界 5120（不是主屏 2554）
    place(SECOND[2] - pw, 400)
    app._edge_tick = 0
    app._edge_hidden = False
    fake.x, fake.y = 100, 400
    for _ in range(3):
        app.edge_update()
    root.update()
    check('D2 副屏右边缘 → 判贴右并收起',
          app._edge_hidden is True and app._edge_side == 'right')
    check('D3 收起位置 = 副屏右界 5120-6 = 5114（不是主屏 2554）',
          root.winfo_x() == SECOND[2] - 6, 'x=%d' % root.winfo_x())
    check('D4 收起时记录所在屏 = 副屏', app._edge_mon == SECOND,
          'mon=%s' % (app._edge_mon,))

    # 鼠标碰副屏右边缘 → 滑出、原位还原
    fake.x, fake.y = SECOND[2] - 2, 400
    app.edge_update()
    root.update()
    check('D5 碰副屏右边缘 → 滑出且原位还原',
          app._edge_hidden is False and root.winfo_x() == SECOND[2] - pw,
          'x=%d' % root.winfo_x())
    # 重新在副屏右边缘收起（先把鼠标移开，避免「鼠标在窗口上」阻止收起）
    app._edge_hidden = False
    place(SECOND[2] - pw, 400)
    app._edge_tick = 0
    fake.x, fake.y = 100, 400
    for _ in range(3):
        app.edge_update()
    root.update()
    hidden_now = app._edge_hidden
    # 收起后鼠标移到**主屏**右界(2558)：不得误触发副屏窗口滑出
    fake.x, fake.y = PRIMARY[2] - 2, 400
    app.edge_update()
    check('D6 收起后鼠标在主屏右界(2558) → 不误触发副屏滑出（仍保持收起）',
          hidden_now is True and app._edge_hidden is True)
    # 鼠标真正碰副屏右边缘(5118) 才滑出
    fake.x, fake.y = SECOND[2] - 2, 400
    app.edge_update()
    root.update()
    check('D6b 收起后鼠标碰到副屏右边缘 → 才滑出',
          app._edge_hidden is False and root.winfo_x() == SECOND[2] - pw,
          'x=%d' % root.winfo_x())

    # D7 主屏右边缘 → 收起位置 2554（回归一致）
    app._edge_hidden = False
    place(PRIMARY[2] - pw, 300)
    app._edge_tick = 0
    fake.x, fake.y = 100, 300
    for _ in range(3):
        app.edge_update()
    root.update()
    check('D7 主屏右边缘 → 收起位置 2560-6 = 2554（与修复前一致）',
          app._edge_hidden is True and root.winfo_x() == PRIMARY[2] - 6,
          'x=%d' % root.winfo_x())

    # D8 副屏左边缘（贴 2560）→ 收起位置 = 副屏左界 - (宽-6)
    app._edge_hidden = False
    place(SECOND[0] + 1, 400)
    app._edge_tick = 0
    fake.x, fake.y = 3000, 400
    for _ in range(3):
        app.edge_update()
    root.update()
    check('D8 副屏左边缘 → 收起位置 = 2560-(350-6)=2216，方向 left',
          app._edge_hidden is True and app._edge_side == 'left'
          and root.winfo_x() == SECOND[0] - (pw - 6),
          'side=%s x=%d' % (app._edge_side, root.winfo_x()))

    # D9 修复前对照：副屏窗口(2700) 旧实现会误判贴右并搬到主屏最右(2554)
    if GP is not None:
        app_pre = HarnessPre(root)
        real_u32_pre = GP.u32
        GP.u32 = fake
        try:
            app_pre.st['edge_hide'] = True
            app_pre.hidden = False
            app_pre.collapsed = False
            place(2700, 400)
            app_pre._edge_tick = 0
            fake.x, fake.y = 100, 400
            for _ in range(3):
                app_pre.edge_update()
            root.update()
            check('D9 修复前对照：副屏窗口被误判贴右并搬到 2554',
                  root.winfo_x() == PRIMARY[2] - 6,
                  'x=%d' % root.winfo_x())
        finally:
            GP.u32 = real_u32_pre
finally:
    G.u32 = real_u32
    app.st['edge_hide'] = False
    app._edge_hidden = False

# ============================================================
# E. 三个浮窗跟随面板所在屏 + CopyToast 行为微调评估
# ============================================================
section('E. 三浮窗跟随面板所在屏 + CopyToast 微调评估')

set_monitors_current(REAL)


def toast_old_pos(owner, Wd, Hd, GAP=12):
    """修复前 CopyToast._pos 的规则（先右下；面板正好占右下才让到左下）。"""
    try:
        x, y = owner.corner_pos(Wd, Hd)
    except Exception:
        return 12, 12
    try:
        if not owner.collapsed and not owner.hidden:
            r = owner.root
            if (abs(r.winfo_x() - x) < Wd + 20
                    and abs(r.winfo_y() - y) < Hd + 20):
                x = 12
    except Exception:
        pass
    return x, y


SIZES = {'CopyToast': (300, 84), 'ContentPreview': (460, 340),
         'ImagePreview': (460, 340)}

# E1 面板在副屏（左半）：三个浮窗都落副屏、y 基于副屏底边 1757
place(SECOND[0] + 100, 400)
ok_e1 = True
detail_e1 = []
for nm, (w, h) in SIZES.items():
    px, py = app.preview_corner(w, h)
    on_second = (SECOND[0] <= px and px + w <= SECOND[2] and
                 SECOND[1] <= py and py + h <= SECOND[3])
    y_from_second = py == SECOND[3] - h - 62
    ok_e1 = ok_e1 and on_second and y_from_second
    detail_e1.append('%s=(%d,%d)' % (nm, px, py))
check('E1 面板在副屏(左半) → 三浮窗均落副屏且 y 基于副屏底边 1757',
      ok_e1, ' '.join(detail_e1))

# E2 y 恰为 1757-340-62=1355（不是主屏 1440-340-62=1038）
px, py = app.preview_corner(460, 340)
check('E2 副屏 y 基于副屏底边（1355），不是主屏（1038）', py == 1355,
      'py=%d' % py)

# E3 面板在副屏右半 → 浮窗落副屏左下角
place(SECOND[0] + 2000, 400)
px, py = app.preview_corner(460, 340)
check('E3 面板在副屏(右半) → 浮窗落副屏左下角 (2560+12=2572)',
      px == SECOND[0] + 12 and py == SECOND[3] - 340 - 62, '(%d,%d)' % (px, py))

# E4 面板在主屏 → 浮窗回落主屏（不串屏）
place(100, 100)
ok_e4 = True
for nm, (w, h) in SIZES.items():
    px, py = app.preview_corner(w, h)
    if not (PRIMARY[0] <= px and px + w <= PRIMARY[2] and
            PRIMARY[1] <= py and py + h <= PRIMARY[3]):
        ok_e4 = False
        _emit('     串屏：%s=(%d,%d)' % (nm, px, py))
check('E4 面板在主屏 → 三浮窗均落主屏', ok_e4)

# E5 源码断言：三处 _pos 不得再调用 winfo_screen*（AST 级，避开注释/文档串）
ok_e5 = True
for _cls in (WG.CopyToast, WG.ContentPreview, WG.ImagePreview):
    src = inspect.getsource(_cls._pos)
    tree = ast.parse(textwrap.dedent(src))
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr.startswith('winfo_screen'):
            bad.append(node.attr)
    has_pc = 'preview_corner' in src
    if bad or not has_pc:
        ok_e5 = False
        _emit('     %s._pos bad=%s has_preview_corner=%s' % (_cls.__name__, bad, has_pc))
check('E5 三处 _pos 均不再调用 winfo_screen*（AST），且改用 preview_corner', ok_e5)

# ---- CopyToast 行为微调评估：新规则是否比旧规则更容易遮挡面板？----
# 遍历面板在屏内的各种位置，统计「toast 与面板矩形相交」的比例。
def rect_overlap(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ow = min(ax + aw, bx + bw) - max(ax, bx)
    oh = min(ay + ah, by + bh) - max(ay, by)
    return ow > 0 and oh > 0


TW, TH = 300, 84
old_bad = new_bad = total = 0
old_only_bad = []      # 旧不挡、新挡 的情形（微调退化）
for cx in range(0, PRIMARY[2] - pw + 1, 40):
    for cy in range(0, PRIMARY[3] - ph + 1, 40):
        place(cx, cy)
        panel_rect = (cx, cy, pw, ph)
        old_x, old_y = toast_old_pos(app, TW, TH)
        new_x, new_y = app.preview_corner(TW, TH)
        old_ov = rect_overlap((old_x, old_y, TW, TH), panel_rect)
        new_ov = rect_overlap((new_x, new_y, TW, TH), panel_rect)
        total += 1
        old_bad += 1 if old_ov else 0
        new_bad += 1 if new_ov else 0
        if (not old_ov) and new_ov:
            old_only_bad.append((cx, cy))
check('E6 微调评估：新规则遮挡面板的情形不多于旧规则',
      new_bad <= old_bad,
      '总样本=%d 旧遮挡=%d 新遮挡=%d 仅新遮挡=%d' %
      (total, old_bad, new_bad, len(old_only_bad)))
check('E7 微调评估：不存在「旧不挡、新挡」的退化情形',
      len(old_only_bad) == 0,
      '退化点=%s' % old_only_bad[:5])
# 默认面板位置（右下角）下的落点
place(PRIMARY[2] - pw - 14, PRIMARY[3] - ph - 62)
_dx, _dy = app.preview_corner(TW, TH)
check('E8 面板在默认右下角 → CopyToast 让到面板**另一侧**（x 明显偏左）',
      _dx < 500, 'toast=(%d,%d)' % (_dx, _dy))

# ============================================================
# F. 单屏环境不受影响
# ============================================================
section('F. 单屏回归（mock 单屏 monitors = [(0,0,2560,1440)]）')

set_monitors_current(SINGLE)
check('F1 单屏：屏内 → 放行', app._enough_visible(100, 100, pw, ph) is True)
check('F2 单屏：完全出屏 → 不放行', app._enough_visible(6000, 100, pw, ph) is False)

place(1500, 300)
before = win_pos()
app.clamp_to_screen()
check('F3 单屏：屏内拖动 → 不动', win_pos() == before, 'pos=%s' % (win_pos(),))

place(2204, 300)                     # 右侧只剩 2560-2204=356 ... 用 80 边界测
place(2461, 300)                     # 右侧只剩 99 宽（≥80）→ 放行
before = win_pos()
app.clamp_to_screen()
check('F4 单屏：右侧只剩 99 宽（≥80）→ 放行', win_pos() == before)

place(2490, 300)                     # 右侧只剩 70 宽（<80）→ 回推，仍在屏内
app.clamp_to_screen()
root.update()
fx, fy = win_pos()
check('F5 单屏：右侧只剩 70 宽（<80）→ 回推且仍在屏内',
      0 <= fx and fx + pw <= SINGLE[0][2], 'x=%d' % fx)

# 单屏：ensure_onscreen 对跨满窗口不误拉、对出屏拉回
place(100, 100)
ret = app.ensure_onscreen()
check('F6 单屏：屏内 → ensure_onscreen 不拉回', ret is False)
place(6000, 400)
ret = app.ensure_onscreen()
root.update()
check('F7 单屏：出屏 → ensure_onscreen 拉回主屏内',
      ret is True and 0 <= root.winfo_x() and root.winfo_x() + pw <= SINGLE[0][2],
      'x=%d' % root.winfo_x())

# 单屏：fit_geometry 哨兵回主屏右下角；可见足够保留；出屏拉回
x6, y6 = app.fit_geometry(340, 480, 10 ** 6, 10 ** 6)[2:4]
check('F8 单屏：哨兵 → 主屏右下角 (2560-340-14=2206)',
      x6 == 2560 - 340 - 14 and y6 == 1440 - 480 - 62, 'x=%d y=%d' % (x6, y6))
check('F9 单屏：可见足够 → 原样保留',
      app.fit_geometry(pw, ph, 500, 200) == (pw, ph, 500, 200))

# 单屏：preview_corner 落单屏内
place(100, 100)
px, py = app.preview_corner(460, 340)
check('F10 单屏：preview_corner 落单屏内',
      0 <= px and px + 460 <= 2560 and 0 <= py and py + 340 <= 1440,
      '(%d,%d)' % (px, py))

# 单屏：edge_* 用单屏边界
G.u32 = fake
try:
    app.st['edge_hide'] = True
    app._edge_hidden = False
    place(2560 - pw, 300)              # 贴单屏右边缘
    app._edge_tick = 0
    fake.x, fake.y = 100, 300
    for _ in range(3):
        app.edge_update()
    root.update()
    check('F11 单屏：贴右边缘 → 收起位置 2560-6=2554',
          app._edge_hidden is True and root.winfo_x() == 2560 - 6,
          'x=%d' % root.winfo_x())
    fake.x, fake.y = 2558, 300
    app.edge_update()
    root.update()
    check('F12 单屏：碰边 → 滑出还原', app._edge_hidden is False)
finally:
    G.u32 = real_u32
    app.st['edge_hide'] = False
    app._edge_hidden = False

set_monitors_current(REAL)

# ============================================================
# G. 窗口不会被「拖丢」+ reset_position 兜底
# ============================================================
section('G. 防拖丢：80x40 可见时标题栏可抓 + reset_position 兜底')

set_monitors_current(REAL)
bar_h = scaled(BAR_H)
check('G1 标题栏高度 scaled(BAR_H)=%d < 40 放行下限' % bar_h, bar_h <= 40)


def titlebar_visible(vis):
    """给定窗口位置，标题栏（窗口顶部 bar_h 高的整条）是否有可见部分。"""
    wx, wy = vis
    top = wy
    bottom = wy + bar_h
    return bottom > PRIMARY[1] and top < PRIMARY[3]


# G2 左移出屏：只留右侧 80 宽（垂直方向完整）→ 标题栏仍可抓
place(-(pw - 80), 300)
check('G2 只留右 80 宽 → _enough_visible True 且标题栏可抓',
      app._enough_visible(-(pw - 80), 300, pw, ph) is True
      and titlebar_visible((-(pw - 80), 300)),
      'titlebar 行 %d..%d 在屏内' % (300, 300 + bar_h))

# G2b 右移出屏：只留左侧 80 宽
place(PRIMARY[2] - 80, 300)
check('G2b 只留左 80 宽 → 放行且标题栏可抓',
      app._enough_visible(PRIMARY[2] - 80, 300, pw, ph) is True
      and titlebar_visible((PRIMARY[2] - 80, 300)))

# G3 下移出屏：只露**顶部 40px**（即标题栏所在行）→ 标题栏完整可见
place(600, PRIMARY[3] - 40)
check('G3 下边只露顶部 40px → 标题栏(y..y+%d) 完整可见' % bar_h,
      PRIMARY[3] - 40 + bar_h <= PRIMARY[3] and
      app._enough_visible(600, PRIMARY[3] - 40, pw, ph) is True,
      'title_span=%d..%d screen_bottom=%d' %
      (PRIMARY[3] - 40, PRIMARY[3] - 40 + bar_h, PRIMARY[3]))

# G4 上移出屏的可达极限：拖标题栏底部到屏幕顶 → window_y = -取点偏移(≤bar_h)。
#    （do_move 绑在标题栏上，光标被限制在屏幕内，故上移量 = 标题栏内取点偏移 ≤ bar_h）
class _Ev:
    def __init__(self, xr, yr):
        self.x_root, self.y_root = xr, yr


place(600, 300)
grab_x, grab_y = 620, 300 + bar_h          # 抓在标题栏最底一行
app._mx, app._my = grab_x, grab_y
app.do_move(_Ev(grab_x, 0))                 # 光标拖到屏幕顶
root.update()
lim_y = root.winfo_y()
check('G4 上移可达极限 window_y = -bar_h(%d)（拖标题栏到底行到屏顶）' % bar_h,
      lim_y == -bar_h, 'y=%d' % lim_y)
check('G4b 该极限下窗口主体 100%% 可见、_enough_visible True（不判为拖丢）',
      app._enough_visible(root.winfo_x(), lim_y, pw, ph) is True)
check('G4c 如实记录：该极限下标题栏正好贴屏顶(0px 可见)，需 reset 召回',
      lim_y + bar_h == PRIMARY[1])

# G5 真正的「只留 40px 高」出屏态（拖拽不可达，仅存档损坏才可能出现）也能 reset 召回
place(-(pw - 80), -(ph - 40))               # 窗口右下角 80x40 可见，标题栏在屏外
check('G5 极端出屏态（标题栏在屏外）→ _enough_visible 仍 True（新语义允许）',
      app._enough_visible(-(pw - 80), -(ph - 40), pw, ph) is True)

# G6 reset_position() 兜底：无论窗口在哪，重置回主屏右下角
for bad in ((6000, 400), (-900, -900), (2700, 400), (-(pw - 80), -(ph - 40))):
    place(*bad)
    app.reset_position()
    root.update()
    rx, ry = win_pos()
    on_primary = (PRIMARY[0] <= rx and rx + 340 <= PRIMARY[2] and
                  PRIMARY[1] <= ry and ry + 480 <= PRIMARY[3])
    check('G6 reset_position 从 %s → 回主屏右下角 (2206,898)' % (bad,),
          on_primary and rx == PRIMARY[2] - 340 - 14 and ry == PRIMARY[3] - 480 - 62,
          'pos=(%d,%d)' % (rx, ry))

# G7 reset_position(mon=副屏) 拉到指定屏
place(6000, 400)
app.reset_position(SECOND)
root.update()
rx, ry = win_pos()
check('G7 reset_position(mon=副屏) → 拉到副屏右下角',
      SECOND[0] <= rx and rx + 340 <= SECOND[2] and SECOND[1] <= ry,
      'pos=(%d,%d)' % (rx, ry))

# ============================================================
# H. 数据不污染
# ============================================================
section('H. 数据不污染')
check('H1 真实数据 sha256 未变且等于期望值',
      HASH_BEFORE == file_hash(REAL_DATA) == EXPECT_HASH,
      'before=%s after=%s' % (HASH_BEFORE, file_hash(REAL_DATA)))
check('H2 真实目录无新增 .bak', sidecars() == FILES_BEFORE,
      'before=%s after=%s' % (FILES_BEFORE, sidecars()))
check('H3 临时数据文件未被写入（NO_SAVE 生效）', not os.path.exists(TMP_DATA))

# ============================================================
# 收尾
# ============================================================
try:
    root.destroy()
except Exception:
    pass
try:
    import shutil
    shutil.rmtree(TMP_DIR, ignore_errors=True)
except Exception:
    pass

_emit('')
_emit('全部通过' if OK else '有失败项')
try:
    _LOGF.write('\n\n' + ('全部通过\n' if OK else '有失败项\n'))
    _LOGF.flush()
    _LOGF.close()
except Exception:
    pass
