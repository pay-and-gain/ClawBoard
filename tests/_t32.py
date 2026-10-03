# -*- coding: utf-8 -*-
"""v1.9.0 自测：拼音查表 + 拼音搜索匹配"""
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clawboard.pinyin import to_pinyin, to_pinyin_initials
import query as Q

OK = True
LOG = []


def check(name, cond, extra=''):
    global OK
    if not cond:
        OK = False
    LOG.append('%s  %s%s' % ('OK  ' if cond else 'FAIL', name,
                             ('  ' + extra) if extra else ''))


# ---------- 1. 查表 ----------
check('全拼 账号→zhanghao', to_pinyin('账号') == 'zhanghao', to_pinyin('账号'))
check('首字母 账号→zh', to_pinyin_initials('账号') == 'zh')
check('全拼 银行→yinhang', to_pinyin('银行') == 'yinhang', to_pinyin('银行'))
check('非汉字原样保留', to_pinyin('123abc') == '123abc')
check('空串/None 安全', to_pinyin('') == '' and to_pinyin(None) == '')
check('混合中英', to_pinyin('中a国b') == 'zhongaguob')

# ---------- 1b. 多音字词组纠正 ----------
check('重庆→chongqing', to_pinyin('重庆') == 'chongqing', to_pinyin('重庆'))
check('长城→changcheng', to_pinyin('长城') == 'changcheng')
check('长大→zhangda', to_pinyin('长大') == 'zhangda')
check('音乐→yinyue', to_pinyin('音乐') == 'yinyue')
check('快乐→kuaile', to_pinyin('快乐') == 'kuaile')
check('重复→chongfu', to_pinyin('重复') == 'chongfu')

# ---------- 2. 搜索匹配：拼音命中 ----------
items = [
    {'text': '我的账号是 master', 'name': ''},
    {'text': 'hello world', 'name': ''},
    {'text': '银行卡号 6222', 'name': ''},
]
r, cond = Q.match('zhanghao', items)
check('搜全拼 zhanghao 命中账号', len(r) == 1 and '账号' in r[0]['text'], str(len(r)))
r, cond = Q.match('zh', items)
check('搜首字母 zh 命中账号', any('账号' in x['text'] for x in r))
r, cond = Q.match('yinhang', items)
check('搜全拼 yinhang 命中银行卡', len(r) == 1 and '银行' in r[0]['text'])
r, cond = Q.match('hello', items)
check('英文搜索仍正常', len(r) == 1 and 'hello' in r[0]['text'])
r, cond = Q.match('bucunzai', items)
check('拼音无命中返回空', len(r) == 0)

# ---------- 3. 拼音 + 排除 ----------
r, cond = Q.match('zh -master', items)
check('拼音 + 排除词 组合', len(r) == 0)

with io.open(os.path.join(tempfile.gettempdir(), '_t32.out'), 'w',
             encoding='utf-8') as f:
    f.write('\n'.join(LOG) + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))
os._exit(0)
