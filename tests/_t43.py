# -*- coding: utf-8 -*-
"""多屏（双屏）面板跨屏自由移动回归自测。

背景（真机双屏）：主屏 (0,0,2560,1440)，副屏 (2560,157,5120,1757)，副屏在主屏**右侧**、
顶边比主屏低 157px。旧实现把窗口死死钳在「当前所在显示器」内部，两个方向都跨不过去：
    clamp_to_screen 每次把窗口完整推进"相交面积最大"的显示器 → 一贴住边界就卡住；
    visible_ratio 取各屏交集比例的**最大值** → 跨屏时只有 0.5，被 ensure_onscreen 拉回主屏；
    edge_update/_edge_hide 用 winfo_screenwidth()（主屏宽）判边 → 副屏永远被判"贴右"、
                                         收起位置 nx=sw-6 把窗口搬到主屏最右。

覆盖：
A. _enough_visible 放行判据（跨屏 / 部分出屏 / 不足 80×40 的边界）
B. clamp_to_screen **拖动序列**：主屏→副屏、副屏→主屏 双向都能连续移动（不被弹回）—— 本用例
   在修复前必失败（卡在 x=2210 / x=2560）
C. clamp_to_screen：可见足够 → 一笔不动；不足 → 回推到**最近**屏（不固定主屏）
D. visible_ratio：跨屏 = 1.0 / 完全出屏 = 0 / 屏内 = 1.0
E. fit_geometry：可见足够保留原位置；完全出屏拉回最近屏；哨兵仍回主屏
F. ensure_onscreen：跨屏**不**拉回；完全出屏才拉回且拉到最近屏
G. edge_*：窗口在副屏不被判为"贴右"；收起位置基于**所在屏**（不是主屏右边界）
H. 单屏回归（mock 单屏 monitors）：行为合理、不会把窗口拖丢
I. 数据不污染：真实 ClawBoard数据.json sha256 前后一致、无新增 .bak

为什么真开 Tk 窗口 + 直接调产品的 GeometryMixin：几何逻辑读的是 root.winfo_x/y/width/height，
只有让 Tk 真正承载窗口、真正做 geometry 往返，才能复现"拖动后位置被改回去"的现场；
显示器集合用 mock（本机是双屏，但为保证断言确定、可移植，显式喂入坐标）。
"""
import ctypes
import glob
import hashlib
import inspect
import os
import sys
import tempfile

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # 与产品一致的 per-monitor DPI 感知
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ---- 重定向落盘目标（必须在 import 业务模块之前）----
TMP_DIR = tempfile.mkdtemp(prefix='cb_t43_')
TMP_DATA = os.path.join(TMP_DIR, 'ClawBoard数据.json')

import clawboard.app_services as S            # noqa: E402
S.DATA_FILE = TMP_DATA
S.CRASH_LOG = os.path.join(TMP_DIR, 'crash.log')

import clawboard.timefmt as TF                # noqa: E402
TF.DATA_FILE = TMP_DATA

from clawboard import runtime as RT           # noqa: E402
RT.NO_SAVE = True

import clawboard.app_geometry as G            # noqa: E402
import clawboard.win32 as W                    # noqa: E402
from clawboard.config import AppState, MIN_W, MIN_H   # noqa: E402
from clawboard.app_geometry import GeometryMixin       # noqa: E402

OK = True
LOG = []


def check(name, cond, extra=''):
    global OK
    if not cond:
        OK = False
    LOG.append('%s  %s%s' % ('OK  ' if cond else 'FAIL', name,
                             ('  ' + extra) if extra else ''))


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


HASH_BEFORE = file_hash(REAL_DATA)             # 期望 == 5c21d32f...4079
FILES_BEFORE = sidecars()

# ============================================================
# 显示器集合 mock（同时打到 app_geometry 与 win32 两个命名空间）
# ============================================================
PRIMARY = (0, 0, 2560, 1440)
SECOND = (2560, 157, 5120, 1757)
DUAL = [PRIMARY, SECOND]
SINGLE = [(0, 0, 1920, 1080)]


def set_monitors(mons):
    G.monitors = lambda: list(mons)
    W.monitors = lambda: list(mons)


set_monitors(DUAL)


# ============================================================
# 最小 harness：只借 GeometryMixin 的几何方法，其余依赖打成桩
# ============================================================
class Harness(GeometryMixin):
    def __init__(self, root):
        # 复制 AppState 全部字段（含 _edge_* ），保证与产品一致的"唯一初始化点"
        state = AppState()
        for f in state.__dataclass_fields__:
            setattr(self, f, getattr(state, f))
        self.root = root
        self.st = {'edge_hide': False, 'edge_delay': 3}
        self.rendered = 0
        self.tips = []

    def render(self):
        self.rendered += 1

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


def win_pos():
    root.update()
    return root.winfo_x(), root.winfo_y()


def place(x, y, w=350, h=480):
    root.geometry('%dx%d+%d+%d' % (w, h, x, y))
    root.update()


def drag(step_x, n):
    """模拟 do_move：先按 step 平移当前窗口，再调 clamp_to_screen（与产品代码同序）。

    关键：平移后先 root.update() 让位置落地再 clamp —— 真实事件循环里 do_move 读到的
    winfo_x() 是刚更新的新鲜值；不先 update 会读到旧值，把"拖动"退化成原地不动。
    """
    xs = [root.winfo_x()]
    for _ in range(n):
        root.geometry('+%d+%d' % (root.winfo_x() + step_x, root.winfo_y()))
        root.update()                       # 位置先落地（等价于事件循环派发）
        app.clamp_to_screen()
        root.update()
        xs.append(root.winfo_x())
    return xs


# ============================================================
# A. _enough_visible 放行判据
# ============================================================
section('A. _enough_visible（≥ min(80,w)×min(40,h) 就放行）')
check('屏内 → True', app._enough_visible(100, 100, 350, 480) is True)
check('跨屏（骑在 2560 边界上）→ True',
      app._enough_visible(2300, 300, 350, 480) is True)
check('副屏内 → True', app._enough_visible(3000, 400, 350, 480) is True)
check('右侧只剩 80 宽 → True（恰好够）',
      app._enough_visible(-270, 300, 350, 480) is True,
      '可见宽=80')
check('右侧只剩 79 宽 → False（不足）',
      app._enough_visible(-271, 300, 350, 480) is False,
      '可见宽=79')
check('完全出屏（右下角外）→ False',
      app._enough_visible(6000, 300, 350, 480) is False)
check('完全出屏（上方外）→ False',
      app._enough_visible(300, -900, 350, 480) is False)
check('窗口比阈值小：宽<80 时要求全宽可见',
      app._enough_visible(0, 0, 60, 30) is True and
      app._enough_visible(-20, 0, 60, 30) is False,
      '60 宽窗口左移 20 → 可见 40<60')

# ============================================================
# B. 拖动序列：双向连续跨屏（修复前必失败）
# ============================================================
section('B. 拖动序列 主屏→副屏 / 副屏→主屏（核心回归）')
place(100, 300)
xs = drag(+50, 70)
mono = all(b - a >= 0 for a, b in zip(xs, xs[1:]))       # 右移不应出现回跳
check('主屏→副屏：无回跳（每步 ≥0）', mono,
      '轨迹=%s' % xs[:3] + '...' + '%s' % xs[-3:])
check('主屏→副屏：能越过主屏右边界 2560', xs[-1] >= 2600,
      '终点 x=%d（旧实现卡在 2210）' % xs[-1])
check('主屏→副屏：终点落在副屏 (≥2560)', xs[-1] >= SECOND[0],
      '终点 x=%d' % xs[-1])
check('主屏→副屏：全程未被打回主屏内部', min(xs) >= 0 and xs[-1] > 2210)

place(4000, 300)
xs2 = drag(-50, 70)
mono2 = all(b - a <= 0 for a, b in zip(xs2, xs2[1:]))    # 左移不应出现回跳
check('副屏→主屏：无回跳（每步 ≤0）', mono2,
      '轨迹=%s' % xs2[:3] + '...' + '%s' % xs2[-3:])
check('副屏→主屏：能越过副屏左边界 2560', xs2[-1] <= 2500,
      '终点 x=%d（旧实现卡在 2560）' % xs2[-1])
check('副屏→主屏：终点落在主屏 (<2560)', xs2[-1] < SECOND[0],
      '终点 x=%d' % xs2[-1])

# ============================================================
# C. clamp_to_screen：足够则不动；不足回推最近屏
# ============================================================
section('C. clamp_to_screen 放行 / 回推最近屏')
place(2300, 300)                      # 跨屏，可见充足
before = win_pos()
app.clamp_to_screen()
check('跨屏合法状态：clamp 一笔不动', win_pos() == before,
      'before=%s after=%s' % (before, win_pos()))

place(-270, 300)                      # 只剩 80 宽，恰好够
before = win_pos()
app.clamp_to_screen()
check('部分出屏但仍够抓 → 不动', win_pos() == before,
      'pos=%s' % (win_pos(),))

place(-300, 300)                      # 只剩 50 宽 → 不足 → 回推
app.clamp_to_screen()
x3, y3 = win_pos()
check('不足 → 回推到最近屏（这里是主屏）', x3 >= 0 and PRIMARY[0] <= x3 <= PRIMARY[2],
      'x=%d' % x3)

# 窗口贴近副屏、完全出屏到右侧 → 回推目标应为副屏（最近），不是主屏
place(6000, 400)
app.clamp_to_screen()
x4, y4 = win_pos()
check('出屏在副屏右侧 → 回推到副屏（最近屏，而非主屏）',
      x4 >= SECOND[0], 'x=%d（主屏右边界=2560）' % x4)

# ============================================================
# D. visible_ratio
# ============================================================
section('D. visible_ratio（求和语义）')
set_monitors(DUAL)
check('跨屏 → 1.0', abs(W.visible_ratio(2300, 300, 350, 480) - 1.0) < 1e-9,
      'got=%.4f' % W.visible_ratio(2300, 300, 350, 480))
check('屏内 → 1.0', abs(W.visible_ratio(100, 100, 350, 480) - 1.0) < 1e-9,
      'got=%.4f' % W.visible_ratio(100, 100, 350, 480))
check('完全出屏 → 0', W.visible_ratio(6000, 300, 350, 480) == 0.0,
      'got=%.4f' % W.visible_ratio(6000, 300, 350, 480))
check('一半出屏 → 约 0.5（旧实现也是 0.5，但那是"误判"的根源）',
      abs(W.visible_ratio(-175, 300, 350, 480) - 0.5) < 1e-6,
      'got=%.4f' % W.visible_ratio(-175, 300, 350, 480))

# ============================================================
# E. fit_geometry
# ============================================================
section('E. fit_geometry（可见足够保留 / 出屏拉最近 / 哨兵回主屏）')
set_monitors(DUAL)
check('跨屏合法位置 → 原样保留',
      app.fit_geometry(350, 480, 2300, 300) == (350, 480, 2300, 300))
check('部分出屏但够抓 → 原样保留',
      app.fit_geometry(350, 480, -270, 300) == (350, 480, -270, 300))
fx, fy = app.fit_geometry(350, 480, 9000, 300)[2:4]
check('完全出屏（右）→ 拉回最近屏（副屏）', fx >= SECOND[0], 'x=%d' % fx)
sx, sy = app.fit_geometry(340, 480, 10 ** 6, 10 ** 6)[2:4]
check('哨兵（无存档）→ 主屏右下角 (2560-340-14=2206)',
      sx == PRIMARY[2] - 340 - 14 and sy == PRIMARY[3] - 480 - 62,
      'x=%d y=%d' % (sx, sy))

# ============================================================
# F. ensure_onscreen
# ============================================================
section('F. ensure_onscreen（跨屏不拉回 / 出屏才拉回且拉最近屏）')
set_monitors(DUAL)
place(2300, 300)                       # 跨屏
before = win_pos()
ret = app.ensure_onscreen()
check('跨屏 → 不拉回', ret is False and win_pos() == before,
      'ret=%r pos=%s' % (ret, win_pos()))

place(6000, 400)                       # 完全出屏
ret = app.ensure_onscreen()
nx, ny = win_pos()
check('完全出屏 → 拉回', ret is True)
check('拉回到最近屏（副屏）', nx >= SECOND[0], 'x=%d' % nx)
check('拉回后窗口完整可见', app._enough_visible(nx, ny, root.winfo_width(), root.winfo_height()))

# ============================================================
# G. edge_update / _edge_hide（用窗口所在屏）
# ============================================================
section('G. edge_* 使用窗口所在显示器')


class _FakeU32:
    def __init__(self):
        self.x = self.y = 0

    def GetCursorPos(self, ref):
        ref._obj.x = self.x
        ref._obj.y = self.y
        return 1


set_monitors(DUAL)
fake = _FakeU32()
real_u32 = G.u32
G.u32 = fake
try:
    app.st['edge_hide'] = True
    app.hidden = False
    app.collapsed = False

    # 副屏上但不在任何边缘 → 绝不能判成"贴右"（旧实现会因主屏宽 2560 误判）
    place(2700, 400)
    app._edge_tick = 0
    fake.x, fake.y = 100, 400           # 鼠标在很远处
    app.edge_update()
    check('副屏内部 → 不判贴边（旧实现会误判贴右）',
          app._edge_tick == 0 and app._edge_hidden is False,
          'tick=%d hidden=%r' % (app._edge_tick, app._edge_hidden))

    # 副屏右边缘 → 判贴右，收起位置基于副屏右边界（5120），不是主屏（2560）
    place(SECOND[2] - 350, 400)
    app._edge_tick = 0
    fake.x, fake.y = 100, 400
    for _ in range(3):
        app.edge_update()
    root.update()
    check('副屏右边缘 → 判贴右并收起', app._edge_hidden is True and app._edge_side == 'right')
    check('收起位置基于副屏右边界 (5120-6=5114)，不是主屏 (2554)',
          root.winfo_x() == SECOND[2] - 6, 'x=%d' % root.winfo_x())
    check('收起时记录了所在屏', app._edge_mon == SECOND, 'mon=%s' % (app._edge_mon,))

    # 鼠标碰副屏右边缘 → 滑出，原位还原
    fake.x, fake.y = SECOND[2] - 2, 400
    app.edge_update()
    root.update()
    check('碰副屏右边缘 → 滑出还原', app._edge_hidden is False and
          root.winfo_x() == SECOND[2] - 350, 'x=%d' % root.winfo_x())

    # 主屏右边缘也应正常判贴右（回归：别把主屏判错）
    place(PRIMARY[2] - 350, 300)
    app._edge_tick = 0
    fake.x, fake.y = 100, 300
    for _ in range(3):
        app.edge_update()
    root.update()
    check('主屏右边缘 → 收起位置 2560-6=2554',
          app._edge_hidden is True and root.winfo_x() == PRIMARY[2] - 6,
          'x=%d' % root.winfo_x())
finally:
    G.u32 = real_u32
    app.st['edge_hide'] = False
    app._edge_hidden = False

# _window_monitor 中心点归属
set_monitors(DUAL)
place(3000, 400)
check('_window_monitor 取窗口中心所在屏（副屏）', app._window_monitor() == SECOND)
place(100, 100)
check('_window_monitor 主屏', app._window_monitor() == PRIMARY)

# corner_pos 用所在屏
place(3000, 400)
cx, cy = app.corner_pos(210, 34)
check('corner_pos 用所在屏（副屏）右下角', cx >= SECOND[0], 'cx=%d' % cx)

# ============================================================
# H. 单屏回归
# ============================================================
section('H. 单屏回归（mock 单屏 monitors）')
set_monitors(SINGLE)
check('单屏：屏内 → 放行', app._enough_visible(100, 100, 350, 480) is True)
check('单屏：完全出屏 → 不放行', app._enough_visible(5000, 100, 350, 480) is False)

place(1500, 300)                        # 屏内
before = win_pos()
app.clamp_to_screen()
check('单屏：屏内拖动 → 不动', win_pos() == before, 'pos=%s' % (win_pos(),))

place(1830, 300)                        # 右侧只剩 90 宽 → 仍放行
before = win_pos()
app.clamp_to_screen()
check('单屏：只剩 90 宽（≥80）→ 放行', win_pos() == before, 'pos=%s' % (win_pos(),))

place(1860, 300)                        # 只剩 60 宽 → 回推
app.clamp_to_screen()
x5, _ = win_pos()
check('单屏：只剩 60 宽（<80）→ 回推，且仍在屏内',
      0 <= x5 <= (SINGLE[0][2] - 80), 'x=%d' % x5)

x6, y6 = app.fit_geometry(340, 480, 10 ** 6, 10 ** 6)[2:4]
check('单屏：哨兵 → 主屏右下角（1920-340-14=1566）',
      x6 == 1920 - 340 - 14 and y6 == 1080 - 480 - 62, 'x=%d y=%d' % (x6, y6))

# ============================================================
# I. 角落预览浮窗定位（跟随面板所在屏）
# ============================================================
section('I. 角落预览浮窗跟随面板所在屏（含副屏顶边偏移 + 不自算主屏）')
set_monitors(DUAL)
PW, PH = 460, 340
place(SECOND[0] + 100, 400)          # 面板中心在副屏**左半**
px, py = app.preview_corner(PW, PH)
check('面板在副屏(左半) → 预览落副屏右下角 (5120-460-12=4648)',
      px == SECOND[2] - PW - 12 and py == SECOND[3] - PH - 62,
      '(x=%d y=%d)' % (px, py))
check('预览完整落在副屏内', 
      SECOND[0] <= px and px + PW <= SECOND[2] and
      SECOND[1] <= py and py + PH <= SECOND[3],
      'rect=(%d..%d, %d..%d) sec=%s' % (px, px + PW, py, py + PH, SECOND))
check('y 按副屏底边 1757 算（=1355），不是主屏底边 1440（=1038）',
      py == 1355, 'py=%d' % py)

place(SECOND[0] + 2000, 400)         # 面板中心在副屏**右半**
px2, py2 = app.preview_corner(PW, PH)
check('面板在副屏(右半) → 预览落副屏左下角 (2560+12=2572)',
      px2 == SECOND[0] + 12 and py2 == SECOND[3] - PH - 62,
      '(x=%d y=%d)' % (px2, py2))

place(100, 100)                      # 面板在主屏 → 预览回主屏（不串屏）
px3, py3 = app.preview_corner(PW, PH)
check('面板在主屏 → 预览落主屏内',
      PRIMARY[0] <= px3 and px3 + PW <= PRIMARY[2] and
      PRIMARY[1] <= py3 and py3 + PH <= PRIMARY[3],
      '(x=%d y=%d)' % (px3, py3))

import clawboard.widgets as WG       # noqa: E402
for _cls in (WG.CopyToast, WG.ContentPreview, WG.ImagePreview):
    _src = inspect.getsource(_cls._pos)
    # 用 '.winfo_screen'（带点、即真正的方法调用）判定，避免误伤解释"为什么不用"的注释/文档串
    check('%s._pos 不再自算 winfo_screen*（改由 preview_corner 算）' % _cls.__name__,
          '.winfo_screen' not in _src and 'preview_corner' in _src)

# ============================================================
# J. 数据不污染
# ============================================================
section('J. 数据不污染')
check('真实数据 sha256 未变',
      HASH_BEFORE == file_hash(REAL_DATA) ==
      '5c21d32f5c8a5173646c7b0927a0a2149d6f2db5b6b35758f5e12c8150314079',
      'before=%s after=%s' % (HASH_BEFORE, file_hash(REAL_DATA)))
check('真实目录无新增 .bak', sidecars() == FILES_BEFORE,
      'before=%s after=%s' % (FILES_BEFORE, sidecars()))
check('临时数据文件未被写入（NO_SAVE 生效）', not os.path.exists(TMP_DATA))

# 收尾
try:
    root.destroy()
except Exception:
    pass
try:
    import shutil
    shutil.rmtree(TMP_DIR, ignore_errors=True)
except Exception:
    pass

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_t43.out')
with open(out, 'w', encoding='utf-8') as f:
    f.write('\n'.join(LOG) + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))
print('\n'.join(LOG), flush=True)
print('全部通过' if OK else '有失败项', flush=True)
os._exit(0)
