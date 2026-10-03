# -*- coding: utf-8 -*-
"""v1.5.2 自测：UI 等比缩放（50%/75%/100%/125%/150% 档位）

覆盖：scaled() 布局尺寸缩放、字体 tk scaling 缩放、窗口几何等比缩放、
min_size 缩放、dpi_scale 不被 UI 缩放污染（BASE_SCALING 固定）、
cycle_ui_scale 步进、折叠态切换、存档持久化。
"""
import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # 与真实 exe 同环境
except Exception:
    pass
import io
import os
import tempfile

import ClawBoard as C
from clawboard import config, runtime
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


root = tk.Tk()
app = C.ClawBoard(root)
if app.collapsed:
    app.collapsed = False
    app.body.pack(fill='both', expand=True)
    root.minsize(*app.min_size())
root.geometry('420x460+100+100')
root.update()

# ---------- 1. 默认 100% ----------
check('默认 UI_SCALE=1.0', config.UI_SCALE == 1.0, str(config.UI_SCALE))
check('默认 scaled(ITEM_H)=52', C.scaled(C.ITEM_H) == 52, str(C.scaled(C.ITEM_H)))
check('默认 scaled(TOOL_H)=48', C.scaled(C.TOOL_H) == 48, str(C.scaled(C.TOOL_H)))
check('BASE_SCALING 已记录（真实 DPI）', runtime.BASE_SCALING > 1.3,
      '%.3f' % runtime.BASE_SCALING)
base_scaling = runtime.BASE_SCALING
dpi0 = C.dpi_scale(root)

# ---------- 2. 缩放到 50% ----------
app.set_ui_scale(0.5)
root.update()
check('缩放后 config.UI_SCALE=0.5', config.UI_SCALE == 0.5, str(config.UI_SCALE))
check('缩放后 scaled(ITEM_H)=26', C.scaled(C.ITEM_H) == 26, str(C.scaled(C.ITEM_H)))
check('缩放后 scaled(TOOL_H)=24', C.scaled(C.TOOL_H) == 24, str(C.scaled(C.TOOL_H)))
check('缩放后 tk scaling = BASE*0.5',
      abs(float(root.tk.call('tk', 'scaling')) - base_scaling * 0.5) < 0.01,
      '%.3f vs %.3f' % (float(root.tk.call('tk', 'scaling')), base_scaling * 0.5))
check('★ 缩放后窗口宽度减半', root.winfo_width() == 210,
      '%d' % root.winfo_width())
check('★ 缩放后窗口高度减半', root.winfo_height() == 230,
      '%d' % root.winfo_height())
mw, mh = app.min_size()
check('min_size 也等比缩小', mw == int(C.MIN_W * dpi0 * 0.5),
      '%d vs %d' % (mw, int(C.MIN_W * dpi0 * 0.5)))
check('dpi_scale 不被 UI 缩放污染（BASE_SCALING 不变）',
      runtime.BASE_SCALING == base_scaling and abs(C.dpi_scale(root) - dpi0) < 0.01,
      '%.3f' % runtime.BASE_SCALING)
check('存档 st[ui_scale]=0.5', app.st.get('ui_scale') == 0.5, str(app.st.get('ui_scale')))

# ---------- 3. 档位循环 ----------
app.cycle_ui_scale(1)     # 0.5 -> 0.75
check('cycle +1 → 0.75', config.UI_SCALE == 0.75, str(config.UI_SCALE))
app.cycle_ui_scale(1)     # 0.75 -> 1.0
check('cycle +1 → 1.0', config.UI_SCALE == 1.0, str(config.UI_SCALE))
app.cycle_ui_scale(1)     # 1.0 -> 1.25
check('cycle +1 → 1.25', config.UI_SCALE == 1.25, str(config.UI_SCALE))
app.cycle_ui_scale(5)     # 到顶 1.5
check('cycle 越界钳制到 1.5', config.UI_SCALE == 1.5, str(config.UI_SCALE))
app.cycle_ui_scale(-5)    # 到底 0.5
check('cycle 越界钳制到 0.5', config.UI_SCALE == 0.5, str(config.UI_SCALE))

# ---------- 4. 恢复到 100% ----------
app.set_ui_scale(1.0)
root.update()
check('恢复 1.0 后窗口回到初始', root.winfo_width() == 420 and root.winfo_height() == 460,
      '%dx%d' % (root.winfo_width(), root.winfo_height()))

# ---------- 5. 折叠态下缩放不崩、不改变折叠态 ----------
app.toggle_collapse()
root.update()
check('已折叠', app.collapsed)
app.set_ui_scale(0.75)
root.update()
check('折叠态缩放后仍折叠', app.collapsed)
check('折叠态缩放后不崩（_restore 仍在）', bool(app._restore))
app.set_ui_scale(1.0)
app.toggle_collapse()
root.update()
check('恢复展开态', not app.collapsed)

# ---------- 6. 非法档位被拒绝 ----------
before = config.UI_SCALE
app.set_ui_scale(0.33)
check('非法档位 0.33 被拒绝', config.UI_SCALE == before, str(config.UI_SCALE))
app.set_ui_scale(2.0)
check('非法档位 2.0 被拒绝', config.UI_SCALE == before, str(config.UI_SCALE))

with io.open(os.path.join(tempfile.gettempdir(), '_t26.out'), 'w',
             encoding='utf-8') as f:
    f.write('\n'.join(LOG) + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))
os._exit(0)
