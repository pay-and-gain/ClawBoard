# -*- coding: utf-8 -*-
"""内置拼音表：汉字 → 全拼（多音字取第一读音，ü 记作 v）。

数据来源：https://github.com/mozillazg/pinyin-data （MIT 许可，version 0.15.0）
由 _gen_pinyin.py 按最多600个数据行分块；首字母 = 全拼[0]。
"""
from clawboard.pinyin_data_0 import PINYIN_PART as _part_0
from clawboard.pinyin_data_1 import PINYIN_PART as _part_1
from clawboard.pinyin_data_2 import PINYIN_PART as _part_2

PINYIN = {}
PINYIN.update(_part_0)
PINYIN.update(_part_1)
PINYIN.update(_part_2)
del _part_0, _part_1, _part_2
