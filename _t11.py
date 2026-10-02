# -*- coding: utf-8 -*-
"""v1.4.2 自测：① 双击折叠热区覆盖整条标题栏 ② 粘贴前去掉首尾空白"""
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


# ---------- 1. 粘贴裁剪（用轻量替身，只用到 self.st） ----------
class Fake:
    def __init__(self, trim):
        self.st = {'trim_paste': trim}

    trim_for_paste = C.ClawBoard.trim_for_paste


on = Fake(True)
off = Fake(False)

check('前导空格被去掉', on.trim_for_paste('  hello') == 'hello',
      repr(on.trim_for_paste('  hello')))
check('换行+缩进被去掉', on.trim_for_paste('\n  hello\n') == 'hello',
      repr(on.trim_for_paste('\n  hello\n')))
check('原本干净的不动', on.trim_for_paste('hello world') == 'hello world')
check('多行中间缩进保留（代码块要留）',
      on.trim_for_paste('  a\n    b  ') == 'a\n    b',
      repr(on.trim_for_paste('  a\n    b  ')))
check('全空白得到空串', on.trim_for_paste('   \n ') == '')
check('空/None 不出错', on.trim_for_paste('') == '' and on.trim_for_paste(None) == '')
check('关掉开关则原样', off.trim_for_paste('  hello ') == '  hello ',
      repr(off.trim_for_paste('  hello ')))
check('默认值是开', C.DEFAULT_SETTINGS.get('trim_paste') is True)

# ---------- 2. 标题栏：整条可双击 + 按钮热区变大 ----------
C.NO_SAVE = True
root = tk.Tk()
root.geometry('340x480+80+80')
app = C.ClawBoard(root)
root.update()

check('bar 本身有双击', bool(app.bar.bind('<Double-Button-1>')))
check('标题文字也有双击（原来只有 bar 的一小条空白能点）',
      bool(app.title_lb.bind('<Double-Button-1>')))
check('标题文字也能拖动窗口', bool(app.title_lb.bind('<ButtonPress-1>')))

bar_w = app.bar.winfo_width()
tl_w = app.title_lb.winfo_width()
btn_w = sum(b.winfo_width() for b in app.bar.winfo_children()
            if isinstance(b, tk.Label) and b is not app.title_lb)
print('   标题栏 %dpx = 标题 %dpx + 按钮 %dpx' % (bar_w, tl_w, btn_w))
check('标题占满剩余宽度（热区不再是窄窄一条）',
      tl_w >= bar_w - btn_w - 20, '标题 %d / 可用 %d' % (tl_w, bar_w - btn_w))
check('热区占标题栏一半以上', tl_w > bar_w * 0.5, '%.0f%%' % (100.0 * tl_w / bar_w))

btns = [(b.cget('text'), b.winfo_width(), b.winfo_height())
        for b in getattr(app, '_bar_btns', [])]
print('   按钮(文字,宽,高):', btns)
check('按钮热区变高（>=24px）', all(h >= 24 for (_, _, h) in btns), str(btns))
check('按钮热区变宽（>=24px）', all(w >= 24 for (_, w, _) in btns), str(btns))
check('标题栏高度 = BAR_H', app.bar.winfo_height() == C.BAR_H,
      '%d vs %d' % (app.bar.winfo_height(), C.BAR_H))

# 折叠/展开本身要正常（tkinter 的 event_generate 发不了 Double 事件，直接调同一入口）
before = app.collapsed
before_h = root.winfo_height()
app.toggle_collapse()
root.update()
check('折叠后只剩标题栏高度', app.collapsed and root.winfo_height() == C.BAR_H,
      '高度 %d' % root.winfo_height())
app.toggle_collapse()
root.update()
check('再展开回到原高度', (not app.collapsed) and root.winfo_height() == before_h,
      '高度 %d（原 %d）' % (root.winfo_height(), before_h))
check('折叠状态回到初始值', app.collapsed == before)

print('DONE')
try:
    root.destroy()
except Exception:
    pass
print('全部通过' if ok_all else '有失败项')
os._exit(0)
