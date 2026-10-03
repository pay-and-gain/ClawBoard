# -*- coding: utf-8 -*-
"""v2.2.x 自测：query 时隙解析跨午夜修复（time:22:00-02:00 等）。

用固定时间戳构造条目（当天某个整点），不依赖运行时刻，可稳定复现。
覆盖：
  - 跨午夜命中（午夜前 23:00 / 午夜后 01:00）
  - 跨午夜排除（12:00 不在区间）
  - 白天正常（回归）
  - 不跨界正常（回归）
"""
import io
import datetime
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import query as Q

OK = True
LOG = []


def check(name, cond, extra=''):
    global OK
    if not cond:
        OK = False
    LOG.append('%s  %s%s' % ('OK  ' if cond else 'FAIL', name,
                             ('  ' + extra) if extra else ''))


def ts_at(hour, minute=0, day_offset=0):
    """基准日（+day_offset 天）的 hour:minute 时间戳（毫秒）。

    只用整点时刻，与「现在几点」无关，因此不受运行时刻影响。
    day_offset 用于构造跨午夜区间的「午夜后」一侧：
    time:22:00-02:00 的窗口是 [今天 22:00, 次日 02:00)，
    所以 01:00 那一侧必须落在「次日」。
    """
    d = (datetime.datetime.now().replace(hour=hour, minute=minute,
                                         second=0, microsecond=0)
         + datetime.timedelta(days=day_offset))
    return int(d.timestamp() * 1000)


def item(text, ts):
    return {'text': text, 'name': '', 'source_app': 'chrome',
            'content_type': 'text', 'content_size': len(text.encode('utf-8')),
            'fav': 0, 'is_estimated': 0, 'sens': None, 'created_at': ts}


def hits(q, it):
    return len(Q.match(q, [it])[0])


# ---------- 1. 跨午夜主用例：22:00-02:00 ----------
# 窗口锚定为 [今天 22:00, 次日 02:00)，故午夜后一侧用 day_offset=1（次日 01:00）。
slot = 'time:22:00-02:00'
check('22:00-02:00 命中 23:00（午夜前）', hits(slot, item('a', ts_at(23, 0))) == 1,
      str(hits(slot, item('a', ts_at(23, 0)))))
check('22:00-02:00 命中 次日 01:00（午夜后）',
      hits(slot, item('b', ts_at(1, 0, day_offset=1))) == 1,
      str(hits(slot, item('b', ts_at(1, 0, day_offset=1)))))
check('22:00-02:00 不命中 12:00（区间外）', hits(slot, item('c', ts_at(12, 0))) == 0,
      str(hits(slot, item('c', ts_at(12, 0)))))
check('22:00-02:00 命中 22:00（左闭边界）', hits(slot, item('d', ts_at(22, 0))) == 1)
check('22:00-02:00 不命中 次日 02:00（右开边界）',
      hits(slot, item('e', ts_at(2, 0, day_offset=1))) == 0)

# ---------- 2. 回归：白天正常，不受修复影响 ----------
check('11:00-13:00 命中 12:00（白天回归）',
      hits('time:11:00-13:00', item('f', ts_at(12, 0))) == 1)
check('11:00-13:00 不命中 14:00（白天区间外）',
      hits('time:11:00-13:00', item('g', ts_at(14, 0))) == 0)

# ---------- 3. 回归：不跨界（22:00-23:59）仍正常，不该被误判成跨午夜 ----------
check('22:00-23:59 命中 23:00（不跨界回归）',
      hits('time:22:00-23:59', item('h', ts_at(23, 0))) == 1)
check('22:00-23:59 不命中 00:30（顺延一天不该被触发）',
      hits('time:22:00-23:59', item('i', ts_at(0, 30))) == 0)

# ---------- 4. 起止相同：09:00-09:00 → 顺延一天 = 跨整天 24h 区间（见 query.py 注释）----------
check('09:00-09:00 命中 10:00（24h 区间语义）',
      hits('time:09:00-09:00', item('j', ts_at(10, 0))) == 1)
check('09:00-09:00 命中 次日 03:00（24h 区间语义，午夜另一侧）',
      hits('time:09:00-09:00', item('k', ts_at(3, 0, day_offset=1))) == 1)

# ---------- 5. 负向：-time:22:00-02:00 排除跨午夜区间 ----------
r, _ = Q.match('-time:22:00-02:00', [item('late', ts_at(23, 0)),
                                     item('noon', ts_at(12, 0))])
check('负向 -time:22:00-02:00 排除 23:00、保留 12:00',
      len(r) == 1 and r[0]['text'] == 'noon',
      str([x['text'] for x in r]))

with io.open(os.path.join(tempfile.gettempdir(), '_t36.out'), 'w',
             encoding='utf-8') as f:
    f.write('\n'.join(LOG) + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))
os._exit(0)
