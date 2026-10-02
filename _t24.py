# -*- coding: utf-8 -*-
"""v1.4.5 hotfix 回归：折叠态启动后展开 + 重复复制入库

两个 bug 都是从 crash.log 里挖出来的真崩溃，之前所有测试都没覆盖到：

A. `toggle_collapse()` 展开分支用了 `self._restore`，但它只在"折叠"时被赋值。
   如果程序**以折叠态启动**（存档 collapsed=True），第一次点「—」展开就会
   AttributeError → 面板展不开。crash.log 2026-10-03 01:22:33 就是这个。

B. `ingest()` 里 `rec` 只在"新条目"分支被赋值。重复复制时走到收尾的
   `rec['source_title']` 就 UnboundLocalError → 表现为"重复复制一条，列表毫无反应"。
   crash.log 里刷了几十条「监听异常：cannot access local variable 'rec'」。
"""
import io
import os

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


root = tk.Tk()
app = C.ClawBoard(root)
if app.collapsed:
    app.collapsed = False
    app.body.pack(fill='both', expand=True)
    root.minsize(*app.min_size())
root.geometry('400x480+120+120')
root.update()

# ---------------- A. 折叠态启动 → 展开 ----------------
check('_restore 初始有定义（不再是未定义属性）', hasattr(app, '_restore'),
      repr(getattr(app, '_restore', '<缺失>')))

# 模拟"上次是折叠着退出的"：把存档状态摆成折叠，再跑一遍 apply_geometry
app.data['geom'] = '400x480+120+120'          # 上次展开时的位置
app.st['collapsed'] = True
try:
    app.apply_geometry()
    root.update()
    ok_apply = True
    err_apply = ''
except Exception as e:
    ok_apply = False
    err_apply = repr(e)
check('折叠态 apply_geometry 不抛异常', ok_apply, err_apply)
check('apply_geometry 后处于折叠态', app.collapsed)
check('折叠态下 _restore 已被算好', bool(app._restore), repr(app._restore))
check('折叠态窗口是标题条高度', root.winfo_height() == C.BAR_H,
      '%d（期望 %d）' % (root.winfo_height(), C.BAR_H))

# 关键：第一次点「—」展开 —— 这就是原来崩的地方
try:
    app.toggle_collapse()
    root.update()
    ok_expand = True
    err_expand = ''
except Exception as e:
    ok_expand = False
    err_expand = repr(e)
check('★ 折叠态启动后第一次展开不抛异常', ok_expand, err_expand)
check('展开后 collapsed=False', not app.collapsed)
check('展开后 body 显示出来了', app.body.winfo_ismapped())
check('展开后尺寸不小于最小尺寸',
      root.winfo_width() >= app.min_size()[0] and root.winfo_height() >= app.min_size()[1],
      '%dx%d vs min %s' % (root.winfo_width(), root.winfo_height(), app.min_size()))
check('展开后回到存档的位置（左上角 120,120 附近）',
      abs(root.winfo_x() - 120) <= 2 and abs(root.winfo_y() - 120) <= 2,
      '实际 (%d,%d)' % (root.winfo_x(), root.winfo_y()))

# 再来一轮：展开 → 折叠 → 展开，确保反复切换都稳
start_collapsed = app.collapsed
try:
    for _ in range(3):
        app.toggle_collapse()
        root.update()
    ok_loop = True
    err_loop = ''
except Exception as e:
    ok_loop = False
    err_loop = repr(e)
check('折叠/展开来回三次不抛异常', ok_loop, err_loop)
# 切换奇数次 → 状态翻转
check('三次来回后状态正确翻转', app.collapsed == (not start_collapsed),
      '起始 collapsed=%s → 现在 %s' % (start_collapsed, app.collapsed))
# 收尾时确保是展开态，后面的用例要在展开态下跑
if app.collapsed:
    app.toggle_collapse()
    root.update()
check('收尾处于展开态', not app.collapsed)

# ---------------- A2. 折叠期间不污染 geom ----------------
app.toggle_collapse()                  # 折叠
root.update()
saved_geom = app.data['geom']
app.save()                             # NO_SAVE 下不写盘，但 do() 仍会更新 data
root.update()
check('折叠期间 save() 不把标题条尺寸写进 geom',
      app.data['geom'] == saved_geom, '%s → %s' % (saved_geom, app.data['geom']))
if app.collapsed:
    app.toggle_collapse()
    root.update()

# ---------------- B. ingest 重复复制 ----------------
app.data['clip'] = []
app.tab = 'clip'

try:
    app.ingest('hello world', manual=True)
    n1 = len(app.data['clip'])
    c1 = app.data['clip'][0]['copy_count']
    ok_i1 = True
    err_i1 = ''
except Exception as e:
    ok_i1, err_i1, n1, c1 = False, repr(e), -1, -1
check('首次 ingest 成功', ok_i1, err_i1)
check('首次 ingest 后 1 条', n1 == 1, str(n1))
check('首次 copy_count=1', c1 == 1, str(c1))

try:
    app.ingest('hello world', manual=True)     # 重复
    n2 = len(app.data['clip'])
    c2 = app.data['clip'][0]['copy_count']
    ok_i2 = True
    err_i2 = ''
except Exception as e:
    ok_i2, err_i2, n2, c2 = False, repr(e), -1, -1
check('★ 重复 ingest 不抛 UnboundLocalError', ok_i2, err_i2)
check('重复 ingest 后仍是 1 条（不重复建条目）', n2 == 1, str(n2))
check('重复 ingest 后 copy_count=2', c2 == 2, str(c2))

# 重复项要回到最前面
app.ingest('second text', manual=True)
app.ingest('hello world', manual=True)         # 再次重复，应置顶
texts = [x['text'] for x in app.data['clip']]
check('重复项被移到列表最前', texts[0] == 'hello world', str(texts))
check('重复项 copy_count 累计到 3',
      app.data['clip'][0]['copy_count'] == 3, str(app.data['clip'][0]['copy_count']))
check('总共 2 条（没有重复建条目）', len(app.data['clip']) == 2, str(len(app.data['clip'])))

# created_at 必须始终是第一次入库的时间，不能被重复复制改写
def created_of(t):
    for x in app.data['clip']:
        if x['text'] == t:
            return x['created_at']
    return None


before = created_of('hello world')
app.ingest('hello world', manual=True)
after = created_of('hello world')
check('★ 重复复制不改写 created_at', before == after, '%s → %s' % (before, after))

out = '\n'.join(LOG)
with io.open('C:/Users/pay and gain/AppData/Local/Temp/_t24.out', 'w',
             encoding='utf-8') as f:
    f.write(out + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))
os._exit(0)
