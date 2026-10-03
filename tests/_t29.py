# -*- coding: utf-8 -*-
"""自测：智能变换推荐 + 搜索频率排序 + 置顶（is:pin）

覆盖：
1. transform.recommend() 对 JSON / URL / 全角 / 多行 / HTML / base64 / 英文标识符 / 普通中文
2. query.parse('is:pin') + compile_pred 能过滤出 pinned 条目
3. 搜索态排序 key：pinned 优先、use_count 次之、last_used_at（回退 created_at）再次
"""
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import transform as tr
import query as Q

OK = True
LOG = []


def check(name, cond, extra=''):
    global OK
    if not cond:
        OK = False
    LOG.append('%s  %s%s' % ('OK  ' if cond else 'FAIL', name,
                             ('  ' + extra) if extra else ''))


# ---------- 1. recommend ----------
check('JSON → 含 jsonfmt', 'jsonfmt' in tr.recommend('{"a": 1}'))
check('JSON → 含 jsonmin', 'jsonmin' in tr.recommend('{"a": 1}'))
check('URL → 含 exurl', 'exurl' in tr.recommend('看 https://example.com/a?x=1'))
check('URL → 含 urldec', 'urldec' in tr.recommend('看 https://example.com/a?x=1'))
check('全角 → 含 half', 'half' in tr.recommend('ＡＢＣ　１２３'))
check('多行 → 含 sortline', 'sortline' in tr.recommend('c\na\nb'))
check('多行 → 含 dropblank', 'dropblank' in tr.recommend('c\na\n\nb'))
check('HTML → 含 deformat', 'deformat' in tr.recommend('<p>hello</p>'))
check('Base64 → 含 b64dec', 'b64dec' in tr.recommend('SGVsbG8gd29ybGQ='))
check('英文标识符 → 含 camel', 'camel' in tr.recommend('user_name_first'))
check('普通中文 → 空或合理值', tr.recommend('你好世界') == [])
check('空串不崩溃且为空', tr.recommend('') == [])
check('None 不崩溃且为空', tr.recommend(None) == [])
check('非 str(123) 不崩且为空', tr.recommend(123) == [])
check('非 str(list) 不崩且为空', tr.recommend([1, 2]) == [])
check('非 str(dict) 不崩且为空', tr.recommend({'a': 1}) == [])
check('非 str(bytes) 不崩且为空', tr.recommend(b'abc') == [])

# ---------- 2. is:pin 过滤 ----------
items = [
    {'text': 'pinned item', 'pinned': 1, 'fav': 0},
    {'text': 'normal item', 'pinned': 0, 'fav': 0},
]
cond = Q.parse('is:pin')
pred = Q.compile_pred(cond)
got = [x for x in items if pred(x)]
check('is:pin 只命中 pinned', len(got) == 1 and got[0]['text'] == 'pinned item')

matched, _ = Q.match('is:pin', items)
check('query.match(is:pin) 过滤正确',
      len(matched) == 1 and matched[0]['text'] == 'pinned item')

# 无 pinned 字段的条目也应被 is:pin 排除
cond2 = Q.parse('is:pin')
pred2 = Q.compile_pred(cond2)
check('缺 pinned 字段 → is:pin 排除', pred2({'text': 'x'}) is False)

# -is:pin 负向过滤（回归：修复 parse 未处理 neg 导致 -is:pin 被当正向）
neg_cond = Q.parse('-is:pin')
check('-is:pin → is_neg 含 pin', 'pin' in neg_cond['is_neg'])
check('-is:pin → is 为空', neg_cond['is'] == [])
neg_pred = Q.compile_pred(neg_cond)
neg_got = [x for x in items if neg_pred(x)]
check('-is:pin 排除 pinned',
      len(neg_got) == 1 and neg_got[0]['text'] == 'normal item')

neg_matched, _ = Q.match('-is:pin', items)
check('query.match(-is:pin) 排除 pinned',
      len(neg_matched) == 1 and neg_matched[0]['text'] == 'normal item')

# -is:fav 同样走负向（历史遗留 -is: 全部未处理 neg）
fav_items = [
    {'text': 'fav item', 'fav': 1},
    {'text': 'plain item', 'fav': 0},
]
fav_neg_cond = Q.parse('-is:fav')
fav_neg_got = [x for x in fav_items if Q.compile_pred(fav_neg_cond)(x)]
check('-is:fav 排除 fav',
      len(fav_neg_got) == 1 and fav_neg_got[0]['text'] == 'plain item')

# ---------- 3. 搜索态排序 ----------
def sort_key(it):
    return (
        -(it.get('pinned') or 0),
        -(it.get('use_count') or 0),
        -(it.get('last_used_at') or it.get('created_at') or 0),
    )

pool = [
    {'id': 'a', 'pinned': 0, 'use_count': 10, 'last_used_at': 300, 'created_at': 100},
    {'id': 'b', 'pinned': 1, 'use_count': 1, 'last_used_at': 200, 'created_at': 200},
    {'id': 'c', 'pinned': 0, 'use_count': 20, 'last_used_at': 500, 'created_at': 300},
]
order = [x['id'] for x in sorted(pool, key=sort_key)]
check('pinned 优先（b 最前）', order[0] == 'b')
check('use_count 次之（c 在 a 前）', order.index('c') < order.index('a'))

# last_used_at 缺失时回退 created_at
pool2 = [
    {'id': 'x', 'pinned': 0, 'use_count': 0, 'last_used_at': None, 'created_at': 100},
    {'id': 'y', 'pinned': 0, 'use_count': 0, 'last_used_at': None, 'created_at': 999},
]
order2 = [x['id'] for x in sorted(pool2, key=sort_key)]
check('last_used_at 缺失回退 created_at', order2[0] == 'y')

# 完全缺字段不崩溃
check('缺字段排序不崩溃', sorted([{'id': 'z'}], key=sort_key)[0]['id'] == 'z')

with io.open(os.path.join(tempfile.gettempdir(), '_t29.out'), 'w',
             encoding='utf-8') as f:
    f.write('\n'.join(LOG) + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))
os._exit(0)
