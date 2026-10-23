"""Generated-table contracts: complete content/order, provenance and regeneration.

Digests were captured from the ordered dictionaries in upstream 6a10466. They
cover every key/value without requiring another checkout or network download.
"""
import ast
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import _gen_phrase
import _gen_pinyin
from clawboard.pinyin import to_pinyin, to_pinyin_initials
from clawboard.pinyin_data import PINYIN
from clawboard.pinyin_phrase import PINYIN_PHRASE


def ordered_digest(mapping):
    encoded = json.dumps(list(mapping.items()), ensure_ascii=False,
                         separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def shard_mapping(path, symbol):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == symbol
                              for target in node.targets))
    return ast.literal_eval(assignment.value)


class PinyinDataContractTests(unittest.TestCase):
    def test_every_single_character_and_its_order_match_upstream(self):
        self.assertIsInstance(PINYIN, dict)
        self.assertEqual(len(PINYIN), 20892)
        self.assertEqual(ordered_digest(PINYIN),
                         'b426b95eb80bb5009ec0edad9795b60fc0ac7d0f541da967e80eb66d74fb59c9')

    def test_every_phrase_and_its_order_match_upstream(self):
        self.assertIsInstance(PINYIN_PHRASE, dict)
        self.assertEqual(len(PINYIN_PHRASE), 14019)
        self.assertEqual(ordered_digest(PINYIN_PHRASE),
                         '47426d461efbf41c6d44bf787c258bde1de903fd78f42bd35323b6aeb2cd07a3')

    def test_shards_are_bounded_and_keep_original_row_width_and_provenance(self):
        for generator, symbol, mapping in ((_gen_pinyin, 'PINYIN_PART', PINYIN),
                                            (_gen_phrase, 'PINYIN_PHRASE_PART', PINYIN_PHRASE)):
            with self.subTest(output=generator.OUT.name):
                paths = sorted(generator.OUT.parent.glob(generator.OUT.stem + '_[0-9]*.py'))
                joined = {}
                for path in paths:
                    source = path.read_text(encoding='utf-8')
                    lines = source.splitlines()
                    self.assertLess(len(lines), 800)
                    self.assertIn('MIT', source)
                    self.assertIn('https://github.com/mozillazg/', source)
                    entries = shard_mapping(path, symbol)
                    self.assertLessEqual(len(entries), generator.ROWS_PER_SHARD * generator.ENTRIES_PER_ROW)
                    data_lines = [line for line in lines if line.startswith('    ')]
                    for line in data_lines:
                        self.assertLessEqual(len(ast.literal_eval('{' + line.strip().rstrip(',') + '}')),
                                             generator.ENTRIES_PER_ROW)
                    joined.update(entries)
                self.assertEqual(list(joined.items()), list(mapping.items()))
                self.assertLess(len(generator.OUT.read_text(encoding='utf-8').splitlines()), 800)

    def test_regeneration_reproduces_exact_tracked_output(self):
        for generator, mapping in ((_gen_pinyin, PINYIN), (_gen_phrase, PINYIN_PHRASE)):
            with self.subTest(output=generator.OUT.name), tempfile.TemporaryDirectory() as directory:
                paths = generator.write_modules(mapping, Path(directory) / generator.OUT.name)
                for path in paths:
                    tracked = generator.OUT.parent / path.name
                    self.assertEqual(path.read_bytes(), tracked.read_bytes())

    def test_regeneration_removes_only_obsolete_numeric_shards(self):
        for generator in (_gen_pinyin, _gen_phrase):
            with self.subTest(output=generator.OUT.name), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / generator.OUT.name
                unrelated = output.with_name(output.stem + '_notes.py')
                unrelated.write_text('# hand maintained\n', encoding='utf-8')
                large = {chr(0x4E00 + number): 'test' for number in range(40)}
                generator.write_modules(large, output, rows_per_shard=1)
                self.assertTrue(output.with_name(output.stem + '_2.py').exists())
                generator.write_modules({'一': 'yi'}, output, rows_per_shard=1)
                self.assertTrue(output.with_name(output.stem + '_0.py').exists())
                self.assertFalse(output.with_name(output.stem + '_1.py').exists())
                self.assertFalse(output.with_name(output.stem + '_2.py').exists())
                self.assertTrue(unrelated.exists())
                generator.write_modules({}, output)
                self.assertFalse(output.with_name(output.stem + '_0.py').exists())
                self.assertTrue(unrelated.exists())
                ast.parse(output.read_text(encoding='utf-8'))

    def test_generator_shard_row_limit_is_enforced(self):
        for generator in (_gen_pinyin, _gen_phrase):
            with self.subTest(output=generator.OUT.name), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / generator.OUT.name
                for invalid in (0, -1, 601, 1.5, '600'):
                    with self.assertRaises(ValueError):
                        generator.write_modules({}, output, rows_per_shard=invalid)

    def test_single_source_parsing_keeps_range_first_reading_and_tones(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'pinyin.txt'
            source.write_text('U+4E00: yī  # 一\nU+884C: xíng,háng # 行\n'
                              'U+3400: qiū # 㐀\nU+9FA6: gǔ # 龦\n', encoding='utf-8')
            self.assertEqual(_gen_pinyin.parse_source(source), {'一': 'yi', '行': 'xing'})
            self.assertEqual(_gen_pinyin.strip_tone('nǚ'), 'nv')

    def test_phrase_parsing_keeps_only_short_pronunciation_corrections(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'phrase.txt'
            source.write_text('重庆: chóng qìng\n重庆市: chóng qìng shì\n'
                              '中国: zhōng guó\n中国人民: zhōng guó rén mín\n', encoding='utf-8')
            single = {'重': 'zhong', '庆': 'qing', '市': 'shi', '中': 'zhong', '国': 'guo'}
            self.assertEqual(_gen_phrase.parse_source(source, single_map=single),
                             {'重庆': 'chongqing', '重庆市': 'chongqingshi'})

    def test_phrase_matching_and_initials_preserve_runtime_contract(self):
        self.assertEqual(to_pinyin('重庆银行'), 'chongqingyinhang')
        self.assertEqual(to_pinyin('你好ABC'), 'nihaoABC')
        self.assertEqual(to_pinyin_initials('你好ABC'), 'nhABC')


if __name__ == '__main__':
    unittest.main(verbosity=2)
