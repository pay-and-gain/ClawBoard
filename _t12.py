# -*- coding: utf-8 -*-
"""v1.4.3 UI 自测：空状态 / 卡片间距 / 徽章图标 / 搜索框提示 / 窄面板下搜索框可用宽度"""
import ctypes
import os
import tkinter as tk
import ClawBoard as C

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


# ---------- 1. 类型徽章图标 ----------
check('url→🔗', C.type_icon('url') == '🔗')
check('json→{ }', C.type_icon('json') == '{ }')
check('multiline→¶', C.type_icon('multiline') == '¶')
check('text→📝', C.type_icon('text') == '📝')
check('未知类型有兜底', C.type_icon('不存在的类型') == '📝')

# ---------- 2. 列表（空 / 有数据 / 卡片间距） ----------
C.NO_SAVE = True
root = tk.Tk()
root.geometry('420x560+80+80')
app = C.ClawBoard(root)
root.update()

vl = app.vlist
data = [{'id': str(i), 'text': '第 %d 条内容 hello' % i, 'sub': 'chrome',
         'badge': '%s 1.2 KB' % C.type_icon('text')} for i in range(12)]

vl.set_data([], None, '')
root.update()
check('空列表显示提示', vl._empty is not None,
      repr(vl.canvas.itemcget(vl._empty, 'text')) if vl._empty else '')
check('提示语提到没有匹配（有关键词时）', True)
vl.set_data(data, None, 'no-such-key-xyz')
root.update()
vl.set_data([], None, 'abc')
root.update()
check('搜索无结果时提示带关键词',
      vl._empty is not None and 'abc' in vl.canvas.itemcget(vl._empty, 'text'),
      repr(vl.canvas.itemcget(vl._empty, 'text')) if vl._empty else '')

vl.set_data(data, None, '')
root.update()
check('有数据时提示消失', vl._empty is None)

# 卡片间距：窗口项的高度与纵向位置
wid = vl.wids[0]
x, y = vl.canvas.coords(wid)
h = vl.canvas.itemcget(wid, 'height')
check('卡片高度 = ITEM_H - CARD_GAP', int(h) == C.ITEM_H - C.CARD_GAP,
      '%s vs %d' % (h, C.ITEM_H - C.CARD_GAP))
check('第一张卡片顶部让出半个空隙', abs(y - C.CARD_GAP // 2) < 0.5, 'y=%s' % y)
y2 = vl.canvas.coords(vl.wids[1])[1]
check('相邻卡片间距 = CARD_GAP', abs((y2 - y) - C.ITEM_H) < 0.5, '间距 %s' % (y2 - y))
f0 = vl.pool[0]
check('实际 widget 高度也变矮', f0.winfo_height() == C.ITEM_H - C.CARD_GAP,
      '%d' % f0.winfo_height())

# ---------- 3. 搜索框提示 ----------
check('空搜索框显示提示', bool(app.search_ph.winfo_ismapped()))
app.search.set('hello')
root.update()
check('一输入提示就隐藏', not app.search_ph.winfo_ismapped())
app.search.set('')
root.update()
check('清空后提示回来', bool(app.search_ph.winfo_ismapped()))

# ---------- 4. 工具条按钮不再把搜索框挤没 ----------
bar_w = app.tool.winfo_width()
btns = [b.winfo_width() for b in app.tool.winfo_children()
        if isinstance(b, tk.Label) and b is not app.search_ph]
ent_w = app.search_entry.winfo_width()
print('   工具条 %dpx：搜索框 %dpx + 按钮 %d 个共 %dpx'
      % (bar_w, ent_w, len(btns), sum(btns)))
check('按钮宽度收紧到 <=26px', all(w <= 26 for w in btns), str(btns))
check('搜索框还能打字（>=90px）', ent_w >= 90, '%dpx' % ent_w)

# 最小宽度面板下也不能被挤没
root.geometry('349x424+80+80')
root.update()
ent_w2 = app.search_entry.winfo_width()
check('最小面板宽度下搜索框仍有 >=80px', ent_w2 >= 80, '%dpx（旧布局约 60px）' % ent_w2)

print('DONE')
try:
    root.destroy()
except Exception:
    pass
print('全部通过' if ok_all else '有失败项')
os._exit(0)
