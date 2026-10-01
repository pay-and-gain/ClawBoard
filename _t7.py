# -*- coding: utf-8 -*-
"""右侧细滑动条自测：位置/宽度可见性 + 拖动 + 轨道点击 + 内容不满屏时不显示滑块"""
import os
import tkinter as tk
import ClawBoard as C

root = tk.Tk()
root.geometry('340x480+50+50')

items = [{'id': str(i), 'text': 'x' * 30, 'time': '2026-10-01 10:00'} for i in range(200)]
vl = C.VirtualList(root, lambda i, e: None, lambda e, i: None, lambda i, x, y: None)
vl.pack(fill='both', expand=True)
root.update()
vl.set_data(items, None, '')
root.update()

bar = vl.sb
print('滑动条类型 %s' % type(bar).__name__)
W = bar.winfo_width()
H = bar.winfo_height()
x = bar.winfo_x()
print('几何: x=%d 宽=%d 高=%d  列表宽=%d' % (x, W, H, vl.winfo_width()))
print('宽度可见(>=6px): %s' % ('OK' if W >= 6 else 'FAIL 被挤扁了'))
print('贴在右边: %s' % ('OK' if abs((x + W) - vl.winfo_width()) <= 1 else 'FAIL 没有靠右'))

# 1) 有内容可滚时滑块要画出来，且落在轨道内
n_items = len(bar.find_all())
y, th, hh = bar._geom()
print('可滚时图元 %d 个 th=%d y=%d 轨道=%d  %s'
      % (n_items, th, y, hh, 'OK' if n_items == 2 and 0 <= y and y + th <= hh else 'FAIL'))

# 2) 拖动滑块到底部：视图应滚到最底
total = len(items) * C.ITEM_H
view_h = vl.canvas.winfo_height()


class E:
    def __init__(self, y):
        self.y = y


bar._press(E(y + th // 2))
bar._move(E(hh - 1))
root.update()
cy = vl.canvas.canvasy(0)
print('拖到底 -> canvasy=%.1f 期望 %.1f  %s'
      % (cy, total - view_h, 'OK' if abs(cy - (total - view_h)) < 2 else 'FAIL'))
bar._release(E(hh - 1))

# 3) 点轨道上半部分：应向上跳
bar._press(E(2))
root.update()
bar._release(E(2))
print('点轨道上部 -> canvasy=%.1f  %s'
      % (vl.canvas.canvasy(0), 'OK' if vl.canvas.canvasy(0) < cy else 'FAIL'))

# 4) 滚动后滑块位置要跟着变（yscrollcommand 协议）
b0 = bar.get()[0]
vl.scroll_rows(10)
root.update()
b1 = bar.get()[0]
print('滚 10 行后滑块 first: %.4f -> %.4f  %s' % (b0, b1, 'OK' if b1 > b0 else 'FAIL'))

# 5) 滑块到顶时不能再向上（边界）
vl.scroll_rows(-999)
root.update()
print('滚到顶 -> canvasy=%.1f  first=%.4f  %s'
      % (vl.canvas.canvasy(0), bar.get()[0],
         'OK' if vl.canvas.canvasy(0) == 0 and abs(bar.get()[0]) < 1e-6 else 'FAIL'))

# 6) 内容不满一屏：只画轨道，不画滑块（避免误导）
vl.set_data(items[:3], None, '')
root.update()
n2 = len(bar.find_all())
y2, th2, h2 = bar._geom()
print('仅 3 条时图元 %d（应为 1=只有轨道）th=%d 轨道=%d  %s'
      % (n2, th2, h2, 'OK' if n2 == 1 and th2 >= h2 else 'FAIL'))

# 7) ScrollFrame（设置窗口）同款滑动条
top = tk.Toplevel(root)
top.geometry('380x240+400+50')
sc = C.ScrollFrame(top)
sc.pack(fill='both', expand=True)
for i in range(20):
    tk.Label(sc.inner, text='选项 %d' % i, bg=C.T['bg'], fg=C.T['fg'],
             anchor='w').pack(fill='x', pady=3)
sc.bind_wheel_tree()
root.update()
root.update_idletasks()
sc._on_inner()
root.update()
b2 = sc.sb
print('ScrollFrame 滑动条 宽=%d 高=%d 列表宽=%d 图元=%d'
      % (b2.winfo_width(), b2.winfo_height(), sc.winfo_width(), len(b2.find_all())))
yy, tt, hhh = b2._geom()
b2._press(E(yy + tt // 2))
b2._move(E(hhh - 1))
root.update()
print('  拖到底 canvasy=%.1f（应 > 0） %s'
      % (sc.canvas.canvasy(0), 'OK' if sc.canvas.canvasy(0) > 0 else 'FAIL'))

print('DONE')
try:
    root.destroy()
except Exception as e:
    print('destroy 异常: %r' % e)
print('EXIT')
os._exit(0)
