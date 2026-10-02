# -*- coding: utf-8 -*-
"""布局测量台：在若干宽度下量工具条/搜索框/按钮是否被裁。
用法：python _t20.py   （不写盘、不抢单实例、强制展开）"""
import io
import os
import sys

import ClawBoard as C
import tkinter as tk

C.NO_SAVE = True
C.DEFAULT_SETTINGS['collapsed'] = False

LOG = io.open('_t20.out', 'w', encoding='utf-8')


def p(s):
    LOG.write(str(s) + '\n')
    LOG.flush()


root = tk.Tk()
app = C.ClawBoard(root)
if app.collapsed:
    app.collapsed = False
    app.body.pack(fill='both', expand=True)
    root.minsize(*app.min_size())

for w in (280, 300, 320, 349, 380, 420, 460, 520, 640):
    root.geometry('%dx460+60+60' % w)
    root.update()
    app._last_tw = 0
    app._layout_tool()
    root.update()
    tool_w = app.tool.winfo_width()
    entry_w = app.search_entry.winfo_width()
    vis = [b.cget('text') for _, b in app._tool_btns if b.winfo_ismapped()]
    clipped = [(b.cget('text'), b.winfo_reqwidth(), b.winfo_width())
               for _, b in app._tool_btns
               if b.winfo_ismapped() and b.winfo_reqwidth() > b.winfo_width()]
    p('W=%-4d tool=%-4d entry=%-4d vis=%-22s clipped=%s'
      % (w, tool_w, entry_w, '/'.join(vis), clipped or '-'))

p('')
p('MIN_W=%d  TOOL_H=%d  btn_req=%d  entry_req=%d'
  % (C.MIN_W, C.TOOL_H, app._tool_btns[0][1].winfo_reqwidth(),
     app.search_entry.winfo_reqwidth()))
os._exit(0)
