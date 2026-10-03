# -*- coding: utf-8 -*-
"""内容自动标签：按内容性质自动打标签，支持 tag: 搜索筛选。

纯函数，无 UI / ctypes 依赖，可单测。
标签是「中性」的描述（邮箱/手机号/数字/日期…），区别于「敏感」语义（sens）。
"""
import json
import re

from clawboard.classify import looks_like_code

# 标签正则（复用敏感识别里的同款规则，但语义是中性标签）
_TAG_PATTERNS = [
    ('email', re.compile(r'[\w.+-]+@[\w-]+\.[\w.]{2,}')),
    ('phone', re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)')),
    ('idcard', re.compile(r'(?<!\d)\d{17}[\dXx](?!\d)')),
    ('bankcard', re.compile(r'(?<!\d)\d{16,19}(?!\d)')),
    ('token', re.compile(r'(?:sk-|ghp_|xox[baprs]-|Bearer\s+)[A-Za-z0-9_\-]{8,}')),
    ('password', re.compile(r'(?i)(password|passwd|pwd|密码|口令)\s*[:：=]\s*\S{4,}')),
    ('url', re.compile(r'https?://\S+', re.I)),
    ('date', re.compile(r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}')),
]

# 标签显示名（列表徽章 / 搜索提示用）
TAG_LABELS = {
    'email': '邮箱', 'phone': '手机号', 'idcard': '身份证', 'bankcard': '银行卡',
    'token': 'Token', 'password': '密码', 'url': '链接', 'number': '数字',
    'date': '日期', 'code': '代码', 'json': 'JSON',
}

# tag: 搜索能识别的标签名（含中文别名）
_TAG_ALIASES = {
    'email': 'email', 'mail': 'email', '邮箱': 'email',
    'phone': 'phone', '手机': 'phone', '手机号': 'phone',
    'idcard': 'idcard', '身份证': 'idcard',
    'bankcard': 'bankcard', '银行卡': 'bankcard',
    'token': 'token', '密钥': 'token',
    'password': 'password', '密码': 'password', '口令': 'password',
    'url': 'url', '链接': 'url',
    'number': 'number', '数字': 'number',
    'date': 'date', '日期': 'date',
    'code': 'code', '代码': 'code',
    'json': 'json',
}


def detect_tags(text):
    """返回内容命中的标签列表（顺序按 _TAG_PATTERNS 定义序）。"""
    s = text or ''
    if not isinstance(s, str):
        return []
    tags = []
    for name, pat in _TAG_PATTERNS:
        if pat.search(s):
            tags.append(name)
    # 纯数字（数字/小数/负数/千分位）
    if re.fullmatch(r'[0-9\s.,+\-]+', s) and any(c.isdigit() for c in s):
        tags.append('number')
    # JSON 优先于 code：{"a":1} 也会命中代码特征，但它是 JSON 不是代码
    is_json = False
    if s[:1] in ('{', '['):
        try:
            json.loads(s)
            tags.append('json')
            is_json = True
        except Exception:
            pass
    if not is_json and looks_like_code(s):
        tags.append('code')
    return tags


def normalize_tag(word):
    """把 tag: 后面的词规范成标准标签名，识别不了返回 None。"""
    return _TAG_ALIASES.get((word or '').strip().lower())
