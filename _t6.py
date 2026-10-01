# -*- coding: utf-8 -*-
"""滚轮功能自测：主列表 + 可滚动容器"""
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

print('ITEM_H=%d WHEEL_LINES=%d' % (C.ITEM_H, C.WHEEL_LINES))
print('初始位置 %.1f' % vl.canvas.canvasy(0))
print('池中 widget 数 %d' % len(vl.pool))


class E:
    def __init__(self, d):
        self.delta = d
        self.x_root = 0
        self.y_root = 0


# 1) 普通鼠标：一格 delta=-120 应该正好滚 3 行
vl._wheel(E(-120))
root.update()
y = vl.canvas.canvasy(0)
print('一格(-120) -> %.1f 期望 %.1f  %s' % (y, 3 * C.ITEM_H, 'OK' if abs(y - 3 * C.ITEM_H) < 0.5 else 'FAIL'))

# 2) 触控板：delta=-40 连滚 3 次也应有位移（老代码这里恒为 0）
y0 = vl.canvas.canvasy(0)
moved = []
for _ in range(3):
    vl._wheel(E(-40))
    root.update()
    moved.append(vl.canvas.canvasy(0))
print('触控板 -40 x3 -> %s %s' % ([round(v, 1) for v in moved],
                                  'OK' if moved[-1] > y0 else 'FAIL'))

# 3) 反向滚回顶部并夹住边界
for _ in range(50):
    vl._wheel(E(120))
root.update()
print('狂滚向上 -> %.1f %s' % (vl.canvas.canvasy(0),
                               'OK' if vl.canvas.canvasy(0) == 0 else 'FAIL'))
for _ in range(500):
    vl._wheel(E(-120))
root.update()
bottom = vl.canvas.canvasy(0)
total = len(items) * C.ITEM_H
h = vl.canvas.winfo_height()
print('狂滚向下 -> %.1f  (max=%.1f) %s' % (bottom, total - h, 'OK' if bottom <= total - h + 1 else 'FAIL'))

# 4) 条目子控件是否都接管了滚轮（否则鼠标停在条目上滚不动）
f = list(vl.pool.values())[0]
subs = [f, f._row, f._l1a, f._l1b, f._l1c, f._l2, f._badge]
bad = [str(w) for w in subs if not w.bind('<MouseWheel>')]
print('条目 7 个子控件滚轮绑定: %s' % ('全部 OK' if not bad else 'FAIL ' + str(bad)))

# 5) 鼠标悬停在条目上滚轮真的能滚（真实事件派发）
vl.view_top = None
vl.canvas.yview_moveto(0.0)
root.update()
f = list(vl.pool.values())[0]
before = vl.canvas.canvasy(0)
f._l1a.event_generate('<MouseWheel>', delta=-120, x=5, y=5)
root.update()
after = vl.canvas.canvasy(0)
print('在条目文字上滚一格: %.1f -> %.1f %s' % (before, after, 'OK' if after > before else 'FAIL'))

# 6) ScrollFrame（设置窗口用）
root2 = tk.Toplevel(root)
root2.geometry('380x300+400+50')
sc = C.ScrollFrame(root2)
sc.pack(fill='both', expand=True)
for i in range(20):
    tk.Label(sc.inner, text='选项 %d' % i, bg=C.T['bg'], fg=C.T['fg'], anchor='w').pack(fill='x', pady=3)
sc.bind_wheel_tree()
root2.update()
root2.update_idletasks()
sc._on_inner()
root2.update()
sr = sc.canvas.cget('scrollregion')
y0 = sc.canvas.canvasy(0)
sc.canvas.event_generate('<MouseWheel>', delta=-120, x=5, y=5)
root2.update()
print('ScrollFrame scrollregion=%s  滚一格 %.1f -> %.1f %s'
      % (sr, y0, sc.canvas.canvasy(0), 'OK' if sc.canvas.canvasy(0) > y0 else 'FAIL'))

root.destroy()
print('DONE')
