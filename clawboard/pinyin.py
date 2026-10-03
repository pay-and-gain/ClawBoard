# -*- coding: utf-8 -*-
"""拼音查表：汉字 → 全拼 / 首字母。纯函数，无 UI 依赖，可单测。

依赖 clawboard/pinyin_data.py（内置拼音表，MIT 数据）。
多音字取第一读音（pinyin-data 的首个读音）；ü 记作 v。
"""

from clawboard.pinyin_data import PINYIN


def to_pinyin(text):
    """汉字转全拼。非汉字（字母/数字/符号）原样保留。"""
    return ''.join(PINYIN.get(c, c) for c in (text or ''))


def to_pinyin_initials(text):
    """汉字转拼音首字母。非汉字原样保留。"""
    out = []
    for c in (text or ''):
        p = PINYIN.get(c)
        out.append(p[0] if p else c)
    return ''.join(out)
