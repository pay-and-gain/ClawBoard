# -*- coding: utf-8 -*-
"""v1.4.4 自测：内容自适应判定 classify()（纯函数）+ 卡片样式是否跟着类型走"""
import ctypes
import os
import tkinter as tk
import tkinter.font as tkfont

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ClawBoard as C

ok_all = True


def check(name, cond, extra=''):
    global ok_all
    if not cond:
        ok_all = False
    print('%s  %s%s' % ('OK  ' if cond else 'FAIL', name, ('  ' + extra) if extra else ''))


K = lambda t: C.classify(t)[0]

# ---------- 1. URL / 邮箱 / 颜色 ----------
check('https 链接', K('https://github.com/hluk/CopyQ') == 'url')
check('www 链接', K('www.baidu.com') == 'url')
check('域名被提取出来', C.classify('https://github.com/a/b')[1].get('host') == 'github.com',
      str(C.classify('https://github.com/a/b')[1]))
check('邮箱', K('someone@example.com') == 'email')
check('邮箱不会误判成链接', K('someone@example.com') != 'url')
check('色值 #1e2027', K('#1e2027') == 'color')
check('色值 #abc', K('#abc') == 'color')
check('css 函数色', K('rgb(30, 32, 39)') == 'color')
check('带点的普通词不是链接', K('facade.txt') != 'url', K('facade.txt'))
check('含空格的像链接的不是链接', K('https://a.com and more') != 'url')

# ---------- 2. 路径 ----------
here = os.path.abspath('ClawBoard.py')
check('存在的绝对路径 → path', K(here) == 'path', K(here))
check('路径带行号也能认', K(here + ':42') == 'path', K(here + ':42'))
check('路径文件名被提取', C.classify(here)[1].get('basename') == 'ClawBoard.py')
check('不存在的路径不算', K('/no/such/file/here.py') != 'path')

# ---------- 3. JSON：必须在代码之前，且只认顶层容器 ----------
check('对象 JSON', K('{"a": 1, "b": [1,2]}') == 'json')
check('数组 JSON', K('[1, 2, 3]') == 'json')
check('JSON 标量不算（"abc"）', K('"abc"') != 'json', K('"abc"'))
check('JSON 标量不算（123）', K('123') != 'json', K('123'))
check('null 不算', K('null') != 'json', K('null'))
check('坏 JSON 不算', K('{"a": }') != 'json')
check('多行 JSON 也算', K('{\n  "a": 1\n}') == 'json')

# ---------- 4. 代码：证据叠加 ----------
check('python 代码', K('def foo():\n    pass\n    return 1') == 'code')
check('单行 def 开头也算', K('def foo(): pass') == 'code')
check('js 箭头函数', K('const f = () => 1') == 'code')
check('html 标签', K('<div class="a">x</div>') == 'code')
check('只有 {} 的散文不算代码', K('你好 {name} 欢迎') != 'code', K('你好 {name} 欢迎'))
check('两行缩进才算', K('a\n  b') != 'code', K('a\n  b'))
check('语言猜测 python', C.guess_lang('def foo():\n    pass') == 'python',
      C.guess_lang('def foo():\n    pass'))
check('语言猜测 javascript', C.guess_lang('function a() { return 1 }') == 'javascript',
      C.guess_lang('function a() { return 1 }'))

# ---------- 5. 其余 ----------
check('多行文本', K('第一行\n第二行') == 'multiline')
check('普通单行', K('今天天气不错') == 'text')
check('空内容', K('') == 'text' and K('   ') == 'text')
check('超长直接降级', K('x' * (C.CLASSIFY_MAX + 10)) == 'text')

# ---------- 6. 卡片样式真的跟着类型走 ----------
C.NO_SAVE = True
C.DEFAULT_SETTINGS['collapsed'] = False
root = tk.Tk()
root.geometry('420x560+80+80')
app = C.ClawBoard(root)
# 上次退出时若折叠，body 被 pack_forget → 虚拟列表只建出 1~2 行，
# 后面访问 pool[3] 直接 KeyError（假失败）
if app.collapsed:
    app.collapsed = False
    app.st['collapsed'] = False
    app.body.pack(fill='both', expand=True)
    app.root.minsize(*app.min_size())
root.update()

items = [
    ('https://github.com/hluk/CopyQ', '链接'),
    ('{"a": 1, "b": [1, 2]}', 'JSON'),
    ('def foo():\n    pass\n    return 1', '代码'),
    ('第一行\n第二行\n第三行', '多行'),
    ('#1e2027', '颜色'),
]
data = []
for i, (t, _) in enumerate(items):
    k = C.classify(t)[0]
    data.append({'id': str(i), 'disp': t, 'text': t, 'sub': 'chrome',
                 'badge': '%s 1 KB' % C.kind_icon(k), 'kind_auto': k})
app.vlist.set_data(data, None, '')
root.update()

mono = str(tkfont.Font(font=C.FONT_MONO).actual()['family'])
ui = str(tkfont.Font(font=C.FONT).actual()['family'])
print('   等宽字体=%s / 界面字体=%s' % (mono, ui))

for i, (t, label) in enumerate(items):
    f = app.vlist.pool[i]
    fam = tkfont.Font(font=f._l1a.cget('font')).actual()['family']
    col = f._l1a.cget('fg')
    want_mono = C.classify(t)[0] in ('code', 'json')
    want_acc = C.classify(t)[0] == 'url'
    ok = (str(fam) == (mono if want_mono else ui)) and \
         (col == (C.T['acc'] if want_acc else C.T['fg']))
    check('%s：字体%s 颜色%s' % (label, '等宽' if want_mono else '普通',
                                '强调' if want_acc else '常规'), ok,
          '实际字体 %s / 颜色 %s' % (fam, col))

print('DONE')
try:
    root.destroy()
except Exception:
    pass
print('全部通过' if ok_all else '有失败项')
os._exit(0)
