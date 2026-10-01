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
  is:fav / is:sens / is:url  标记过滤
  -关键词 / -app:xxx         排除

解析结果 compile 成谓词函数（本项目是 JSON 内存列表，无 SQL 层，
因此编译为 Python 谓词 + 倒排索引，而非 SQL WHERE；同样可单测、同样防注入）。
"""
import re
import time

UNIT = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400, 'w': 604800}
SIZE_UNIT = {'b': 1, 'kb': 1024, 'k': 1024, 'mb': 1048576, 'm': 1048576,
             'gb': 1073741824, 'g': 1073741824}
KNOWN_TYPES = ('text', 'url', 'json', 'multiline', 'image', 'filelist', 'empty')
KNOWN_IS = ('fav', 'sens', 'url', 'est')


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
        base = datetime.datetime(n.tm_year, n.tm_mon, n.tm_mday)
        a = base + datetime.timedelta(hours=int(m.group(1)), minutes=int(m.group(2)))
        b = base + datetime.timedelta(hours=int(m.group(3)), minutes=int(m.group(4)))
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
            'type': [], 'not_type': [], 'size': [], 'is': [], 'errors': []}
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
                else:
                    cond['time'].append((r, neg))
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
                    cond['is'].append(v)
                else:
                    cond['errors'].append('未知标记：' + v)
            else:
                (cond['not_terms'] if neg else cond['terms']).append(body.lower())
        except Exception as e:
            cond['errors'].append('%s：%s' % (body, e))
    return cond


def compile_pred(cond):
    """编译成谓词：item(dict) -> bool"""
    terms = cond['terms']
    not_terms = cond['not_terms']
    times = cond['time']
    apps = cond['app']
    not_apps = cond['not_app']
    types = cond['type']
    not_types = cond['not_type']
    sizes = cond['size']
    isf = cond['is']

    def pred(it):
        text = (it.get('text') or '').lower()
        name = (it.get('name') or '').lower()
        hay = text + ' ' + name
        for t in terms:
            if t not in hay:
                return False
        for t in not_terms:
            if t in hay:
                return False
        if apps or not_apps:
            app = (it.get('source_app') or 'unknown').lower()
            if apps and not any(a in app for a in apps):
                return False
            if not_apps and any(a in app for a in not_apps):
                return False
        if types or not_types:
            ct = (it.get('content_type') or 'text').lower()
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
            if f == 'fav' and not it.get('fav'):
                return False
            if f == 'sens' and not it.get('sens'):
                return False
            if f == 'est' and not it.get('is_estimated'):
                return False
            if f == 'url' and (it.get('content_type') or '') != 'url':
                return False
        return True
    return pred


def match(q, items):
    """便利函数：直接过滤列表"""
    cond = parse(q)
    if not any(cond[k] for k in ('terms', 'not_terms', 'time', 'app', 'not_app',
                                 'type', 'not_type', 'size', 'is')):
        return list(items), cond
    p = compile_pred(cond)
    return [x for x in items if p(x)], cond


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
    ('is:fav', '收藏 / is:sens 敏感 / is:est 时间为估算'),
]
