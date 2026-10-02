# -*- coding: utf-8 -*-
"""v1.4.5 自测：窄面板下工具条按钮自适应收起（不再被压成残废）+ 标题栏提示截断"""
import ctypes
import os
import tkinter as tk

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import ClawBoard as C

ok_all = True


def check(name, cond, extra=''):
    global ok_all
    if not cond:
        ok_all = False
    print('%s  %s%s' % ('OK  ' if cond else 'FAIL', name, ('  ' + extra) if extra else ''))


C.NO_SAVE = True
C.DEFAULT_SETTINGS['collapsed'] = False
root = tk.Tk()
root.minsize(C.MIN_W, C.MIN_H)
root.geometry('349x424+80+80')
app = C.ClawBoard(root)
# 上次退出时若是折叠态，body 会被 pack_forget（工具条宽度退化成 1px），
# 那样测出来的"布局坏了"是假象。先强制展开
if app.collapsed:
    app.collapsed = False
    app.st['collapsed'] = False
    app.body.pack(fill='both', expand=True)
    app.root.minsize(*app.min_size())
app._last_tw = 0
root.update()
app._layout_tool()
root.update()


def visible_texts():
    return [b.cget('text') for _, b in app._tool_btns if b.winfo_ismapped()]


# ---------- 1. 窄面板：次要按钮收起，保留下来的必须完整 ----------
w = app.tool.winfo_width()
vis = visible_texts()
print('   工具条 %dpx，可见按钮：%s' % (w, vis))
check('窄面板收起 ＋/拆/清', all(t not in vis for t in ('＋', '拆', '清')), str(vis))
check('删/🔧/?/⚙ 保留', all(t in vis for t in ('删', '🔧', '?', '⚙')), str(vis))
bad = []
for _, b in app._tool_btns:
    if b.winfo_ismapped() and b.winfo_reqwidth() > b.winfo_width():
        bad.append((b.cget('text'), b.winfo_reqwidth(), b.winfo_width()))
check('保留的按钮没有被裁', not bad, str(bad))
ent = app.search_entry.winfo_width()
check('搜索框仍然够宽（>=120px）', ent >= 120, '%dpx' % ent)

# ---------- 2. 拉宽：按钮全部回来，顺序不变 ----------
root.geometry('560x424+80+80')
root.update()
app._last_tw = 0
app._layout_tool()
root.update()
vis2 = visible_texts()
check('宽面板按钮全回来', len(vis2) == 7, str(vis2))
check('顺序保持 ＋拆删清🔧?⚙',
      vis2 == ['＋', '拆', '删', '清', '🔧', '?', '⚙'], str(vis2))
# 复原时必须带回原来的 padx/pady，否则按钮会挤成一坨贴左边
# 注意：Label 自身也有 padx/pady 选项（默认 1），cget 取不到 pack 参数，要用 pack_info()
pad_bad = []
for _, b in app._tool_btns:
    pi = b.pack_info()
    if int(pi.get('padx', 0)) != 1 or int(pi.get('pady', 0)) != 7 \
            or pi.get('side') != 'left':
        pad_bad.append((b.cget('text'), pi.get('side'), pi.get('padx'), pi.get('pady')))
check('复原后 pack 参数未丢失', not pad_bad, str(pad_bad))

# ---------- 3. 再缩回去：又能正常收起（来回切换不坏） ----------
root.geometry('349x424+80+80')
root.update()
app._last_tw = 0
app._layout_tool()
root.update()
vis3 = visible_texts()
check('再缩窄仍正常收起', all(t not in vis3 for t in ('＋', '拆', '清')), str(vis3))

# ---------- 4. 标题栏长提示截断，不会顶到右侧按钮 ----------
long_tip = '这是一条非常非常非常非常非常非常非常非常非常长的提示信息' * 3
app.tip(long_tip)
root.update()
txt = app.title_lb.cget('text')
tl_w = app.title_lb.winfo_width()
bar_w = app.bar.winfo_width()
btn_w = sum(b.winfo_width() for b in getattr(app, '_bar_btns', []))
check('长提示被截断（带省略号）', txt.endswith('…') and len(txt) < len('⚡ ' + long_tip),
      'len=%d' % len(txt))
check('提示文字没有盖过右侧按钮', tl_w <= bar_w - btn_w + 2,
      '标题 %d / 标题栏 %d / 按钮 %d' % (tl_w, bar_w, btn_w))
short = '已复制'
app.tip(short)
root.update()
check('短提示不截断', app.title_lb.cget('text') == '⚡ ' + short,
      repr(app.title_lb.cget('text')))

print('DONE')
try:
    root.destroy()
except Exception:
    pass
print('全部通过' if ok_all else '有失败项')
os._exit(0)
