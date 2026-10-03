# -*- coding: utf-8 -*-
"""v2.2.x 自测：query 时隙解析（跨午夜 + 以 now 为锚 + 起止相同空集）。

关键：所有用例都用**固定的基准日整点时间戳**，并通过直接调用
parse_time_token(v, now_ms) 显式传入 now，从而完全控制「锚点」，
不依赖运行时刻，可稳定复现（无论几点跑结果都一样）。

覆盖：
  A. 夜间视角（now=23:00）的跨午夜命中/排除
  B. 凌晨视角（now=00:30）以 now 为锚：命中昨晚（关键新用例）
  C. 白天不受影响 + 凌晨搜白天时段的过去取向
  D. 不跨界 22:00-23:59 在凌晨的行为
  E. 起止相同 → 空集（不再是 24h）+ parse() errors 提示
  F. 负向谓词（-time:）在固定 now 下的整链路
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


# 固定基准日：取运行日的日期，但所有时刻都用整点，故与「现在几点」无关。
_BASE = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)


def at(hour, minute=0, day_offset=0):
    """基准日（+day_offset 天）hour:minute 的时间戳（毫秒）"""
    d = _BASE + datetime.timedelta(days=day_offset, hours=hour, minutes=minute)
    return int(d.timestamp() * 1000)


def item(text, ts):
    return {'text': text, 'name': '', 'source_app': 'chrome',
            'content_type': 'text', 'content_size': len(text.encode('utf-8')),
            'fav': 0, 'is_estimated': 0, 'sens': None, 'created_at': ts}


def hit_at(q, ts, now_ms):
    """在指定 now 下，判断 ts 是否命中 q 的时隙（复刻 compile_pred 的 lo<=ts<hi）"""
    r = Q.parse_time_token(q, now_ms)
    if r is None:
        return False
    lo, hi = r[0], r[1]
    return lo <= ts < hi


# ================= A. 夜间视角（now = 今天 23:00）=================
NOW_EVE = at(23, 0)
check('A1 22:00-02:00 @now23:00 命中今天23:00',
      hit_at('22:00-02:00', at(23, 0), NOW_EVE) is True)
check('A2 22:00-02:00 @now23:00 不命中今天12:00',
      hit_at('22:00-02:00', at(12, 0), NOW_EVE) is False)
check('A3 22:00-02:00 @now23:00 左闭：命中今天22:00',
      hit_at('22:00-02:00', at(22, 0), NOW_EVE) is True)
check('A4 22:00-02:00 @now23:00 右开：不命中次日02:00',
      hit_at('22:00-02:00', at(2, 0, day_offset=1), NOW_EVE) is False)
check('A5 22:00-02:00 @now23:00 命中次日01:00（窗口后半段）',
      hit_at('22:00-02:00', at(1, 0, day_offset=1), NOW_EVE) is True)

# ================= B. 凌晨视角（now = 今天 00:30）—— 关键新用例 =================
NOW_DAWN = at(0, 30)
check('B1 22:00-02:00 @now00:30 命中昨天23:00（核心修复）',
      hit_at('22:00-02:00', at(23, 0, day_offset=-1), NOW_DAWN) is True,
      'lo/hi=%s' % str(Q.parse_time_token('22:00-02:00', NOW_DAWN)))
check('B2 22:00-02:00 @now00:30 命中今天00:30（窗口内）',
      hit_at('22:00-02:00', at(0, 30), NOW_DAWN) is True)
check('B3 22:00-02:00 @now00:30 命中昨天22:00（左闭）',
      hit_at('22:00-02:00', at(22, 0, day_offset=-1), NOW_DAWN) is True)
check('B4 22:00-02:00 @now00:30 不命中今天02:00（右开）',
      hit_at('22:00-02:00', at(2, 0), NOW_DAWN) is False)
check('B5 22:00-02:00 @now00:30 不命中昨天12:00（区间外）',
      hit_at('22:00-02:00', at(12, 0, day_offset=-1), NOW_DAWN) is False)

# ================= C. 白天视角（now = 今天 12:00）不受影响 =================
NOW_DAY = at(12, 0)
check('C1 11:00-13:00 @now12:00 命中今天12:00',
      hit_at('11:00-13:00', at(12, 0), NOW_DAY) is True)
check('C2 11:00-13:00 @now12:00 不命中今天14:00',
      hit_at('11:00-13:00', at(14, 0), NOW_DAY) is False)
check('C3 11:00-13:00 @now12:00 不前移：不命中昨天12:00',
      hit_at('11:00-13:00', at(12, 0, day_offset=-1), NOW_DAY) is False)
# C4：历史搜索的过去取向 —— 凌晨搜白天时段，锚点回退到「昨天那一段」
check('C4 11:00-13:00 @now00:30 前移命中昨天11:00-13:00（历史过去取向）',
      hit_at('11:00-13:00', at(12, 0, day_offset=-1), NOW_DAWN) is True)
check('C5 11:00-13:00 @now00:30 不命中今天12:00（尚未发生）',
      hit_at('11:00-13:00', at(12, 0), NOW_DAWN) is False)

# ================= D. 不跨界 22:00-23:59 在凌晨的行为 =================
check('D1 22:00-23:59 @now00:30 前移命中昨天23:00',
      hit_at('22:00-23:59', at(23, 0, day_offset=-1), NOW_DAWN) is True)
check('D2 22:00-23:59 @now00:30 不命中今天23:00（已在未来）',
      hit_at('22:00-23:59', at(23, 0), NOW_DAWN) is False)
check('D3 22:00-23:59 @now23:00 命中今天23:00（晚上不前移）',
      hit_at('22:00-23:59', at(23, 0), NOW_EVE) is True)

# ================= E. 起止相同 → 空集（不再是 24h）=================
# 直接对区间断言：lo >= hi（lo<=ts<hi 恒为假）
r = Q.parse_time_token('09:00-09:00', NOW_DAY)
check('E1 09:00-09:00 返回空区间（lo >= hi）',
      r is not None and r[0] >= r[1], 'r=%s' % str(r))
check('E2 09:00-09:00 带 err 提示（三元组）', len(r) == 3, 'r=%s' % str(r))
check('E3 09:00-09:00 不命中今天10:00（不再 24h）',
      hit_at('09:00-09:00', at(10, 0), NOW_DAY) is False)
check('E4 09:00-09:00 不命中次日03:00（不再 24h）',
      hit_at('09:00-09:00', at(3, 0, day_offset=1), NOW_DAY) is False)
r2 = Q.parse_time_token('00:00-00:00', NOW_DAY)
check('E5 00:00-00:00 亦为空区间', r2 is not None and r2[0] >= r2[1], 'r=%s' % str(r2))
# parse() 层把该提示写进 errors（搜索框据此变红提示）
c = Q.parse('time:09:00-09:00')
check('E6 parse() 收集到起止相同的 errors 提示',
      any('相同' in e for e in c['errors']), str(c['errors']))
# 常规合法时隙不应产生 errors
c2 = Q.parse('time:22:00-02:00')
check('E7 parse() 常规时隙无 errors', c2['errors'] == [], str(c2['errors']))

# ================= F. 负向谓词 =================
# 用固定 now 走完整 parse+compile：构造昨晚 23:00 条目，-time:22:00-02:00 时
# 该时段整体前移命中，故应被排除。
import query as _Q  # noqa: E402


def match_at(q, items, now_ms):
    """在固定 now 下走完整 match（临时替换 time.time 以确保锚点可控）"""
    import time as _t
    orig = _t.time
    _t.time = lambda: now_ms / 1000.0
    try:
        return _Q.match(q, items)[0]
    finally:
        _t.time = orig


now = NOW_DAWN
items = [item('昨晚23点', at(23, 0, day_offset=-1)),
         item('今天中午', at(12, 0)),
         item('今天00:30', at(0, 30))]
pos = [x['text'] for x in match_at('time:22:00-02:00', items, now)]
check('F1 @now00:30 正向命中「昨晚23点」「今天00:30」',
      set(pos) == {'昨晚23点', '今天00:30'}, str(pos))
neg = [x['text'] for x in match_at('-time:22:00-02:00', items, now)]
check('F2 @now00:30 负向排除窗口内、保留「今天中午」',
      neg == ['今天中午'], str(neg))

with io.open(os.path.join(tempfile.gettempdir(), '_t36.out'), 'w',
             encoding='utf-8') as f:
    f.write('\n'.join(LOG) + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))
os._exit(0)
