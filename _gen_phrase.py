# -*- coding: utf-8 -*-
"""生成 clawboard/pinyin_phrase.py：内置多音字词组拼音表（2-3 字）。

数据来源：https://github.com/mozillazg/phrase-pinyin-data （MIT 许可，version 0.19.0）
只保留「词组拼音 ≠ 单字拼音拼接」的多音字词组，用于纠正单字表的错误读音。
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from clawboard.pinyin_data import PINYIN

SRC = os.path.join(os.environ.get('TEMP', '.'), 'phrase.txt')
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'clawboard',
                   'pinyin_phrase.py')

tone_map = {}
for a, b in zip('āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜü', 'aaaaeeeeiiiioooouuuuvvvvv'):
    tone_map[a] = b


def strip_tone(p):
    return ''.join(tone_map.get(c, c) for c in p)


pat = re.compile(r'^([\u4e00-\u9fa5]+):\s*([^#]+?)\s*$')
kept = {}
for line in io.open(SRC, encoding='utf-8'):
    m = pat.match(line)
    if not m:
        continue
    ph = m.group(1)
    if not (2 <= len(ph) <= 3):
        continue
    py = ''.join(strip_tone(m.group(2)).split())
    single = ''.join(PINYIN.get(c, c) for c in ph)
    if py != single:
        kept[ph] = py

print('内置多音词组数:', len(kept))

lines = ['# -*- coding: utf-8 -*-',
         '"""内置多音字词组拼音表（2-3 字），用于纠正单字表错误读音。',
         '',
         '数据来源：https://github.com/mozillazg/phrase-pinyin-data （MIT 许可）',
         '生成脚本见 _gen_phrase.py。',
         '"""',
         'PINYIN_PHRASE = {']
row = []
for ph, py in sorted(kept.items()):
    row.append('%r: %r' % (ph, py))
    if len(row) >= 12:
        lines.append('    ' + ', '.join(row) + ',')
        row = []
if row:
    lines.append('    ' + ', '.join(row) + ',')
lines.append('}')
lines.append('')

io.open(OUT, 'w', encoding='utf-8').write('\n'.join(lines))
print('已生成', OUT, os.path.getsize(OUT), '字节')
