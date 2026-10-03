# -*- coding: utf-8 -*-
"""v1.8.0 自测：TriggerEngine 触发词匹配（纯逻辑）"""
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clawboard.trigger import TriggerEngine

OK = True
LOG = []


def check(name, cond, extra=''):
    global OK
    if not cond:
        OK = False
    LOG.append('%s  %s%s' % ('OK  ' if cond else 'FAIL', name,
                             ('  ' + extra) if extra else ''))


def feed_str(e, s):
    """逐个字符喂入，返回最后一次 feed 的返回值（命中结果）"""
    r = None
    for ch in s:
        r = e.feed(ch)
    return r


# 1. 基本触发：dz + 空格
e = TriggerEngine({'dz': '地址'})
check('输入 dz 本身不触发', feed_str(e, 'dz') is None)
check('dz+空格 触发', feed_str(e, ' ') == ('dz', '地址'),
      str(feed_str(e, ' ')))

# 2. 词边界：address 不该触发 addr
e = TriggerEngine({'addr': '地址'})
check('address+空格 不触发 addr（前面是字母）', feed_str(e, 'address ') is None)

# 3. 词边界：前面是空格则触发
e = TriggerEngine({'addr': '地址'})
check('xx addr+空格 触发', feed_str(e, 'xx addr ') == ('addr', '地址'))

# 4. 长触发词优先
e = TriggerEngine({'邮': '短', '邮箱': '长'})
check('邮箱 优先于 邮', feed_str(e, '邮箱 ') == ('邮箱', '长'))

# 5. 退格同步
e = TriggerEngine({'dz': '地址'})
feed_str(e, 'dzz')
e.feed_backspace()
check('退格后 dz+空格 触发', feed_str(e, ' ') == ('dz', '地址'))

# 6. 中文分隔符
e = TriggerEngine({'dz': '地址'})
check('dz+中文逗号 触发', feed_str(e, 'dz，') == ('dz', '地址'))

# 7. 换行分隔符
e = TriggerEngine({'dz': '地址'})
check('dz+换行 触发', feed_str(e, 'dz\n') == ('dz', '地址'))

# 8. 空触发器安全
e = TriggerEngine({})
check('空触发器不触发', feed_str(e, 'abc ') is None)

# 9. 非 str 输入安全
e = TriggerEngine({'dz': '地址'})
check('非 str 输入安全', e.feed(123) is None and e.feed(None) is None)

# 10. 前缀重叠：foobar 优先于 foo
e = TriggerEngine({'foo': '短', 'foobar': '长'})
check('foobar 优先于 foo', feed_str(e, 'foobar ') == ('foobar', '长'))

# 11. 无边界场景：直接粘连 'xdz ' 触发（dz 前是 x，非词边界字符？x 是字母，算词边界）
#     所以 'xdz ' 不应触发（dz 前面是字母 x，构成单词 xdz）
e = TriggerEngine({'dz': '地址'})
check('xdz+空格 不触发（dz 前是字母）', feed_str(e, 'xdz ') is None)

# 12. 触发词含下划线视为词字符
e = TriggerEngine({'my_t': 'x'})
check('触发词本身含下划线仍可匹配', feed_str(e, 'my_t ') == ('my_t', 'x'))

with io.open(os.path.join(tempfile.gettempdir(), '_t31.out'), 'w',
             encoding='utf-8') as f:
    f.write('\n'.join(LOG) + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))
os._exit(0)
