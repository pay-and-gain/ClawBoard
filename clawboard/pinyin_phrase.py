# -*- coding: utf-8 -*-
"""内置多音字词组拼音表（2–3字），用于纠正单字表错误读音。

数据来源：https://github.com/mozillazg/phrase-pinyin-data （MIT 许可，version 0.19.0）
由 _gen_phrase.py 按最多600个数据行分块。
"""
from clawboard.pinyin_phrase_0 import PINYIN_PHRASE_PART as _part_0
from clawboard.pinyin_phrase_1 import PINYIN_PHRASE_PART as _part_1

PINYIN_PHRASE = {}
PINYIN_PHRASE.update(_part_0)
PINYIN_PHRASE.update(_part_1)
del _part_0, _part_1
