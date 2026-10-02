# -*- coding: utf-8 -*-
"""定位 _t16 卡在哪一步：分段打点，5秒没到下一段就退出"""
import ctypes
import os
import sys
import time
import tkinter as tk

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass


def mark(s):
    print('[%6.2fs] %s' % (time.time() - T0, s), flush=True)


T0 = time.time()
mark('start')
import ClawBoard as C
mark('import ClawBoard')

C.NO_SAVE = True
root = tk.Tk()
mark('Tk()')
root.geometry('349x424+80+80')
mark('geometry')
app = C.ClawBoard(root)
mark('ClawBoard()')
root.update()
mark('update')

print('root    ', root.winfo_width(), root.winfo_height(), 'mapped=', root.winfo_ismapped(), flush=True)
print('body    ', app.body.winfo_width(), app.body.winfo_height(), flush=True)
print('tool    ', app.tool.winfo_width(), app.tool.winfo_height(), flush=True)
print('vlist   ', app.vlist.winfo_width(), app.vlist.winfo_height(), flush=True)
print('bar     ', app.bar.winfo_width(), app.bar.winfo_height(), flush=True)
print('entry   ', app.search_entry.winfo_width(), 'req=', app.search_entry.winfo_reqwidth(), flush=True)
print('visible ', [b.cget('text') for _, b in app._tool_btns if b.winfo_ismapped()], flush=True)
print('all btn ', [(b.cget('text'), b.winfo_ismapped(), b.winfo_width(), b.winfo_reqwidth())
                  for _, b in app._tool_btns], flush=True)
print('_last_tw=', app._last_tw, flush=True)
mark('done')
os._exit(0)
