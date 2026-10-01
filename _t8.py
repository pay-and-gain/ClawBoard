# -*- coding: utf-8 -*-
"""v1.4.0 借鉴 Ditto / CopyQ / PasteBar 后的自测：
隐私标记 / 忽略名单 / 长度过滤 / 收藏保护裁剪 / Ctrl+数字序号 / 多词高亮 / INPUT 结构体"""
import ctypes
import os
import tkinter as tk
import ClawBoard as C

ok_all = True


def check(name, cond, extra=''):
    global ok_all
    if not cond:
        ok_all = False
    print('%s  %s%s' % ('OK  ' if cond else 'FAIL', name, ('  ' + extra) if extra else ''))


# ---------- 1. SendInput 结构体：大小必须与系统一致，否则按键根本发不出去 ----------
check('sizeof(INPUT)==40 (64bit)', ctypes.sizeof(C.INPUT) == 40,
      '实际 %d' % ctypes.sizeof(C.INPUT))
check('sizeof(KEYBDINPUT)==24', ctypes.sizeof(C.KEYBDINPUT) == 24,
      '实际 %d' % ctypes.sizeof(C.KEYBDINPUT))
check('INPUT.u 偏移==8', C.INPUT.u.offset == 8, '实际 %d' % C.INPUT.u.offset)
inp = C._kbd(C.VK_V)
check('_kbd 带扫描码', inp.u.ki.wScan > 0 and inp.u.ki.wVk == C.VK_V,
      'vk=%d scan=%d' % (inp.u.ki.wVk, inp.u.ki.wScan))
check('_kbd 按下/抬起 flag', C._kbd(C.VK_V, True).u.ki.dwFlags == C.KEYEVENTF_KEYUP)

# ---------- 2. 忽略名单（Ditto ClipboardViewer.cpp:345 的通配语义） ----------
check('解析：逗号分隔', C.parse_ignore_list('keepass, 微信') == ['*keepass*', '*微信*'])
check('解析：保留通配符', C.parse_ignore_list('*.exe, keep?ss') == ['*.exe', 'keep?ss'])
check('解析：换行/分号/顿号', C.parse_ignore_list('a\nb;c、d') == ['*a*', '*b*', '*c*', '*d*'])
check('解析：空串', C.parse_ignore_list('') == [] and C.parse_ignore_list(None) == [])
check('命中：应用名通配', C.match_ignore('keepass.exe', '', 'keepass', '') is not None)
check('命中：显式通配', C.match_ignore('1password.exe', '', '*, 1password*', '') is not None)
check('命中：大小写不敏感', C.match_ignore('KeePassXC.exe', '', 'keepass', '') is not None)
check('不命中：别的程序', C.match_ignore('chrome.exe', 'GitHub', 'keepass', '') is None)
check('命中：标题正则', C.match_ignore('chrome.exe', '登录 - 密码管理', '', '密码') is not None)
check('命中：标题正则（大小写）', C.match_ignore('x.exe', 'PASSWORD MANAGER', '', 'password'))
check('不命中：标题不匹配', C.match_ignore('chrome.exe', 'GitHub', '', '密码') is None)
check('非法正则降级为子串', C.match_ignore('x.exe', 'a[b', '', 'a[b') is not None)
check('空规则不误杀', C.match_ignore('anything.exe', 't', '', '') is None)

# ---------- 3. 长度上下限（PasteBar clipTextMinLength / clipTextMaxLength） ----------
check('下限拦截', C.length_filtered('ab', 5, 0) is not None)
check('下限放行', C.length_filtered('abcde', 5, 0) is None)
check('上限拦截', C.length_filtered('x' * 11, 0, 10) is not None)
check('上限放行', C.length_filtered('x' * 10, 0, 10) is None)
check('0=不限', C.length_filtered('a', 0, 0) is None)

# ---------- 4. 裁剪要跳过收藏（Ditto RemoveOldEntries / CopyQ cropToSize） ----------
items = [{'id': str(i), 'fav': 1 if i in (7, 9) else 0} for i in range(10)]
kept = C.crop_items(items, 5)
check('裁剪到 5 条', len([x for x in kept if x['id'] not in ('7', '9')]) == 5)
check('收藏项被保住', {x['id'] for x in kept if x['fav']} == {'7', '9'},
      '实际 %s' % sorted(x['id'] for x in kept if x['fav']))
check('未超限不动', C.crop_items(items, 20) == items)

# ---------- 5. 隐私标记函数可用（只读剪贴板，不动用户内容） ----------
try:
    v = C.clip_is_private()
    check('clip_is_private 返回 bool 且不抛异常', isinstance(v, bool), '读到 %r' % v)
    check('普通文本不算私有', v is False)
except Exception as e:
    check('clip_is_private 可调用', False, repr(e))
check('格式 id 查询稳定', C._clip_fmt_id(C.CF_NAME_EXCLUDE) == C._clip_fmt_id(C.CF_NAME_EXCLUDE))

# ---------- 6. 列表：多词高亮 + Ctrl 序号 ----------
root = tk.Tk()
root.geometry('340x480+60+60')
data = [{'id': str(i), 'text': 'hello world 第 %d 条' % i, 'time': '2026-10-01 10:00'}
        for i in range(12)]
vl = C.VirtualList(root, lambda i, e: None, lambda e, i: None, lambda i, x, y: None)
vl.pack(fill='both', expand=True)
root.update()
vl.set_data(data, None, 'hello world')
root.update()

word, pos = vl._first_hit('hello world 第 3 条')
check('多词：整串命中', (word, pos) == ('hello world', 0), '%r %d' % (word, pos))
word, pos = vl._first_hit('xx hello yy')          # 整串找不到，应退到单字命中
check('多词：退到单词命中', (word, pos) == ('hello', 3), '%r %d' % (word, pos))
check('完全不命中', vl._first_hit('nothing here') == ('', -1))

f = vl.pool[0]
check('命中处高亮到 _l1b', f._l1b.cget('text') == 'hello world',
      repr(f._l1b.cget('text')))

vl.show_num = True
vl.update_view()
root.update()
f0, f9 = vl.pool[0], vl.pool[9]
check('序号 1..9', f0._num.cget('text') == '1', repr(f0._num.cget('text')))
check('第 10 项显示 0（PasteBar）', f9._num.cget('text') == '0', repr(f9._num.cget('text')))
vl.show_num = False
vl.update_view()
root.update()
check('松开 Ctrl 序号消失', vl.pool[0]._num.cget('text') == '')

# 序号列不能压住正文
x_num = f0._num.winfo_x() + f0._num.winfo_width()
x_row = f0._row.winfo_x()
check('序号列与正文不重叠', x_num <= x_row, '序号右缘 %d <= 正文左缘 %d' % (x_num, x_row))

print('DONE')
try:
    root.destroy()
except Exception:
    pass
print('全部通过' if ok_all else '有失败项')
os._exit(0)
