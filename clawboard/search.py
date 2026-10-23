# -*- coding: utf-8 -*-
"""
F3 · 高级搜索语法解析器（纯函数，无 UI 依赖，可单测）

支持：
  普通关键词（空格分隔，多词 AND）
  time:2026-10-01            当天
  time:>1h / time:<30m       相对时间（s/m/h/d/w）
  time:09:00-12:00           当天时段
  time:2026-09-01..2026-09-30  区间
  app:chrome                 来源应用（中文/模糊）
  type:text                  内容类型
  size:>1mb / size:<100      大小过滤
  is:fav / is:sens / is:url / is:est / is:pin  标记过滤
  -关键词 / -app:xxx / -is:pin  排除

解析结果 compile 成谓词函数（本项目是 JSON 内存列表，无 SQL 层，
因此编译为 Python 谓词；按需生成拼音并使用有界缓存，保持零依赖。
"""
from collections import OrderedDict
import re
from threading import RLock
import time

from clawboard.pinyin import to_pinyin, to_pinyin_initials, PINYIN, PINYIN_PHRASE
from clawboard.tag import normalize_tag

UNIT = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400, 'w': 604800}
SIZE_UNIT = {'b': 1, 'kb': 1024, 'k': 1024, 'mb': 1048576, 'm': 1048576,
             'gb': 1073741824, 'g': 1073741824}
KNOWN_TYPES = ('text', 'url', 'json', 'multiline', 'image', 'filelist', 'empty')
KNOWN_IS = ('fav', 'sens', 'url', 'est', 'pin')


def day_range(y, m, d):
    """返回 [当天 00:00:00, 次日 00:00:00) 的毫秒区间"""
    import datetime
    a = datetime.datetime(y, m, d)
    return (int(a.timestamp() * 1000), int((a + datetime.timedelta(days=1)).timestamp() * 1000))


def parse_date(s):
    m = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', s)
    if m:
        return day_range(*[int(x) for x in m.groups()])
    m = re.match(r'^(\d{1,2})-(\d{1,2})$', s)
    if m:
        n = time.localtime()
        return day_range(n.tm_year, int(m.group(1)), int(m.group(2)))
    return None


def parse_time_token(v, now_ms):
    """返回 (lo, hi) 毫秒区间或 None（无法解析）"""
    v = v.strip()
    if '..' in v:
        a, b = v.split('..', 1)
        ra, rb = parse_date(a), parse_date(b)
        if ra and rb:
            return (min(ra[0], rb[0]), max(ra[1], rb[1]))
        return None
    m = re.match(r'^([<>])(\d+)([smhdw])$', v)
    if m:
        op, n, u = m.group(1), int(m.group(2)), m.group(3)
        delta = n * UNIT[u] * 1000
        if op == '>':
            return (0, now_ms - delta)          # 早于 N 之前
        return (now_ms - delta, now_ms + 1000)  # N 之内
    m = re.match(r'^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$', v)
    if m:
        n = time.localtime(now_ms / 1000.0)
        import datetime
        h1, m1 = int(m.group(1)), int(m.group(2))
        h2, m2 = int(m.group(3)), int(m.group(4))
        # 起止完全相同的时段在语义上无意义（用户多半写错，或想表达"就那一分钟"）。
        # 不扩成 24h 全天（那会把整桶数据静默放行，方向相反地骗人），
        # 而是返回空区间（lo == hi，lo <= ts < hi 恒为假 = 命中 0 条），
        # 并通过第三元 err 让 parse() 把提示透传到搜索框（红框 + 文案）。
        if (h1, m1) == (h2, m2):
            t0 = datetime.datetime(n.tm_year, n.tm_mon, n.tm_mday)
            t0 += datetime.timedelta(hours=h1, minutes=m1)
            t0ms = int(t0.timestamp() * 1000)
            return (t0ms, t0ms, '起止时间相同，时段为空：' + v)
        base = datetime.datetime(n.tm_year, n.tm_mon, n.tm_mday)
        a = base + datetime.timedelta(hours=h1, minutes=m1)
        b = base + datetime.timedelta(hours=h2, minutes=m2)
        # ---- 时隙锚定规则（务必看清，两处调整的先后顺序有意义）----
        # 1) 跨午夜顺延：起时间晚于止时间（如 22:00-02:00）时把止时间 +1 天，
        #    得到 [今天22:00, 次日02:00)，否则 a > b 会让 lo <= ts < hi 恒为假、
        #    搜索静默返回 0 条 —— 用户以为那段时间没数据。用 b <= a（含相等），
        #    起止相同的分支已提前 return 拦截，故此处实际是 b < a。
        if b <= a:
            b += datetime.timedelta(days=1)
        # 2) 以 now 为锚（关键）：把整段窗口对齐到「起时刻 a 最近一次已经发生的时刻」，
        #    即保证 a <= now < a+24h。若 a 落在「未来」（a > now），说明用户是在
        #    该时隙的起点之前搜索（典型：凌晨 00:30 搜 22:00-02:00，想找昨晚复制的东西），
        #    此时整段窗口前移一天：
        #      · 22:00-02:00 → [昨天22:00, 今天02:00)，命中昨晚 23:00 / 今天 00:30；
        #      · 22:00-23:59（不跨界）→ [昨天22:00, 昨天23:59)，命中昨晚 23:00。
        #    理由：这是**历史记录**搜索，默认取向是「过去的、最近的那个窗口」。
        #    · 晚上 23:00 搜 22:00-02:00：a=今天22:00 <= now → 不前移，命中今天23:00；
        #    · 白天 12:00 搜 11:00-13:00：a=今天11:00 <= now → 不前移，命中今天12:00；
        #    · 凌晨 00:14 搜 11:00-13:00：a=今天11:00 > now → 前移到昨天 11:00-13:00
        #      （凌晨找的是「昨天那个白天窗口」，符合历史搜索的过去取向）。
        #    顺序：先顺延（让 a/b 成为合法递增区间），再看 now 决定是否前移。
        if int(a.timestamp() * 1000) > now_ms:
            a -= datetime.timedelta(days=1)
            b -= datetime.timedelta(days=1)
        return (int(a.timestamp() * 1000), int(b.timestamp() * 1000))
    return parse_date(v)


def parse_size_token(v):
    """'>1mb' / '<100' / '500' → (op, bytes)"""
    m = re.match(r'^([<>])?(\d+(?:\.\d+)?)(b|kb|k|mb|m|gb|g)?$', v.strip().lower())
    if not m:
        return None
    op = m.group(1) or '='
    n = float(m.group(2))
    u = SIZE_UNIT.get(m.group(3) or 'b', 1)
    return (op, int(n * u))


def parse(q):
    """把查询串解析成结构化条件。无法识别的 token 一律当普通关键词，绝不抛异常"""
    cond = {'terms': [], 'not_terms': [], 'time': [], 'app': [], 'not_app': [],
            'type': [], 'not_type': [], 'size': [], 'is': [], 'is_neg': [],
            'tag': [], 'not_tag': [], 'errors': []}
    for tok in (q or '').split():
        if not tok:
            continue
        neg = tok.startswith('-')
        body = tok[1:] if neg else tok
        low = body.lower()
        try:
            if low.startswith('time:'):
                r = parse_time_token(body[5:], int(time.time() * 1000))
                if r is None:
                    cond['errors'].append('无法识别的时间：' + body)
                    continue
                # parse_time_token 在软性写法问题（如起止相同）时返回三元组
                # (lo, hi, err)：区间照常入列（此时为空区间，命中 0 条），
                # 同时把提示透传给搜索框。
                if len(r) == 3:
                    cond['time'].append(((r[0], r[1]), neg))
                    cond['errors'].append(r[2])
                else:
                    cond['time'].append(((r[0], r[1]), neg))
            elif low.startswith('tag:'):
                v = normalize_tag(body[4:])
                if v:
                    (cond['not_tag'] if neg else cond['tag']).append(v)
                else:
                    cond['errors'].append('未知标签：' + body[4:])
            elif low.startswith('app:'):
                v = body[4:].strip()
                (cond['not_app'] if neg else cond['app']).append(v.lower())
            elif low.startswith('type:'):
                v = body[5:].strip().lower()
                if v in KNOWN_TYPES:
                    (cond['not_type'] if neg else cond['type']).append(v)
                else:
                    cond['errors'].append('未知类型：' + v)
            elif low.startswith('size:'):
                r = parse_size_token(body[5:])
                if r is None:
                    cond['errors'].append('无法识别的大小：' + body)
                else:
                    cond['size'].append((r, neg))
            elif low.startswith('is:'):
                v = body[3:].strip().lower()
                if v in KNOWN_IS:
                    (cond['is_neg'] if neg else cond['is']).append(v)
                else:
                    cond['errors'].append('未知标记：' + v)
            else:
                (cond['not_terms'] if neg else cond['terms']).append(body.lower())
        except Exception as e:
            cond['errors'].append('%s：%s' % (body, e))
    return cond


def _is_hit(f, it):
    """五种 is: 标记的统一命中判定（正向/负向共用）"""
    if f == 'fav':
        return bool(it.get('fav'))
    if f == 'sens':
        return bool(it.get('sens'))
    if f == 'est':
        return bool(it.get('is_estimated'))
    if f == 'url':
        return (it.get('content_type') or '') == 'url'
    if f == 'pin':
        return bool(it.get('pinned'))
    return False


# 表里的词组当前只含非 ASCII 字符，所以英文/数字不必逐字符查汉字表。
# 若将来词库加入「A股」等混合词组，自动回退整段转换，避免跨段边界改变读音。
_ASCII_SPLIT_SAFE = (not any(key.isascii() for key in PINYIN)
                     and not any(any(c.isascii() for c in key) for key in PINYIN_PHRASE))
_NON_ASCII_PARTS = re.compile(r'([^\x00-\x7f]+)')


def _derive_pinyin(text, get_pair):
    if not _ASCII_SPLIT_SAFE:
        full, initials = get_pair(text)
        return full + ' ' + initials
    parts = _NON_ASCII_PARTS.split(text)
    full_parts, initial_parts = [], []
    for i, part in enumerate(parts):
        full, initials = get_pair(part) if i % 2 else (part, part)
        full_parts.append(full)
        initial_parts.append(initials)
    return ''.join(full_parts) + ' ' + ''.join(initial_parts)


class _PinyinCache:
    """按非 ASCII 连续段缓存派生值，英文日志前后缀不占用拼音缓存。"""

    def __init__(self, max_entries=512, max_chars=2_000_000):
        self.max_entries = max(0, int(max_entries))
        self.max_chars = max(0, int(max_chars))
        self._lock = RLock()
        self.entries = OrderedDict()
        self.chars = 0

    def clear(self):
        with self._lock:
            self.entries.clear()
            self.chars = 0

    def _get_pair(self, text):
        cached = self.entries.get(text)
        if cached is not None:
            self.entries.move_to_end(text)
            return cached[0]
        pair = (to_pinyin(text), to_pinyin_initials(text))
        cost = len(text) + len(pair[0]) + len(pair[1])
        # 巨大条目仍正确搜索，但不让一次查询挤占整个常驻缓存。
        if self.max_entries and cost <= self.max_chars:
            while self.entries and (len(self.entries) >= self.max_entries
                                    or self.chars + cost > self.max_chars):
                _, (_, previous_cost) = self.entries.popitem(last=False)
                self.chars -= previous_cost
            self.entries[text] = (pair, cost)
            self.chars += cost
        return pair

    def get(self, text):
        with self._lock:
            return _derive_pinyin(text, self._get_pair)


def compile_pred(cond, cache=None):
    """编译成谓词：item(dict) -> bool；无文本条件时不做正文派生。"""
    terms = cond['terms']
    not_terms = cond['not_terms']
    times = cond['time']
    apps = cond['app']
    not_apps = cond['not_app']
    types = cond['type']
    not_types = cond['not_type']
    sizes = cond['size']
    isf = cond['is']
    is_neg = cond.get('is_neg', [])
    tags = cond.get('tag', [])
    not_tags = cond.get('not_tag', [])

    def pred(it):
        if tags or not_tags:
            ts = it.get('tags') or []
            if tags and not all(t in ts for t in tags):
                return False
            if not_tags and any(t in ts for t in not_tags):
                return False
        if apps or not_apps:
            app = (it.get('source_app') or 'unknown').lower()
            if apps and not any(a in app for a in apps):
                return False
            if not_apps and any(a in app for a in not_apps):
                return False
        if types or not_types:
            ct = str(it.get('content_type') or 'text').lower()
            if types and ct not in types:
                return False
            if not_types and ct in not_types:
                return False
        if sizes:
            sz = int(it.get('content_size') or 0)
            for (op, n), neg in sizes:
                hit = (sz > n) if op == '>' else ((sz < n) if op == '<' else (sz == n))
                if neg and hit:
                    return False
                if (not neg) and (not hit):
                    return False
        if times:
            ts = int(it.get('created_at') or 0)
            for (lo, hi), neg in times:
                hit = lo <= ts < hi
                if neg and hit:
                    return False
                if (not neg) and (not hit):
                    return False
        for f in isf:
            if not _is_hit(f, it):
                return False
        for f in is_neg:
            if _is_hit(f, it):
                return False
        if not terms and not not_terms:
            return True
        text = (it.get('text') or '').lower()
        name = (it.get('name') or '').lower()
        direct = text + ' ' + name
        if any(t in direct for t in not_terms):
            return False
        missing = [t for t in terms if t not in direct]
        # ASCII 没有可转换的汉字，拼音结果只会重复原文。
        if text.isascii():
            return not missing
        if not missing and not not_terms:
            return True
        derived = (cache.get(text) if cache is not None else
                   _derive_pinyin(text, lambda value: (to_pinyin(value),
                                                       to_pinyin_initials(value))))
        return (all(t in derived for t in missing)
                and not any(t in derived for t in not_terms))
    return pred


def _match(q, items, cache=None):
    cond = parse(q)
    if not any(cond[k] for k in ('terms', 'not_terms', 'time', 'app', 'not_app',
                                 'type', 'not_type', 'size', 'is', 'is_neg',
                                 'tag', 'not_tag')):
        return list(items), cond
    predicate = compile_pred(cond, cache)
    return [item for item in items if predicate(item)], cond


def match(q, items):
    """兼容入口；长生命周期界面应复用 SearchService 的有界缓存。"""
    return _match(q, items)


class SearchService:
    """与 UI、存储无关的搜索服务，一个窗口持有一个实例即可。"""

    def __init__(self, max_entries=512, max_chars=2_000_000):
        self._cache = _PinyinCache(max_entries, max_chars)

    def match(self, q, items):
        return _match(q, items, self._cache)

    def clear(self):
        self._cache.clear()

    @property
    def cache_size(self):
        return len(self._cache.entries)

    @property
    def cached_chars(self):
        return self._cache.chars


SYNTAX_HELP = [
    ('关键词', 'hello world（空格分隔 = 同时包含）'),
    ('-关键词', '排除包含该词的条目'),
    ('time:2026-10-01', '指定当天'),
    ('time:>1h', '1 小时之前（s/m/h/d/w）'),
    ('time:<30m', '最近 30 分钟内'),
    ('time:09:00-12:00', '今天这个时段'),
    ('time:2026-09-01..2026-09-30', '日期区间'),
    ('app:chrome', '来源应用（支持中文、模糊）'),
    ('type:url', '类型：text/url/json/multiline'),
    ('size:>1mb', '大小过滤（b/kb/mb/gb）'),
    ('is:fav', '收藏 / is:sens 敏感 / is:url 链接'),
    ('is:est', '时间为估算 / is:pin 固定置顶'),
    ('tag:email', '标签：邮箱/手机号/数字/日期/链接/代码/JSON/密码/Token'),
]
