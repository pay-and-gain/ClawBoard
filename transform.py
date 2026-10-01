# -*- coding: utf-8 -*-
"""
F4 · 文本变换工具（纯函数集合，无 UI 依赖，全部可单测）

每个函数：str -> str，非法输入抛 ValueError（带明确原因），绝不静默返回空。
"""
import re
import json
import base64
import hashlib
import urllib.parse
import html as _html

URL_RE = re.compile(r'https?://[^\s<>"\'）)】\]]+', re.I)
NUM_RE = re.compile(r'-?\d+(?:\.\d+)?')


# ---------- 基础清洗 ----------
def strip_html(s):
    s = re.sub(r'<\s*br\s*/?\s*>', '\n', s or '', flags=re.I)
    s = re.sub(r'</\s*(p|div|li|tr|h[1-6])\s*>', '\n', s, flags=re.I)
    s = re.sub(r'</\s*t[dh]\s*>', '\t', s, flags=re.I)
    s = re.sub(r'<[^>]+>', '', s)
    return _html.unescape(s).replace('\xa0', ' ')


def t_deformat(s):
    out = strip_html(s)
    out = '\n'.join(x.rstrip() for x in out.split('\n'))
    return out.strip('\n')


def t_drop_blank_lines(s):
    return '\n'.join(x for x in (s or '').split('\n') if x.strip())


def t_trim_lines(s):
    return '\n'.join(x.strip() for x in (s or '').split('\n'))


def t_trim(s):
    return (s or '').strip()


# ---------- 全角半角 ----------
def to_halfwidth(s):
    out = []
    for ch in s or '':
        c = ord(ch)
        if c == 0x3000:
            out.append(' ')
        elif 0xFF01 <= c <= 0xFF5E:
            out.append(chr(c - 0xFEE0))
        else:
            out.append(ch)
    return ''.join(out)


def to_fullwidth(s):
    out = []
    for ch in s or '':
        c = ord(ch)
        if c == 0x20:
            out.append(chr(0x3000))
        elif 0x21 <= c <= 0x7E:
            out.append(chr(c + 0xFEE0))
        else:
            out.append(ch)
    return ''.join(out)


# ---------- 大小写 / 命名 ----------
def t_upper(s):
    return (s or '').upper()


def t_lower(s):
    return (s or '').lower()


def t_capitalize(s):
    return ' '.join(w[:1].upper() + w[1:].lower() for w in (s or '').split())


def to_camel(s):
    parts = [p for p in re.split(r'[^0-9a-zA-Z\u4e00-\u9fa5]+', s or '') if p]
    if not parts:
        return ''
    return parts[0].lower() + ''.join(p[:1].upper() + p[1:] for p in parts[1:])


def to_pascal(s):
    parts = [p for p in re.split(r'[^0-9a-zA-Z\u4e00-\u9fa5]+', s or '') if p]
    return ''.join(p[:1].upper() + p[1:] for p in parts)


def to_snake(s):
    s = (s or '').strip()
    s = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s)
    return re.sub(r'[^0-9a-zA-Z]+', '_', s).strip('_').lower()


def to_kebab(s):
    return to_snake(s).replace('_', '-')


# ---------- 结构化 ----------
def t_json_format(s):
    try:
        obj = json.loads(s)
    except Exception as e:
        raise ValueError('不是合法 JSON：%s' % e)
    return json.dumps(obj, ensure_ascii=False, indent=2)


def t_json_minify(s):
    try:
        obj = json.loads(s)
    except Exception as e:
        raise ValueError('不是合法 JSON：%s' % e)
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':'))


# ---------- 编码 ----------
def t_b64enc(s):
    return base64.b64encode((s or '').encode('utf-8')).decode('ascii')


def t_b64dec(s):
    try:
        return base64.b64decode((s or '').strip(), validate=True).decode('utf-8')
    except Exception as e:
        raise ValueError('Base64 解码失败：%s' % e)


def t_urlenc(s):
    return urllib.parse.quote((s or ''), safe='')


def t_urldec(s):
    return urllib.parse.unquote((s or ''))


# ---------- 摘要 ----------
def t_md5(s):
    return hashlib.md5((s or '').encode('utf-8')).hexdigest()


def t_sha1(s):
    return hashlib.sha1((s or '').encode('utf-8')).hexdigest()


def t_sha256(s):
    return hashlib.sha256((s or '').encode('utf-8')).hexdigest()


# ---------- 提取 ----------
def t_extract_url(s):
    out = URL_RE.findall(s or '')
    if not out:
        raise ValueError('没有找到任何 URL')
    return '\n'.join(out)


def t_extract_num(s):
    out = NUM_RE.findall(s or '')
    if not out:
        raise ValueError('没有找到任何数字')
    return '\n'.join(out)


# ---------- 行操作 ----------
def t_sort_lines(s):
    return '\n'.join(sorted((s or '').split('\n')))


def t_uniq_lines(s):
    seen = set()
    out = []
    for x in (s or '').split('\n'):
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return '\n'.join(out)


def t_md_to_text(s):
    s = s or ''
    s = re.sub(r'```[\s\S]*?```', lambda m: m.group(0).strip('`'), s)
    s = re.sub(r'^\s{0,3}#{1,6}\s*', '', s, flags=re.M)
    s = re.sub(r'!\[([^\]]*)\]\([^)]*\)', r'\1', s)
    s = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', s)
    s = re.sub(r'[*_`~]{1,3}', '', s)
    s = re.sub(r'^\s*>\s?', '', s, flags=re.M)
    s = re.sub(r'^\s*[-*+]\s+', '', s, flags=re.M)
    return s.strip()


TRANSFORMS = [
    ('deformat', '去格式（HTML→纯文本）', t_deformat),
    ('dropblank', '去空行', t_drop_blank_lines),
    ('trimlines', '去每行首尾空格', t_trim_lines),
    ('trim', '去整体首尾空白', t_trim),
    ('half', '全角→半角', to_halfwidth),
    ('full', '半角→全角', to_fullwidth),
    ('upper', '全部大写', t_upper),
    ('lower', '全部小写', t_lower),
    ('capital', '首字母大写', t_capitalize),
    ('camel', '转小驼峰', to_camel),
    ('pascal', '转大驼峰', to_pascal),
    ('snake', '转下划线', to_snake),
    ('kebab', '转短横线', to_kebab),
    ('jsonfmt', 'JSON 格式化', t_json_format),
    ('jsonmin', 'JSON 压缩', t_json_minify),
    ('b64enc', 'Base64 编码', t_b64enc),
    ('b64dec', 'Base64 解码', t_b64dec),
    ('urlenc', 'URL 编码', t_urlenc),
    ('urldec', 'URL 解码', t_urldec),
    ('md5', 'MD5', t_md5),
    ('sha1', 'SHA1', t_sha1),
    ('sha256', 'SHA256', t_sha256),
    ('exurl', '提取全部 URL', t_extract_url),
    ('exnum', '提取全部数字', t_extract_num),
    ('sortline', '行排序', t_sort_lines),
    ('uniqline', '行去重', t_uniq_lines),
    ('md2txt', 'Markdown→纯文本', t_md_to_text),
]
MAP = {k: f for k, _, f in TRANSFORMS}


def apply(key, text):
    f = MAP.get(key)
    if not f:
        raise ValueError('未知变换：%s' % key)
    return f(text)
