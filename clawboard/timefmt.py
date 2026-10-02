# -*- coding: utf-8 -*-
"""时间格式化 + 来源忽略规则 + 数据迁移（migrate/backup_data）。

纯函数层，无 tkinter / ctypes 依赖。migrate 1→2→3 步骤逐字保留，保证老数据兼容。
"""
import os
import re
import time
import fnmatch

from clawboard.config import DATA_FILE
from clawboard.classify import byte_size, detect_content_type


def now_ms():
    return int(time.time() * 1000)


def rel_time(ms, estimated=False):
    """相对时间文案：<1min 刚刚 / <60min N 分钟前 / 今天 HH:MM / 昨天 / 更早"""
    if not ms:
        return '未知时间'
    pre = '约 ' if estimated else ''
    now = now_ms()
    if ms > now + 60000:
        return pre + '时间异常'
    diff = (now - ms) / 1000.0
    if diff < 60:
        return pre + '刚刚'
    if diff < 3600:
        return pre + '%d 分钟前' % int(diff / 60)
    lt = time.localtime(ms / 1000.0)
    n = time.localtime()
    if lt.tm_year == n.tm_year and lt.tm_yday == n.tm_yday:
        return pre + time.strftime('%H:%M', lt)
    if (n.tm_yday - lt.tm_yday) == 1 and lt.tm_year == n.tm_year:
        return pre + '昨天 ' + time.strftime('%H:%M', lt)
    return pre + time.strftime('%m-%d %H:%M', lt)


def full_time(ms):
    if not ms:
        return '—'
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ms / 1000.0))


def parse_ignore_list(raw):
    """把忽略名单文本拆成通配模式列表。
    没写通配符的按「包含」处理（keepass → *keepass*），对齐 Ditto
    ClipboardViewer.cpp:345 的 WildMatch 语义，但 * / ? 交给 fnmatch，不自己造轮子。"""
    out = []
    for p in re.split(r'[,;\n、\r]', raw or ''):
        p = p.strip().lower()
        if not p:
            continue
        if not any(ch in p for ch in '*?'):
            p = '*' + p + '*'
        out.append(p)
    return out


def match_ignore(app_name, title, apps_raw, titles_raw):
    """命中忽略规则则返回规则描述，否则 None。
    应用名按通配匹配、窗口标题按正则匹配（对齐 CopyQ predefinedcommands.cpp:151 ——
    预设的「忽略标题含 Password 的窗口」就是这么一条 wndre 正则）。"""
    name = (app_name or '').lower()
    for pat in parse_ignore_list(apps_raw):
        if fnmatch.fnmatch(name, pat):
            return '应用 %s' % (pat.strip('*') or pat)
    t = title or ''
    for pat in re.split(r'[\n;\r]', titles_raw or ''):
        pat = pat.strip()
        if not pat:
            continue
        try:
            if re.search(pat, t, re.I):
                return '标题 /%s/' % pat
        except re.error:
            if pat.lower() in t.lower():
                return '标题 %s' % pat
    return None


def backup_data():
    """迁移前备份，返回备份路径（失败返回 None）"""
    if not os.path.exists(DATA_FILE):
        return None
    bak = DATA_FILE + '.bak'
    try:
        with open(DATA_FILE, 'rb') as a:
            with open(bak, 'wb') as b:
                b.write(a.read())
        return bak
    except Exception:
        return None


def migrate(d, note=None):
    """版本化迁移：1 → 2 → 3，幂等可重复执行"""
    v = d.get('schema_version', 1)
    if not isinstance(v, int):
        v = 1

    def pools():
        out = []
        if isinstance(d.get('clip'), list):
            out.append(d['clip'])
        for g in d.get('groups') or []:
            if isinstance(g, dict) and isinstance(g.get('items'), list):
                out.append(g['items'])
        return out

    if v < 2:
        # v1 → v2：补 created_at / seq，老数据没有真实时间戳，按倒序估算并标记
        seq = 0
        for pool in pools():
            for it in pool:
                if not isinstance(it, dict):
                    continue
                seq += 1
                if not it.get('created_at'):
                    it['created_at'] = now_ms() - seq * 1000
                    it.setdefault('is_estimated', 1)   # 老数据无时间戳 → 标记为估算
                it.setdefault('seq', seq)
        v = 2
    if v < 3:
        # v2 → v3：补 F0/F1/F2 全部字段
        for pool in pools():
            for it in pool:
                if not isinstance(it, dict):
                    continue
                it.setdefault('updated_at', it.get('created_at'))
                it.setdefault('last_used_at', None)
                it.setdefault('source_app', 'unknown')
                it.setdefault('source_title', None)
                it.setdefault('copy_count', 1)
                it.setdefault('fav', 0)
                it.setdefault('meta', None)
                if not it.get('content_type'):
                    it['content_type'] = detect_content_type(it.get('text', ''))
                if not it.get('content_size'):
                    it['content_size'] = byte_size(it.get('text', ''))
        v = 3
    d['schema_version'] = v
    return d
