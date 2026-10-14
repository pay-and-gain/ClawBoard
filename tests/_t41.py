# -*- coding: utf-8 -*-
"""全屏程序前台时面板不再置顶（topmost 状态机）回归自测。

覆盖：
A. 全屏判定纯逻辑（rect_covers / is_fullscreen_window）：
   覆盖 / 不覆盖 / 1~2px 容差边界 / 缺边 / 更大窗口 / **多屏 + 不同分辨率**
   （必须用窗口**所在**显示器，拿主屏尺寸比副屏窗口会判错）。
B. 排除项：句柄 0 / 面板自己 / 桌面与 Shell（Progman / WorkerW / Shell_TrayWnd）→ 不算全屏。
C. 置顶状态机（GUI，stub 掉全屏检测，绝不真进全屏）：
   - 全屏 → -topmost 变 False；退出全屏 → 恢复 True
   - 用户 toggle_pin() 取消置顶后，进/出全屏**不得**把它改回 True
   - 全屏时呼出 → 置顶可见；隐藏后 → 又被抑制
D. 数据不污染：真实 ClawBoard数据.json sha256 前后一致、无新增 .bak。

数据安全：import 业务模块前把 app_services.DATA_FILE 与 timefmt.DATA_FILE **两个**都指向
临时目录，并置 runtime.NO_SAVE / C.NO_SAVE = True。测试里 **不真进全屏**（stub 掉
is_fullscreen_window），也不依赖真实前台窗口。
"""
import ctypes
import glob
import hashlib
import os
import sys
import tempfile

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # 与产品一致的 DPI 感知
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ---- 重定向落盘目标（必须在 import 业务模块之前）----
TMP_DIR = tempfile.mkdtemp(prefix='cb_t41_')
TMP_DATA = os.path.join(TMP_DIR, 'ClawBoard数据.json')

import clawboard.app_services as S            # noqa: E402
S.DATA_FILE = TMP_DATA
S.CRASH_LOG = os.path.join(TMP_DIR, 'crash.log')

import clawboard.timefmt as TF                # noqa: E402
TF.DATA_FILE = TMP_DATA

from clawboard import runtime as RT           # noqa: E402
RT.NO_SAVE = True

import clawboard.win32 as W                    # noqa: E402
from clawboard.win32 import (rect_covers, is_fullscreen_window,
                             monitor_rect_of, class_name_of)   # noqa: E402

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


HASH_BEFORE = file_hash(REAL_DATA)
FILES_BEFORE = sidecars()

# ============================================================
# A. rect_covers 纯逻辑
# ============================================================
section('A. rect_covers')
check('完全重合 → 覆盖', rect_covers((0, 0, 2560, 1440), (0, 0, 2560, 1440)) is True)
check('1px 内缩 → 覆盖（容差内）', rect_covers((1, 1, 2559, 1439), (0, 0, 2560, 1440)) is True)
check('2px 内缩 → 覆盖（容差边界）', rect_covers((2, 2, 2558, 1438), (0, 0, 2560, 1440)) is True)
check('3px 内缩 → 不覆盖（超容差）', rect_covers((3, 3, 2557, 1437), (0, 0, 2560, 1440)) is False)
check('高度不足（任务栏） → 不覆盖', rect_covers((0, 0, 2560, 1400), (0, 0, 2560, 1440)) is False)
check('偏出右侧 → 不覆盖', rect_covers((100, 0, 2660, 1440), (0, 0, 2560, 1440)) is False)
check('比显示器更大 → 覆盖', rect_covers((-10, -10, 2570, 1450), (0, 0, 2560, 1440)) is True)
check('监视器非零原点也能判（副屏）',
      rect_covers((2560, 157, 5120, 1757), (2560, 157, 5120, 1757)) is True)
check('None 输入 → False', rect_covers(None, (0, 0, 1, 1)) is False
      and rect_covers((0, 0, 1, 1), None) is False)

# ============================================================
# B. is_fullscreen_window（stub 掉 Win32 取数，纯逻辑）
# ============================================================
section('B. is_fullscreen_window（含多屏 / 排除项）')
_owr, _omr, _ocn = W.window_rect, W.monitor_rect_of, W.class_name_of


def sim(win_rect, mon_rect, cls='chrome_widgetwin_1'):
    """把 is_fullscreen_window 依赖的三个取数函数替换成固定值。"""
    W.window_rect = lambda h: win_rect
    W.monitor_rect_of = lambda h: mon_rect
    W.class_name_of = lambda h: cls
    return W.is_fullscreen_window(0x1234, 0)


# 主屏 2560x1440 物理
check('主屏全屏 → True', sim((0, 0, 2560, 1440), (0, 0, 2560, 1440)) is True)
check('主屏最大化（少任务栏）→ False', sim((0, 0, 2560, 1408), (0, 0, 2560, 1440)) is False)
# 4K 单屏
check('4K 全屏 → True', sim((0, 0, 3840, 2160), (0, 0, 3840, 2160)) is True)
# 多屏：窗口在第二台显示器上（原点非 0）
check('副屏全屏 → True（用窗口所在显示器判定）',
      sim((2560, 157, 5120, 1757), (2560, 157, 5120, 1757)) is True)
check('副屏窗口 用主屏尺寸比 → False（必须用所在显示器，否则误判）',
      sim((2560, 157, 5120, 1757), (0, 0, 2560, 1440)) is False)
# 不同分辨率的第二屏
check('不同分辨率副屏 全屏 → True',
      sim((2560, 0, 4464, 1080), (2560, 0, 4464, 1080)) is True)

# 排除项
check('句柄 0 → False', is_fullscreen_window(0) is False)
check('面板自己 → False', sim((0, 0, 2560, 1440), (0, 0, 2560, 1440)) is True
      and W.is_fullscreen_window(0x1234, 0x1234) is False)
for cls in ('progman', 'workerw', 'shell_traywnd', 'Progman', 'WorkerW'):
    check('桌面/Shell 类 %s → False' % cls,
          sim((0, 0, 2560, 1440), (0, 0, 2560, 1440), cls) is False)

# 还原
W.window_rect, W.monitor_rect_of, W.class_name_of = _owr, _omr, _ocn
check('真实 monitor_rect_of 可调用不抛', monitor_rect_of(0) is None)
check('真实 class_name_of 不抛', isinstance(class_name_of(0), str))

# ============================================================
# C. 置顶状态机（GUI，stub 全屏检测，不真进全屏）
# ============================================================
section('C. 置顶状态机')
import tkinter as tk          # noqa: E402
import ClawBoard as C         # noqa: E402

C.NO_SAVE = True

# stub 掉全屏检测：由 FS['on'] 控制（同时在 S 里 stub，避免 poll_bg 抢改状态）
FS = {'on': False}
S.is_fullscreen_window = lambda *a, **k: FS['on']
S.top_hwnd = lambda r: 1               # 面板顶层句柄；保证永不等于真实前台窗口

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


# 基线：无全屏 → 默认置顶
app._topmost_user = True
app._user_pulled = False
set_fs(False)
check('基线：无全屏 → 置顶', topmost() is True)

# 全屏 → 被覆盖（不再置顶）；退出 → 恢复
set_fs(True)
check('全屏（未呼出）→ 不再置顶', topmost() is False)
set_fs(False)
check('退出全屏 → 恢复置顶', topmost() is True)

# 用户取消置顶后，进/出全屏不得改回 True
app.toggle_pin()                       # 用户取消置顶
check('toggle_pin 取消置顶 → False', topmost() is False
      and app._topmost_user is False)
set_fs(True)
check('取消置顶 + 进全屏 → 仍 False', topmost() is False)
set_fs(False)
check('取消置顶 + 出全屏 → 仍 False（不被强行改回 True）',
      topmost() is False and app._topmost_user is False)
app.toggle_pin()                       # 恢复置顶意图
check('toggle_pin 恢复置顶 → True', topmost() is True and app._topmost_user is True)

# 全屏呼出场景：呼出 → 置顶可见；隐藏 → 又被抑制
app._fg_fullscreen = True
FS['on'] = True
app.root.withdraw()
app.hidden = True
app._user_pulled = False
app.sync_topmost()
check('全屏 + 隐藏 → 不置顶', topmost() is False)

app.toggle_show()                      # 用户按热键呼出
root.update()
check('全屏呼出 → 置顶可见', topmost() is True)
check('全屏呼出 → 面板未隐藏', app.hidden is False)

app.hide()                             # 呼出用完隐藏
check('呼出后隐藏 → 又被抑制（False）', topmost() is False)
check('隐藏后 _user_pulled 已清除', app._user_pulled is False)

# 用户意图在全屏进出中始终不变
app._topmost_user = True
app._user_pulled = False
entered = []
for on in (True, False, True, False):
    set_fs(on)
    entered.append((on, topmost()))
check('全屏循环中用户意图恒为 True', app._topmost_user is True)
check('全屏循环实际值：on→False / off→True',
      entered == [(True, False), (False, True), (True, False), (False, True)],
      'got=%r' % (entered,))

# 还原 stub + 销毁 GUI
S.is_fullscreen_window = getattr(S, 'is_fullscreen_window')
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
# D. 数据不污染
# ============================================================
section('D. 数据不污染')
check('真实数据 sha256 未变', HASH_BEFORE == file_hash(REAL_DATA),
      'before=%s after=%s' % (HASH_BEFORE, file_hash(REAL_DATA)))
check('真实目录无新增 .bak', sidecars() == FILES_BEFORE,
      'before=%s after=%s' % (FILES_BEFORE, sidecars()))
check('临时数据文件未被写入（NO_SAVE 生效）', not os.path.exists(TMP_DATA))

try:
    import shutil
    shutil.rmtree(TMP_DIR, ignore_errors=True)
except Exception:
    pass

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_t41.out')
with open(out, 'w', encoding='utf-8') as f:
    f.write('\n'.join(LOG) + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))
print('\n'.join(LOG), flush=True)
print('全部通过' if OK else '有失败项', flush=True)
os._exit(0)
