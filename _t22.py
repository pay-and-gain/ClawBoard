# -*- coding: utf-8 -*-
"""v1.4.5 自测：工具条响应式 + 溢出菜单 + 顺序稳定

踩过的坑（别再犯）：
- 测试实例直接 new ClawBoard(root) 会把存档里的 collapsed=True 带进来，
  body 被 pack_forget，量出来 body/tool/entry 全是 1px —— 看起来像布局塌了，
  其实是被折叠了。必须先 DEFAULT_SETTINGS['collapsed']=False 再 unpack。
- NO_SAVE=True 必须在构造前设好，否则压测/自测会往真实存档写热键和窗口位置。
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


def vis():
    return [b.cget('text') for _, b in app._tool_btns if b.winfo_ismapped()]


def vis_x():
    """按视觉 x 坐标排序后的可见按钮 —— 顺序对不对看这个，不是看 _tool_btns"""
    bs = [b for _, b in app._tool_btns if b.winfo_ismapped()]
    bs.sort(key=lambda b: b.winfo_x())
    return [b.cget('text') for b in bs]


def clipped():
    return [(b.cget('text'), b.winfo_reqwidth(), b.winfo_width())
            for _, b in app._tool_btns
            if b.winfo_ismapped() and b.winfo_reqwidth() > b.winfo_width()]


def setw(w):
    root.geometry('%dx460+60+60' % w)
    root.update()
    app._last_tw = 0          # 手动触发：Configure 只在宽度真的变了才回调
    app._layout_tool()
    root.update()


root = tk.Tk()
app = C.ClawBoard(root)
if app.collapsed:                     # 双保险：存档里若还是折叠态就展开
    app.collapsed = False
    app.body.pack(fill='both', expand=True)
    root.minsize(*app.min_size())

# ---------- 1. 宽面板：7 个全在，顺序正确 ----------
setw(640)
check('宽面板 7 个按钮全在', len(vis()) == 7, str(vis()))
check('宽面板顺序 ＋拆删清🔧?⚙', vis_x() == ['＋', '拆', '删', '清', '🔧', '?', '⚙'],
      str(vis_x()))
check('宽面板无溢出按钮', not app.more_btn.winfo_ismapped())
check('宽面板无裁切', not clipped(), str(clipped()))

# ---------- 2. 窄面板：次要项进「⋯」，核心项保留 ----------
setw(320)
v = vis_x()
check('窄面板藏起 ＋拆', '＋' not in v and '拆' not in v, str(v))
check('窄面板保留 删🔧?⚙', all(t in v for t in ('删', '🔧', '?', '⚙')), str(v))
check('窄面板出现 ⋯ 溢出按钮', app.more_btn.winfo_ismapped())
check('窄面板无裁切', not clipped(), str(clipped()))
ent = app.search_entry.winfo_width()
check('窄面板搜索框 >= 120px', ent >= 120, '%dpx' % ent)
check('窄面板记录了收起项', set(app._tool_hidden) == {'＋', '拆', '清'},
      str(app._tool_hidden))

# ---------- 3. 最小宽度 280：搜索框仍可用 ----------
setw(280)
check('MIN_W 280 下搜索框 >= 100px', app.search_entry.winfo_width() >= 100,
      '%dpx' % app.search_entry.winfo_width())
check('MIN_W 280 下无裁切', not clipped(), str(clipped()))

# ---------- 4. 宽→窄→宽 来回切：顺序必须还原（这是修掉的真 bug） ----------
setw(640)
check('来回切换后顺序还原', vis_x() == ['＋', '拆', '删', '清', '🔧', '?', '⚙'],
      str(vis_x()))
setw(320)
setw(640)
check('两轮来回后顺序仍正确',
      vis_x() == ['＋', '拆', '删', '清', '🔧', '?', '⚙'], str(vis_x()))
check('两轮来回后 ⋯ 已隐藏', not app.more_btn.winfo_ismapped())
check('两轮来回后 _tool_hidden 清空', app._tool_hidden == (), str(app._tool_hidden))

# ---------- 5. 折叠态不能把布局算坏 ----------
app._last_tw = 0
app.body.pack_forget()
root.update()
app._layout_tool()
check('折叠态（宽度退化 1px）不污染 _last_tw', app._last_tw == 0, str(app._last_tw))
app.body.pack(fill='both', expand=True)
root.update()
setw(320)
check('展开后仍能正常收起', set(app._tool_hidden) == {'＋', '拆', '清'},
      str(app._tool_hidden))

# ---------- 6. 溢出菜单里确实有被收起的项，且能回调 ----------
setw(320)
hidden_txt = [t for t, b in app._tool_btns if t in app._tool_hidden]
check('窄面板确实有被收起的按钮', len(hidden_txt) >= 2, str(hidden_txt))
check('被收起的按钮都带 _tip_cmd（菜单要用）',
      all(hasattr(dict(app._tool_btns)[t], '_tip_cmd') for t in hidden_txt),
      str(hidden_txt))

# 直接调 more_menu，用假的 tk_popup 拦下菜单内容
menus = []
real_popup = tk.Menu.tk_popup
tk.Menu.tk_popup = lambda self, x=0, y=0: menus.append(
    [self.entrycget(i, 'label') for i in range(self.index('end') + 1)])
try:
    app.more_menu(type('E', (), {'x_root': 10, 'y_root': 10})())
finally:
    tk.Menu.tk_popup = real_popup
labels = menus[0] if menus else []
check('溢出菜单已弹出', bool(menus))
check('菜单包含全部被收起项',
      all(any(lbl.startswith(t) for lbl in labels) for t in hidden_txt),
      '%s vs %s' % (labels, hidden_txt))

# ---------- 7. 标题栏长提示截断 ----------
long_tip = '这是一条非常非常非常非常非常非常非常非常非常长的提示信息' * 3
app.tip(long_tip)
root.update()
txt = app.title_lb.cget('text')
check('长提示被截断（带省略号）', txt.endswith('…') and len(txt) < len('⚡ ' + long_tip),
      'len=%d' % len(txt))
bar_w = app.bar.winfo_width()
btn_w = sum(b.winfo_width() for b in getattr(app, '_bar_btns', []))
check('提示文字没有盖过标题栏右侧按钮',
      app.title_lb.winfo_x() + app.title_lb.winfo_width() <= bar_w - btn_w + 2,
      'title_end=%d / 可用=%d' % (app.title_lb.winfo_x() + app.title_lb.winfo_width(),
                                  bar_w - btn_w))
app.tip('已复制')
root.update()
check('短提示不截断', app.title_lb.cget('text') == '⚡ 已复制',
      repr(app.title_lb.cget('text')))

out = '\n'.join(LOG)
with io.open('C:/Users/pay and gain/AppData/Local/Temp/_claw_t22.out', 'w', encoding='utf-8') as f:
    f.write(out + '\n\n')
    f.write('全部通过\n' if OK else '有失败项\n')
    for w in (280, 300, 320, 349, 380, 420, 500, 640):
        setw(w)
        f.write('W=%-4d tool=%-4d entry=%-4d vis=%-24s ⋯=%s\n'
                % (w, app.tool.winfo_width(), app.search_entry.winfo_width(),
                   '/'.join(vis()), app.more_btn.winfo_ismapped()))
os._exit(0)
