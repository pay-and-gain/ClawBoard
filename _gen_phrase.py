# -*- coding: utf-8 -*-
"""开发工具，不参与产品运行：生成内置多音词组拼音表与有界数据分块。

数据来源：https://github.com/mozillazg/phrase-pinyin-data （MIT，version 0.19.0）
只保留2–3字且词组拼音不同于单字拼接的词组，保持既有纠音规则。
"""
from pathlib import Path
import os
import re

from clawboard.pinyin_data import PINYIN


SRC = Path(os.environ.get('TEMP', '.')) / 'phrase.txt'
OUT = Path(__file__).resolve().parent / 'clawboard' / 'pinyin_phrase.py'
ROWS_PER_SHARD = 600
ENTRIES_PER_ROW = 12
SOURCE = 'https://github.com/mozillazg/phrase-pinyin-data （MIT 许可，version 0.19.0）'
TONE_MAP = dict(zip('āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜü', 'aaaaeeeeiiiioooouuuuvvvvv'))
PATTERN = re.compile(r'^([\u4e00-\u9fa5]+):\s*([^#]+?)\s*$')


def strip_tone(pinyin):
    return ''.join(TONE_MAP.get(char, char) for char in pinyin)


def parse_source(source=SRC, *, single_map=PINYIN):
    mapping = {}
    with Path(source).open(encoding='utf-8') as stream:
        for line in stream:
            match = PATTERN.match(line)
            if not match:
                continue
            phrase = match.group(1)
            if not 2 <= len(phrase) <= 3:
                continue
            pinyin = ''.join(strip_tone(match.group(2)).split())
            if pinyin != ''.join(single_map.get(char, char) for char in phrase):
                mapping[phrase] = pinyin
    return mapping


def write_modules(mapping, output=OUT, *, rows_per_shard=ROWS_PER_SHARD):
    """延续每行12词组，只通过固定分块减少文件行数。"""
    if not isinstance(rows_per_shard, int) or not 1 <= rows_per_shard <= ROWS_PER_SHARD:
        raise ValueError('rows_per_shard 必须介于 1 与 600')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    items = sorted(mapping.items())
    capacity = rows_per_shard * ENTRIES_PER_ROW
    chunks = [items[start:start + capacity] for start in range(0, len(items), capacity)]
    shard_paths = []
    for index, chunk in enumerate(chunks):
        path = output.with_name('%s_%d.py' % (output.stem, index))
        lines = ['# -*- coding: utf-8 -*-',
                 '"""内置多音词组数据分块 %d；自动生成，修改请运行 _gen_phrase.py。' % index,
                 '', '数据来源：' + SOURCE, '"""', 'PINYIN_PHRASE_PART = {']
        for start in range(0, len(chunk), ENTRIES_PER_ROW):
            lines.append('    ' + ', '.join('%r: %r' % pair
                                          for pair in chunk[start:start + ENTRIES_PER_ROW]) + ',')
        lines.extend(('}', ''))
        path.write_text('\n'.join(lines), encoding='utf-8')
        shard_paths.append(path)
    lines = ['# -*- coding: utf-8 -*-',
             '"""内置多音字词组拼音表（2–3字），用于纠正单字表错误读音。',
             '', '数据来源：' + SOURCE,
             '由 _gen_phrase.py 按最多600个数据行分块。', '"""']
    for index, path in enumerate(shard_paths):
        lines.append('from clawboard.%s import PINYIN_PHRASE_PART as _part_%d' % (path.stem, index))
    lines.extend(('', 'PINYIN_PHRASE = {}'))
    for index in range(len(shard_paths)):
        lines.append('PINYIN_PHRASE.update(_part_%d)' % index)
    if shard_paths:
        lines.append('del ' + ', '.join('_part_%d' % index for index in range(len(shard_paths))))
    lines.append('')
    output.write_text('\n'.join(lines), encoding='utf-8')
    active = {path.name for path in shard_paths}
    pattern = re.compile(re.escape(output.stem) + r'_\d+\.py$')
    for path in output.parent.glob(output.stem + '_*.py'):
        if pattern.fullmatch(path.name) and path.name not in active:
            path.unlink()
    return (output, *shard_paths)


def main():
    mapping = parse_source()
    paths = write_modules(mapping)
    print('内置多音词组数:', len(mapping))
    print('已生成聚合层及分块:', len(paths), '文件,', sum(path.stat().st_size for path in paths), '字节')


if __name__ == '__main__':
    main()
