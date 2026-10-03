# -*- coding: utf-8 -*-
"""拼音查表：汉字 → 全拼 / 首字母。纯函数，无 UI 依赖，可单测。

依赖 clawboard/pinyin_data.py（单字表）与 clawboard/pinyin_phrase.py（多音词组表）。
多音字用「最长词组匹配」纠正：先匹配 3 字、再 2 字词组，命中用词组正确读音，
否则回退单字表（取第一读音）。ü 记作 v。
"""

from clawboard.pinyin_data import PINYIN
from clawboard.pinyin_phrase import PINYIN_PHRASE


def to_pinyin(text):
    """汉字转全拼，多音字用词组纠正。非汉字（字母/数字/符号）原样保留。"""
    s = text or ''
    out = []
    i = 0
    while i < len(s):
        matched = False
        for n in (3, 2):                     # 最长匹配：先 3 字、再 2 字
            if i + n <= len(s):
                ph = s[i:i + n]
                if ph in PINYIN_PHRASE:
                    out.append(PINYIN_PHRASE[ph])
                    i += n
                    matched = True
                    break
        if not matched:
            out.append(PINYIN.get(s[i], s[i]))
            i += 1
    return ''.join(out)


def to_pinyin_initials(text):
    """汉字转拼音首字母。非汉字原样保留。"""
    out = []
    for c in (text or ''):
        p = PINYIN.get(c)
        out.append(p[0] if p else c)
    return ''.join(out)

