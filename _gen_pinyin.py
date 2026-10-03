# -*- coding: utf-8 -*-
"""生成 clawboard/pinyin_data.py：从 pinyin-data 的单字拼音表生成内置映射。

数据来源：https://github.com/mozillazg/pinyin-data （MIT 许可）
格式：U+XXXX: pinyin1,pinyin2  # 汉字
"""
import io
import os
import re

SRC = os.path.join(os.environ.get('TEMP', '.'), 'pinyin.txt')
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'clawboard',
                   'pinyin_data.py')

tone_map = {}
for a, b in zip('āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜü', 'aaaaeeeeiiiioooouuuuvvvvv'):
    tone_map[a] = b


def strip_tone(p):
    return ''.join(tone_map.get(c, c) for c in p)


pat = re.compile(r'^U\+([0-9A-F]+):\s*([^#]+?)\s*#\s*(.)')
full = {}
count = 0
for line in io.open(SRC, encoding='utf-8'):
    m = pat.match(line)
    if not m:
        continue
    cp = int(m.group(1), 16)
    ch = m.group(3)
    if not (0x4E00 <= cp <= 0x9FA5):
        continue
    pys = [p.strip() for p in m.group(2).split(',') if p.strip()]
    if not pys:
        continue
    full[ch] = strip_tone(pys[0])
    count += 1

print('筛选汉字数:', count)

# 生成紧凑的 dict 字面量（多行，每行约 16 个条目）
lines = ['# -*- coding: utf-8 -*-',
         '"""内置拼音表：汉字 → 全拼（多音字取第一读音，ü 记作 v）。',
         '',
         '数据来源：https://github.com/mozillazg/pinyin-data （MIT 许可，version 0.15.0）',
         '生成脚本见 _gen_pinyin.py。首字母 = 全拼[0]。',
         '"""',
         'PINYIN = {']
items = sorted(full.items())
row = []
for ch, p in items:
    row.append('%r: %r' % (ch, p))
    if len(row) >= 16:
        lines.append('    ' + ', '.join(row) + ',')
        row = []
if row:
    lines.append('    ' + ', '.join(row) + ',')
lines.append('}')
lines.append('')

io.open(OUT, 'w', encoding='utf-8').write('\n'.join(lines))
print('已生成', OUT, os.path.getsize(OUT), '字节')
