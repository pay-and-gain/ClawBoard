# -*- coding: utf-8 -*-
"""开发工具，不参与产品运行：生成内置单字拼音表与有界数据分块。

数据来源：https://github.com/mozillazg/pinyin-data （MIT，version 0.15.0）
输入格式：U+XXXX: pinyin1,pinyin2  # 汉字
"""
from pathlib import Path
import os
import re


SRC = Path(os.environ.get('TEMP', '.')) / 'pinyin.txt'
OUT = Path(__file__).resolve().parent / 'clawboard' / 'pinyin_data.py'
ROWS_PER_SHARD = 600
ENTRIES_PER_ROW = 16
SOURCE = 'https://github.com/mozillazg/pinyin-data （MIT 许可，version 0.15.0）'
TONE_MAP = dict(zip('āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜü', 'aaaaeeeeiiiioooouuuuvvvvv'))
PATTERN = re.compile(r'^U\+([0-9A-F]+):\s*([^#]+?)\s*#\s*(.)')


def strip_tone(pinyin):
    return ''.join(TONE_MAP.get(char, char) for char in pinyin)


def parse_source(source=SRC):
    """沿用原筛选范围与第一读音规则；不改变单字表的语义。"""
    mapping = {}
    with Path(source).open(encoding='utf-8') as stream:
        for line in stream:
            match = PATTERN.match(line)
            if not match or not (0x4E00 <= int(match.group(1), 16) <= 0x9FA5):
                continue
            syllables = [word.strip() for word in match.group(2).split(',') if word.strip()]
            if syllables:
                mapping[match.group(3)] = strip_tone(syllables[0])
    return mapping


def write_modules(mapping, output=OUT, *, rows_per_shard=ROWS_PER_SHARD):
    """每块最多600个原宽度数据行；聚合顺序与原排序字典完全一致。"""
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
                 '"""内置单字拼音数据分块 %d；自动生成，修改请运行 _gen_pinyin.py。' % index,
                 '', '数据来源：' + SOURCE, '"""', 'PINYIN_PART = {']
        for start in range(0, len(chunk), ENTRIES_PER_ROW):
            lines.append('    ' + ', '.join('%r: %r' % pair
                                          for pair in chunk[start:start + ENTRIES_PER_ROW]) + ',')
        lines.extend(('}', ''))
        path.write_text('\n'.join(lines), encoding='utf-8')
        shard_paths.append(path)
    lines = ['# -*- coding: utf-8 -*-',
             '"""内置拼音表：汉字 → 全拼（多音字取第一读音，ü 记作 v）。',
             '', '数据来源：' + SOURCE,
             '由 _gen_pinyin.py 按最多600个数据行分块；首字母 = 全拼[0]。', '"""']
    for index, path in enumerate(shard_paths):
        lines.append('from clawboard.%s import PINYIN_PART as _part_%d' % (path.stem, index))
    lines.extend(('', 'PINYIN = {}'))
    for index in range(len(shard_paths)):
        lines.append('PINYIN.update(_part_%d)' % index)
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
    print('筛选汉字数:', len(mapping))
    print('已生成聚合层及分块:', len(paths), '文件,', sum(path.stat().st_size for path in paths), '字节')


if __name__ == '__main__':
    main()
