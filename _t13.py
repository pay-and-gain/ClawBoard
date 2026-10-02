# -*- coding: utf-8 -*-
"""诊断：工具条按钮为什么被"遮住一些"——量请求宽度 vs 实际宽度、以及拖动手柄是否压在按钮上"""
import ctypes
import os
import tkinter as tk

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import ClawBoard as C

C.NO_SAVE = True
root = tk.Tk()
root.geometry('380x540+200+120')
app = C.ClawBoard(root)
root.update()

print('工具条 %dx%d' % (app.tool.winfo_width(), app.tool.winfo_height()))
print('搜索框 %dx%d' % (app.search_entry.winfo_width(), app.search_entry.winfo_height()))
print()
print('%-6s %-8s %-8s %-8s %s' % ('按钮', '需要宽', '实际宽', '实际高', '被裁剪？'))
for b in app.tool.winfo_children():
    if not isinstance(b, tk.Label) or b is app.search_ph:
        continue
    req = b.winfo_reqwidth()
    act = b.winfo_width()
    print('%-6s %-8d %-8d %-8d %s'
          % (b.cget('text'), req, act, b.winfo_height(),
             '*** 是（需要 %d > 实际 %d）***' % (req, act) if req > act else '否'))

print()
# 拖动手柄（右下角 ◢）会不会压住按钮？
gx, gy = app.grip.winfo_x(), app.grip.winfo_y()
gw, gh = app.grip.winfo_width(), app.grip.winfo_height()
# grip 是相对 root 的 place，换算成 root 坐标
print('拖动手柄: root 坐标 (%d,%d) %dx%d' % (gx, gy, gw, gh))
last = [b for b in app.tool.winfo_children()
        if isinstance(b, tk.Label) and b is not app.search_ph][-1]
# 按钮相对 root 的坐标
lx = app.tool.winfo_x() + last.winfo_x()
ly = app.tool.winfo_y() + last.winfo_y()
print('最后一个按钮 "%s": root 坐标 (%d,%d) %dx%d'
      % (last.cget('text'), lx, ly, last.winfo_width(), last.winfo_height()))
overlap = not (gx + gw <= lx or lx + last.winfo_width() <= gx
               or gy + gh <= ly or ly + last.winfo_height() <= gy)
print('拖动手柄压住按钮了吗:', '是 ***' if overlap else '否')

# 按钮底部有没有超出工具条（被垂直裁掉）
for b in app.tool.winfo_children():
    if not isinstance(b, tk.Label) or b is app.search_ph:
        continue
    by = b.winfo_y() + b.winfo_height()
    if by > app.tool.winfo_height():
        print('*** 按钮 %s 底部 %d 超出工具条高度 %d（被垂直裁切）'
              % (b.cget('text'), by, app.tool.winfo_height()))

print('DONE')
root.destroy()
os._exit(0)
