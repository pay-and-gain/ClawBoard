# -*- coding: utf-8 -*-
"""QA(Edward) 独立验证 · 跨午夜时隙「以 now 为锚」语义（v2）。

!!! 本脚本由 QA 独立编写，刻意不复用工程师的 tests/_t36.py 构造方式 !!!

背景：工程师按 team-lead 指令把时隙语义从「锚定今天」改为「以 now 为锚」——
构造 [a,b) 后，若起点 a 在未来（a > now）则整段窗口前移一天，使 a <= now < a+24h。
起止相同不再扩成 24h，而是返回空区间 + 第三元 err（透传到 cond['errors']）。

为消除 flaky，本脚本**一律显式传入固定 now**：
  - 直接测 parse_time_token(v, NOW_MS) 的区间；
  - match() 级用例用 monkeypatch 把 query.time.time 钉死到固定 now。
两套 now：夜间 23:00（window 不过夜，a<=now 不前移）、凌晨 00:30（跨午夜窗口前移一天）。
每个断言都显式标注"当前用哪套 now"，不依赖真实运行时刻。

输出：stdout + 写 %TEMP%/__qa4.out；os._exit(0)。
"""
import datetime
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import query as Q   # noqa: E402

LOG = []
FAILS = []


def rec(name, ok, detail=''):
    LOG.append('%s  %-60s %s' % ('OK  ' if ok else 'FAIL', name, detail))
    if not ok:
        FAILS.append(name)


def item(text, ts):
    return {'text': text, 'name': '', 'source_app': 'chrome', 'content_type': 'text',
            'content_size': len(text.encode('utf-8')), 'fav': 0,
            'is_estimated': 0, 'sens': None, 'created_at': ts}


# ---- 固定基准日（本地日期），显式拼时刻，秒级精度 ----
TODAY = datetime.datetime.now()
D0 = datetime.datetime(TODAY.year, TODAY.month, TODAY.day, 0, 0, 0)   # 今天 00:00:00


def ms_of(day_off, hh, mm, ss=0):
    """基准日 + day_off 天 的 hh:mm:ss 的毫秒时间戳（绝对，不随运行时刻变）"""
    return int((D0 + datetime.timedelta(days=day_off, hours=hh, minutes=mm,
                                        seconds=ss)).timestamp() * 1000)


# 两套「固定 now」
NOW_NIGHT = ms_of(0, 23, 0, 0)    # 今晚 23:00（用于"当天窗口"用例）
NOW_DAWN = ms_of(0, 0, 30, 0)     # 今天凌晨 00:30（用于"跨午夜前移"用例）


class fixed_now(object):
    """with fixed_now(ms): 期间 query.time.time 返回 ms/1000。"""
    def __init__(self, ms):
        self.ms = ms
        self._saved = None

    def __enter__(self):
        self._saved = Q.time.time
        Q.time.time = lambda: self.ms / 1000.0
        return self

    def __exit__(self, *a):
        Q.time.time = self._saved


def rng(v, now_ms):
    """返回 (lo, hi)；三元组取前两位。"""
    r = Q.parse_time_token(v, now_ms)
    return (r[0], r[1])


def hits_with_now(q, now_ms, *items):
    with fixed_now(now_ms):
        return len(Q.match(q, list(items))[0])


# ============================================================
LOG.append('== 基准：今天=%s  tz偏移=%s s  now_night=%s  now_dawn=%s =='
           % (D0.strftime('%Y-%m-%d'), -__import__('time').timezone,
              D0.replace(hour=23).strftime('%m-%d %H:%M'),
              (D0 + datetime.timedelta(hours=0, minutes=30)).strftime('%m-%d %H:%M')))

# ---------------- A. parse_time_token 区间结构（显式 now） ----------------
# A1 跨午夜，now=23:00（夜间，a<=now 不前移）
lo, hi = rng('22:00-02:00', NOW_NIGHT)
rec('A1 [now=23:00] 22:00-02:00 = [今天22:00,次日02:00)',
    lo == ms_of(0, 22, 0) and hi == ms_of(1, 2, 0),
    'lo=%s hi=%s' % (datetime.datetime.fromtimestamp(lo / 1000).strftime('%m-%d %H:%M'),
                     datetime.datetime.fromtimestamp(hi / 1000).strftime('%m-%d %H:%M')))

# A1b 跨午夜，now=00:30（凌晨，a>now → 前移一天）
lo, hi = rng('22:00-02:00', NOW_DAWN)
rec('A1b[now=00:30] 22:00-02:00 = [昨天22:00,今天02:00)',
    lo == ms_of(-1, 22, 0) and hi == ms_of(0, 2, 0),
    'lo=%s hi=%s' % (datetime.datetime.fromtimestamp(lo / 1000).strftime('%m-%d %H:%M'),
                     datetime.datetime.fromtimestamp(hi / 1000).strftime('%m-%d %H:%M')))

# A2 白天非跨界，now=23:00 → a<=now 不前移，仍是今天
lo, hi = rng('11:00-13:00', NOW_NIGHT)
rec('A2 [now=23:00] 11:00-13:00 = [今天11:00,今天13:00)',
    lo == ms_of(0, 11, 0) and hi == ms_of(0, 13, 0))

# A2b 白天非跨界，now=00:30 → a=今天11:00 > now → 前移到昨天
lo, hi = rng('11:00-13:00', NOW_DAWN)
rec('A2b[now=00:30] 11:00-13:00 = [昨天11:00,昨天13:00)',
    lo == ms_of(-1, 11, 0) and hi == ms_of(-1, 13, 0))

# A3 不跨界晚场 22:00-23:59，now=00:30 → a=今天22:00 > now → 前移到昨天
lo, hi = rng('22:00-23:59', NOW_DAWN)
rec('A3 [now=00:30] 22:00-23:59 = [昨天22:00,昨天23:59)',
    lo == ms_of(-1, 22, 0) and hi == ms_of(-1, 23, 59))

# A4 刁钻跨界 23:59-00:00，now=23:00 → a=今天23:59 > now(23:00) → 前移一天
lo, hi = rng('23:59-00:00', NOW_NIGHT)
rec('A4a[now=23:00] 23:59-00:00 前移=[昨天23:59,今天00:00)',
    lo == ms_of(-1, 23, 59) and hi == ms_of(0, 0, 0))
# 同一条 now=00:30 → a=今天23:59 > now → 前移=[昨天23:59,今天00:00)
lo, hi = rng('23:59-00:00', NOW_DAWN)
rec('A4b[now=00:30] 23:59-00:00 = [昨天23:59,今天00:00)',
    lo == ms_of(-1, 23, 59) and hi == ms_of(0, 0, 0))

# A5 起止相同 → 空区间 + 三元组 err（不再 24h）
r5 = Q.parse_time_token('09:00-09:00', NOW_NIGHT)
rec('A5 09:00-09:00 返回三元组', isinstance(r5, tuple) and len(r5) == 3, str(r5))
if isinstance(r5, tuple) and len(r5) == 3:
    rec('A5 09:00-09:00 为空区间(lo==hi)', r5[0] == r5[1])
    rec('A5 09:00-09:00 err 文案非空', bool(r5[2]) and '09:00-09:00' in r5[2],
        repr(r5[2]))
rec('A5 09:00-09:00 命中 0 条（空区间）',
    hits_with_now('time:09:00-09:00', NOW_NIGHT, item('x', ms_of(0, 10, 0))) == 0)

# ============================================================
# ---------------- B. match() 级命中/排除（显式 now） ----------------
slot = 'time:22:00-02:00'

# B1 now=23:00：窗口=[今天22:00,次日02:00)
rec('B1 [now=23:00] 命中今天23:00', hits_with_now(slot, NOW_NIGHT, item('a', ms_of(0, 23, 0))) == 1)
rec('B1 [now=23:00] 命中次日01:00', hits_with_now(slot, NOW_NIGHT, item('b', ms_of(1, 1, 0))) == 1)
rec('B1 [now=23:00] 不命中今天12:00', hits_with_now(slot, NOW_NIGHT, item('c', ms_of(0, 12, 0))) == 0)
rec('B1 [now=23:00] 不命中次日02:00(右开)', hits_with_now(slot, NOW_NIGHT, item('d', ms_of(1, 2, 0))) == 0)
rec('B1 [now=23:00] 命中今天22:00(左闭)', hits_with_now(slot, NOW_NIGHT, item('e', ms_of(0, 22, 0))) == 1)
rec('B1 [now=23:00] 不命中今天21:59', hits_with_now(slot, NOW_NIGHT, item('f', ms_of(0, 21, 59))) == 0)

# B2 now=00:30：窗口=[昨天22:00,今天02:00) —— 本次修复的核心目标
rec('B2 [now=00:30] 命中昨天23:00（核心修复目标）',
    hits_with_now(slot, NOW_DAWN, item('g', ms_of(-1, 23, 0))) == 1)
rec('B2 [now=00:30] 命中今天00:30',
    hits_with_now(slot, NOW_DAWN, item('h', ms_of(0, 0, 30))) == 1)
rec('B2 [now=00:30] 命中今天01:59',
    hits_with_now(slot, NOW_DAWN, item('i', ms_of(0, 1, 59))) == 1)
rec('B2 [now=00:30] 不命中今天02:00(右开)',
    hits_with_now(slot, NOW_DAWN, item('j', ms_of(0, 2, 0))) == 0)
rec('B2 [now=00:30] 不命中昨天21:59(左开)',
    hits_with_now(slot, NOW_DAWN, item('k', ms_of(-1, 21, 59))) == 0)
rec('B2 [now=00:30] 不命中今天12:00',
    hits_with_now(slot, NOW_DAWN, item('l', ms_of(0, 12, 0))) == 0)

# B3 负向排除（显式 now=23:00）
with fixed_now(NOW_NIGHT):
    r, _ = Q.match('-time:22:00-02:00', [item('late', ms_of(0, 23, 0)),
                                         item('noon', ms_of(0, 12, 0))])
rec('B3 [now=23:00] -time:22:00-02:00 排除23:00 保留12:00',
    len(r) == 1 and r[0]['text'] == 'noon', str([x['text'] for x in r]))

# B4 组合 AND（显式 now=00:30，凌晨场景）
combo = [item('report 23', ms_of(-1, 23, 0)), item('report 12', ms_of(0, 12, 0)),
         item('memo 23', ms_of(-1, 23, 0))]
rec('B4 [now=00:30] "time:22:00-02:00 report" 命中昨晚report',
    hits_with_now('time:22:00-02:00 report', NOW_DAWN, *combo) == 1)

# B5 左闭右开秒级（显式 now=23:00）
rec('B5 [now=23:00] 22:00:00 命中(左闭)', hits_with_now(slot, NOW_NIGHT, item('m', ms_of(0, 22, 0, 0))) == 1)
rec('B5 [now=23:00] 21:59:59 不命中', hits_with_now(slot, NOW_NIGHT, item('n', ms_of(0, 21, 59, 59))) == 0)

# ============================================================
# ---------------- C. 回归：其他 time: 分支 + err 透传 ----------------
lo, hi = rng('>1h', NOW_NIGHT)
rec('C time:>1h = (0, now-1h)', lo == 0 and hi == NOW_NIGHT - 3600 * 1000)
lo, hi = rng('<30m', NOW_NIGHT)
rec('C time:<30m = (now-30m, now+1s)', lo == NOW_NIGHT - 1800 * 1000 and hi == NOW_NIGHT + 1000)
lo, hi = rng('2026-10-01', NOW_NIGHT)
d = datetime.datetime(2026, 10, 1)
rec('C time:2026-10-01 当天区间',
    lo == int(d.timestamp() * 1000) and hi == int((d + datetime.timedelta(days=1)).timestamp() * 1000))
lo, hi = rng('2026-09-01..2026-09-30', NOW_NIGHT)
da, db = datetime.datetime(2026, 9, 1), datetime.datetime(2026, 9, 30)
rec('C time:区间',
    lo == int(da.timestamp() * 1000) and hi == int((db + datetime.timedelta(days=1)).timestamp() * 1000))
rec('C 无法识别返回 None', Q.parse_time_token('notatime', NOW_NIGHT) is None)

# err 透传到 cond['errors']
with fixed_now(NOW_NIGHT):
    _, cond = Q.match('time:09:00-09:00', [item('x', ms_of(0, 10, 0))])
rec('C 起止相同 err 透传到 cond["errors"]',
    any('09:00-09:00' in e for e in cond['errors']), str(cond['errors']))

# ============================================================
# ---------------- D. 独立质疑：锚定规则的边界是否自洽 ----------------
# D1 边界恰好在 a（a == now）：应"不前移"（条件是 a > now 才前移）
lo, hi = rng('22:00-02:00', ms_of(0, 22, 0, 0))   # now 恰=今天22:00
rec('D1 now 恰=今天22:00 不前移（[今天22:00,次日02:00)）',
    lo == ms_of(0, 22, 0) and hi == ms_of(1, 2, 0),
    'lo=%s' % datetime.datetime.fromtimestamp(lo / 1000).strftime('%m-%d %H:%M'))
# D2 now = 今天21:59:59 → a=22:00 > now → 前移
lo, hi = rng('22:00-02:00', ms_of(0, 21, 59, 59))
rec('D2 now=今天21:59:59 前移（[昨天22:00,今天02:00)）',
    lo == ms_of(-1, 22, 0) and hi == ms_of(0, 2, 0))
# D3 now 略超窗口右端（今天03:00 搜 22:00-02:00）：a=今天22:00 > now → 前移
#     → [昨天22:00,今天02:00)，但 now=03:00 已在右端之后 → 搜"过去的最近窗口"是对的
lo, hi = rng('22:00-02:00', ms_of(0, 3, 0))
rec('D3 now=今天03:00 前移=[昨天22:00,今天02:00)（不含now，合理）',
    lo == ms_of(-1, 22, 0) and hi == ms_of(0, 2, 0))

# ---------------- 输出 ----------------
out = '\n'.join(LOG) + '\n\n' + ('全部通过\n' if not FAILS else '有失败项：%s\n' % FAILS)
print(out)
with io.open(os.path.join(tempfile.gettempdir(), '__qa4.out'), 'w', encoding='utf-8') as f:
    f.write(out)
sys.stdout.flush()
os._exit(0)
