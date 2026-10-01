# -*- coding: utf-8 -*-
"""v1.4.1 自测：面板被拖小时不再"看不见内容"
最小尺寸兜底 + 窄宽度下序号列/徽章给正文让位"""
import ctypes
import os
import tkinter as tk
import ClawBoard as C

# 和主程序一样先声明 DPI 感知，否则 tk scaling 拿不到真实的屏幕缩放
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

ok_all = True


def check(name, cond, extra=''):
    global ok_all
    if not cond:
        ok_all = False
    print('%s  %s%s' % ('OK  ' if cond else 'FAIL', name, ('  ' + extra) if extra else ''))


check('MIN_W/MIN_H 已定义且够用', C.MIN_W >= 280 and C.MIN_H >= 300,
      '%dx%d' % (C.MIN_W, C.MIN_H))

# ---------- 1. 最小尺寸真的能兜住（复现用户被拖成的 192x293） ----------
root = tk.Tk()
root.minsize(C.MIN_W, C.MIN_H)
root.geometry('192x293+80+80')
root.update()
w, h = root.winfo_width(), root.winfo_height()
check('设成 192x293 时被兜到最小尺寸', w >= C.MIN_W and h >= C.MIN_H, '实际 %dx%d' % (w, h))

root.geometry('340x480+80+80')
root.update()

# ---------- 1.5 DPI 换算：最小尺寸必须随缩放放大 ----------
k = C.dpi_scale(root)
check('dpi_scale 在合理区间', 0.5 <= k <= 4.0,
      'k=%.4f（tk scaling %s）' % (k, root.tk.call('tk', 'scaling')))
mw, mh = int(C.MIN_W * k), int(C.MIN_H * k)
check('最小尺寸随缩放只增不减', mw >= C.MIN_W and mh >= C.MIN_H,
      '%dx%d（100%% 时是 %dx%d）' % (mw, mh, C.MIN_W, C.MIN_H))

# ---------- 2. 列表按宽度自适应布局 ----------
vl = C.VirtualList(root, lambda i, e: None, lambda e, i: None, lambda i, x, y: None)
vl.pack(fill='both', expand=True)
root.update()
vl.set_data([{'id': str(i), 'text': 'hello world 第 %d 条' % i} for i in range(20)], None, '')
root.update()


def place_of(f, w):
    vl._layout(f, w)
    info_row = f._row.place_info()
    info_num = f._num.place_info()
    info_badge = f._badge.place_info()
    x0 = int(info_row['x'])
    row_w = w + int(info_row['width'])          # place 用 relwidth=1 + 负 width，故是加
    return x0, row_w, int(info_num['width']), int(info_badge['width'])


f = vl.pool[0]

# 宽：序号 + 完整徽章
x0, row_w, num, badge = place_of(f, 300)
check('宽 300：序号 16 徽章 80', (x0, num, badge) == (24, 16, 80),
      'x0=%d num=%d badge=%d' % (x0, num, badge))
check('宽 300：正文够宽', row_w >= 180, '正文 %dpx' % row_w)

# 中：徽章缩窄，序号保留
x0, row_w, num, badge = place_of(f, 200)
check('宽 200：徽章缩到 48', (x0, num, badge) == (24, 16, 48),
      'x0=%d num=%d badge=%d' % (x0, num, badge))

# 窄：序号与徽章全部让位（宽度压到 1px = 不可见）
x0, row_w, num, badge = place_of(f, 150)
check('宽 150：正文回到最左（x0=7）', x0 == 7, 'x0=%d' % x0)
check('窄卡片下序号/徽章宽度 <=1px', num <= 1 and badge <= 1,
      'num=%d badge=%d' % (num, badge))
check('宽 150：正文反而比 200 宽时更大', row_w >= 130, '正文 %dpx' % row_w)

# 复现用户那个致命尺寸：面板 192 宽 → 列表约 178 → 正文必须还能看
x0, row_w, num, badge = place_of(f, 178)
check('复现 192px 面板：正文不再只剩 66px', row_w >= 160,
      '正文 %dpx（旧布局是 178-112=66px）' % row_w)

# ---------- 3. 序号在窄卡片下不显示 ----------
vl.show_num = True
vl._layout(f, 150)
root.update()
vl._fill(f, 0)
root.update()
check('窄卡片下不显示序号', f._num.cget('text') == '',
      repr(f._num.cget('text')))
vl._layout(f, 300)
vl._fill(f, 0)
root.update()
check('宽卡片下显示序号', f._num.cget('text') == '1',
      repr(f._num.cget('text')))

# ---------- 4. 正文真的能画出来（宽度 > 0 且不被挤成负值） ----------
bad = []
for wid in (120, 150, 178, 200, 240, 300, 420):
    x0, row_w, num, badge = place_of(f, wid)
    if row_w < 60:
        bad.append((wid, row_w))
check('各宽度下正文宽度都 >= 60px', not bad, '异常 %s' % bad)

print('DONE')
try:
    root.destroy()
except Exception:
    pass
print('全部通过' if ok_all else '有失败项')
os._exit(0)
