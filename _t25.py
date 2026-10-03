# -*- coding: utf-8 -*-
"""v1.5.1 自测：工具条扩大 + 窗口边缘随意拉伸

背景（用户截图反馈）：
- 125% DPI 下按钮 25px + pady 7*2 = 39px，TOOL_H=40 只剩 1px 余量，
  视觉上按钮紧贴工具条上下边缘、像被切掉；按钮间 padx=1 几乎无间距。
- do_resize 下限硬编码 240x160，与 min_size()（280x340*DPI）两套下限打架。
- 窗口只能从右下角 grip 拉伸，用户要求"随意拉伸"。

本测试覆盖：按钮区域扩大、边缘方向判定、四边四角拉伸、
拖左/上边窗口跟随移动、minsize 下限、折叠态禁用。
"""
import io
import os
import tempfile

import ClawBoard as C
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


def ev(x, y):
    """伪造屏幕坐标事件"""
    return type('E', (), {'x_root': x, 'y_root': y})()


root = tk.Tk()
app = C.ClawBoard(root)
if app.collapsed:
    app.collapsed = False
    app.body.pack(fill='both', expand=True)
    root.minsize(*app.min_size())
root.geometry('420x460+100+100')
root.update()

RX, RY = root.winfo_rootx(), root.winfo_rooty()   # 窗口客户区屏幕坐标

# ---------- 1. 按钮区域扩大 ----------
check('TOOL_H 扩到 48', C.TOOL_H == 48, str(C.TOOL_H))
check('工具条实际高度 = 48', app.tool.winfo_height() == C.TOOL_H,
      str(app.tool.winfo_height()))
btns = [(b.cget('text'), b.winfo_reqheight(), b.winfo_reqwidth())
        for _, b in app._tool_btns if b.winfo_ismapped()]
max_h = max(r for _, r, _ in btns)
check('按钮实高 %d，工具条 %d，余量 %dpx（不再贴边）' % (max_h, C.TOOL_H, C.TOOL_H - max_h),
      max_h + 18 <= C.TOOL_H, 'req=%d' % max_h)
padx = {b.pack_info()['padx'] for _, b in app._tool_btns}   # pack 的 padx，不是 Label 选项
check('按钮 pack padx=2（有间距）', padx == {2}, str(padx))

# ---------- 2. 边缘方向判定 ----------
L, T, W, H = RX, RY, root.winfo_width(), root.winfo_height()
check('左边缘 → w', app._resize_dir(ev(L + 2, T + H // 2)) == 'w',
      str(app._resize_dir(ev(L + 2, T + H // 2))))
check('右边缘 → e', app._resize_dir(ev(L + W - 2, T + H // 2)) == 'e',
      str(app._resize_dir(ev(L + W - 2, T + H // 2))))
check('上边缘 → n', app._resize_dir(ev(L + W // 2, T + 2)) == 'n',
      str(app._resize_dir(ev(L + W // 2, T + 2))))
check('下边缘 → s', app._resize_dir(ev(L + W // 2, T + H - 2)) == 's',
      str(app._resize_dir(ev(L + W // 2, T + H - 2))))
check('右下角 → se', app._resize_dir(ev(L + W - 2, T + H - 2)) == 'se',
      str(app._resize_dir(ev(L + W - 2, T + H - 2))))
check('左上角 → nw', app._resize_dir(ev(L + 2, T + 2)) == 'nw',
      str(app._resize_dir(ev(L + 2, T + 2))))
check('窗口中央 → None', app._resize_dir(ev(L + W // 2, T + H // 2)) is None,
      str(app._resize_dir(ev(L + W // 2, T + H // 2))))

# ---------- 3. 折叠态禁用 ----------
app.toggle_collapse()
root.update()
check('折叠态下边缘判定返回 None', app._resize_dir(ev(L + 2, T + 2)) is None,
      str(app._resize_dir(ev(L + 2, T + 2))))
app.toggle_collapse()
root.update()
check('恢复展开态', not app.collapsed)

# ---------- 4. 四边拉伸 + minsize 下限 ----------
mw, mh = app.min_size()
# 向右拉（东边）：宽度增加
app._rz_dir = 'e'
app._rz = (L + W, T + H // 2, W, H, root.winfo_x(), root.winfo_y())
app.on_zone_drag(ev(L + W + 60, T + H // 2))
root.update()
check('拖右边缘 → 宽度增加', root.winfo_width() == W + 60,
      '%d → %d' % (W, root.winfo_width()))
check('拖右边缘 → 高度不变', root.winfo_height() == H, str(root.winfo_height()))
check('拖右边缘 → 位置不变', (root.winfo_x(), root.winfo_y()) == (100, 100))

# 向左拉（西边）：宽度增加 + 窗口左移
w_before, x_before = root.winfo_width(), root.winfo_x()
app._rz_dir = 'w'
app._rz = (root.winfo_rootx(), T + H // 2, w_before, root.winfo_height(),
           x_before, root.winfo_y())
app.on_zone_drag(ev(root.winfo_rootx() - 50, T + H // 2))
root.update()
check('拖左边缘 → 宽度增加', root.winfo_width() == w_before + 50,
      '%d → %d' % (w_before, root.winfo_width()))
check('拖左边缘 → 窗口左移（右边缘不动）',
      root.winfo_x() == x_before - 50,
      '%d → %d' % (x_before, root.winfo_x()))

# 向上拉（北边）：高度增加 + 窗口上移，且不低于 minsize
h_before, y_before = root.winfo_height(), root.winfo_y()
app._rz_dir = 'n'
app._rz = (L + W // 2, root.winfo_rooty(), root.winfo_width(), h_before,
           root.winfo_x(), y_before)
app.on_zone_drag(ev(L + W // 2, root.winfo_rooty() + 10))   # 向下拖 10 → 高度-10
root.update()
check('拖上边缘（向下）→ 高度减少', root.winfo_height() == h_before - 10,
      '%d → %d' % (h_before, root.winfo_height()))
check('拖上边缘（向下）→ 窗口下移', root.winfo_y() == y_before + 10,
      '%d → %d' % (y_before, root.winfo_y()))
check('高度不低于 minsize', root.winfo_height() >= mh,
      '%d vs %d' % (root.winfo_height(), mh))

# 强行往小拉 → 被 minsize 挡住
app._rz_dir = 'se'
app._rz = (L + W, T + H, root.winfo_width(), root.winfo_height(),
           root.winfo_x(), root.winfo_y())
app.on_zone_drag(ev(L + 10, T + 10))          # 拉到非常小
root.update()
check('★ 强行拉小 → 被 minsize 挡住（do_resize 两套下限已统一）',
      root.winfo_width() >= mw and root.winfo_height() >= mh,
      '%dx%d vs min %dx%d' % (root.winfo_width(), root.winfo_height(), mw, mh))
app.on_zone_release(ev(L + 10, T + 10))
check('松开后 _rz_dir 清空', app._rz_dir is None, str(app._rz_dir))

# grip 的 do_resize 也不能拉破下限（旧硬编码 240x160 修复）
app._rx, app._ry = 5000, 5000
app._rw, app._rh = root.winfo_width(), root.winfo_height()
app.do_resize(ev(10, 10))                     # 往回拖很远
root.update()
check('★ grip do_resize 同样不低于 minsize',
      root.winfo_width() >= mw and root.winfo_height() >= mh,
      '%dx%d' % (root.winfo_width(), root.winfo_height()))

# 拉伸状态字段有唯一初始化点（R3 规矩）
check('AppState 含 _rz_dir/_hover_dir（不再分支隐式初始化）',
      hasattr(app, '_rz_dir') and hasattr(app, '_hover_dir'),
      '%s/%s' % (getattr(app, '_rz_dir', '<缺>'), getattr(app, '_hover_dir', '<缺>')))

with io.open(os.path.join(tempfile.gettempdir(), '_t25.out'), 'w',
             encoding='utf-8') as f:
    f.write('\n'.join(LOG) + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))
os._exit(0)
