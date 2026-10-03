# -*- coding: utf-8 -*-
"""v2.1.0 自测：内容自动标签 + tag: 搜索"""
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clawboard.tag import detect_tags, normalize_tag
import query as Q

OK = True
LOG = []


def check(name, cond, extra=''):
    global OK
    if not cond:
        OK = False
    LOG.append('%s  %s%s' % ('OK  ' if cond else 'FAIL', name,
                             ('  ' + extra) if extra else ''))


# ---------- 1. detect_tags ----------
check('邮箱', 'email' in detect_tags('联系 master@example.com'))
check('手机号', 'phone' in detect_tags('13800138000'))
check('纯数字', 'number' in detect_tags('12345.67'))
check('日期', 'date' in detect_tags('2026-10-03 会议'))
check('代码', 'code' in detect_tags('def foo():\n    return 1'))
check('JSON 标 json 不标 code',
      detect_tags('{"a":1}') == ['json'], str(detect_tags('{"a":1}')))
check('链接', 'url' in detect_tags('https://github.com'))
check('空/None 安全', detect_tags('') == [] and detect_tags(None) == [])
check('非 str 安全', detect_tags(123) == [])
check('normalize_tag 中文别名', normalize_tag('邮箱') == 'email')
check('normalize_tag 未知返回 None', normalize_tag('不存在') is None)

# ---------- 2. tag: 搜索 ----------
items = [
    {'text': '联系 master@example.com', 'tags': ['email']},
    {'text': '13800138000', 'tags': ['phone', 'number']},
    {'text': 'hello', 'tags': []},
]
r, cond = Q.match('tag:email', items)
check('tag:email 命中邮箱', len(r) == 1 and 'email' in r[0]['tags'])
r, cond = Q.match('tag:邮箱', items)
check('tag:邮箱 中文别名命中', len(r) == 1 and 'email' in r[0]['tags'])
r, cond = Q.match('tag:number', items)
check('tag:number 命中数字', len(r) == 1 and 'phone' in r[0]['tags'])
r, cond = Q.match('-tag:email', items)
check('-tag:email 排除邮箱', len(r) == 2 and all('email' not in (x['tags'] or []) for x in r))
r, cond = Q.match('tag:不存在', items)
check('未知标签不抛异常且全量', len(r) == 3 and cond['errors'])

with io.open(os.path.join(tempfile.gettempdir(), '_t34.out'), 'w',
             encoding='utf-8') as f:
    f.write('\n'.join(LOG) + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))
os._exit(0)
