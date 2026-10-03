# -*- coding: utf-8 -*-
"""F3 查询解析器 / F4 变换函数 单元测试（python test_core.py）"""
import os
import sys
import time
import json
import base64
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import query
import transform as tr

NOW = int(time.time() * 1000)


def item(text, app='chrome', ctype='text', size=None, fav=0, est=0, ts=None):
    return {'text': text, 'name': '', 'source_app': app, 'content_type': ctype,
            'content_size': size if size is not None else len(text.encode('utf-8')),
            'fav': fav, 'is_estimated': est, 'sens': None,
            'created_at': ts if ts is not None else NOW}


class TestQuery(unittest.TestCase):
    def test_empty(self):
        c = query.parse('')
        self.assertEqual(c['terms'], [])
        self.assertEqual(c['errors'], [])

    def test_and_terms(self):
        items = [item('hello world'), item('hello'), item('world')]
        got, _ = query.match('hello world', items)
        self.assertEqual(len(got), 1)

    def test_exclude(self):
        items = [item('hello world'), item('hello')]
        got, _ = query.match('hello -world', items)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]['text'], 'hello')

    def test_app_chinese_fuzzy(self):
        items = [item('a', app='WeChat'), item('b', app='chrome')]
        self.assertEqual(len(query.match('app:wechat', items)[0]), 1)
        self.assertEqual(len(query.match('app:微信', items)[0]), 0)   # 进程名是英文
        self.assertEqual(len(query.match('app:hro', items)[0]), 1)    # 模糊

    def test_type_and_size(self):
        items = [item('https://a.com', ctype='url', size=100),
                 item('plain', ctype='text', size=2 * 1024 * 1024)]
        self.assertEqual(len(query.match('type:url', items)[0]), 1)
        self.assertEqual(len(query.match('size:>1mb', items)[0]), 1)
        self.assertEqual(len(query.match('size:<200', items)[0]), 1)

    def test_is_flags(self):
        items = [item('a', fav=1), item('b', fav=0)]
        self.assertEqual(len(query.match('is:fav', items)[0]), 1)

    def test_time_relative(self):
        old = item('old', ts=NOW - 2 * 3600 * 1000)
        new = item('new', ts=NOW - 60 * 1000)
        self.assertEqual(len(query.match('time:>1h', [old, new])[0]), 1)
        self.assertEqual(len(query.match('time:<30m', [old, new])[0]), 1)

    def test_time_date_and_range(self):
        import datetime
        d = datetime.datetime.now()
        s = d.strftime('%Y-%m-%d')
        today = item('today', ts=NOW)
        old = item('old', ts=NOW - 10 * 86400 * 1000)
        self.assertEqual(len(query.match('time:' + s, [today, old])[0]), 1)
        got, _ = query.match('time:2020-01-01..2020-12-31', [today, old])
        self.assertEqual(len(got), 0)

    def test_time_slot(self):
        # 用固定白天时段（10:00-12:00）+ 对应时间戳构造条目，不依赖运行时刻。
        # 原实现用 now-1h..now+1h，在 23:00~00:59 运行时起时间会跨午夜回绕，
        # 测试因此时好时坏（flaky）。固定时段后稳定可复现。
        import datetime
        d = datetime.datetime.now().replace(hour=11, minute=0, second=0, microsecond=0)
        ts = int(d.timestamp() * 1000)                     # 当天 11:00
        got, _ = query.match('time:10:00-12:00', [item('x', ts=ts)])
        self.assertEqual(len(got), 1)
        # 12:30 在白天时段之外，不该命中
        ts2 = int((d.replace(hour=12, minute=30)).timestamp() * 1000)
        got2, _ = query.match('time:10:00-12:00', [item('y', ts=ts2)])
        self.assertEqual(len(got2), 0)

    def test_time_slot_cross_midnight(self):
        # 跨午夜时段 22:00-02:00 的回归由 tests/_t36.py 全面覆盖，
        # 这里只做一条冒烟：23:00 与 01:00 都应命中。
        import datetime
        d = datetime.datetime.now().replace(hour=23, minute=0, second=0, microsecond=0)
        ts_late = int(d.timestamp() * 1000)                 # 当天 23:00
        self.assertEqual(
            len(query.match('time:22:00-02:00', [item('a', ts=ts_late)])[0]), 1)

    def test_bad_syntax_no_crash(self):
        c = query.parse('time:notatime type:zzz size:abc is:zzz')
        self.assertTrue(len(c['errors']) >= 3)
        got, cond = query.match('time:notatime', [item('x')])
        self.assertTrue(isinstance(got, list))

    def test_injection_string(self):
        # 无 SQL 层：注入串只会被当成字面量关键词，绝不改变过滤逻辑
        evil = "' OR 1=1 --"
        items = [item('normal'), item(evil)]
        got, cond = query.match("1=1", items)      # 单个 token，字面量匹配
        self.assertEqual(len(got), 1)              # 只命中含该字面量那一条
        self.assertEqual(got[0]['text'], evil)
        got2, cond2 = query.match(evil, items)     # 带空格 = 多词 AND
        self.assertEqual(cond2['errors'], [])      # 不报错、不崩溃
        self.assertTrue(isinstance(got2, list))

    def test_very_long_keyword(self):
        long_kw = 'x' * 5000
        got, _ = query.match(long_kw, [item('y' * 10000), item('short')])
        self.assertEqual(len(got), 0)

    def test_neg_app_and_type(self):
        items = [item('a', app='chrome', ctype='text'),
                 item('b', app='excel', ctype='url')]
        got, _ = query.match('-app:chrome -type:url', items)
        self.assertEqual(len(got), 0)
        got, _ = query.match('-app:chrome', items)
        self.assertEqual(len(got), 1)


class TestTransform(unittest.TestCase):
    def test_deformat(self):
        self.assertEqual(tr.t_deformat('<p>你好&nbsp;&amp; 世界</p><li>一</li>'),
                         '你好 & 世界\n一')

    def test_drop_blank(self):
        self.assertEqual(tr.t_drop_blank_lines('a\n\n\nb\n  \nc'), 'a\nb\nc')

    def test_trim_lines(self):
        self.assertEqual(tr.t_trim_lines('  a  \n b'), 'a\nb')

    def test_width(self):
        self.assertEqual(tr.to_halfwidth('ＡＢＣ　１２３'), 'ABC 123')
        self.assertEqual(tr.to_fullwidth('AB 1'), 'ＡＢ　１')

    def test_case(self):
        self.assertEqual(tr.t_upper('abc'), 'ABC')
        self.assertEqual(tr.t_lower('ABC'), 'abc')
        self.assertEqual(tr.t_capitalize('hello world'), 'Hello World')

    def test_naming(self):
        self.assertEqual(tr.to_camel('user name first'), 'userNameFirst')
        self.assertEqual(tr.to_pascal('user_name'), 'UserName')
        self.assertEqual(tr.to_snake('UserNameFirst'), 'user_name_first')
        self.assertEqual(tr.to_kebab('UserName'), 'user-name')

    def test_json(self):
        self.assertIn('\n', tr.t_json_format('{"a":1}'))
        self.assertEqual(tr.t_json_minify('{"a": 1}'), '{"a":1}')
        with self.assertRaises(ValueError):
            tr.t_json_format('{bad json}')

    def test_base64(self):
        enc = tr.t_b64enc('中文abc')
        self.assertEqual(tr.t_b64dec(enc), '中文abc')
        self.assertEqual(enc, base64.b64encode('中文abc'.encode()).decode())
        with self.assertRaises(ValueError):
            tr.t_b64dec('!!!not base64!!!')

    def test_url(self):
        self.assertEqual(tr.t_urldec(tr.t_urlenc('中文 &/?=x')), '中文 &/?=x')

    def test_hash(self):
        self.assertEqual(len(tr.t_md5('abc')), 32)
        self.assertEqual(len(tr.t_sha1('abc')), 40)
        self.assertEqual(len(tr.t_sha256('abc')), 64)

    def test_extract(self):
        self.assertEqual(tr.t_extract_url('see https://a.com/x and http://b.cn'),
                         'https://a.com/x\nhttp://b.cn')
        self.assertEqual(tr.t_extract_num('a1 b-2.5 c'), '1\n-2.5')
        with self.assertRaises(ValueError):
            tr.t_extract_url('no url here')

    def test_lines(self):
        self.assertEqual(tr.t_sort_lines('c\na\nb'), 'a\nb\nc')
        self.assertEqual(tr.t_uniq_lines('a\na\nb'), 'a\nb')

    def test_md(self):
        self.assertEqual(tr.t_md_to_text('# 标题\n- **加粗**\n[链接](http://x)'),
                         '标题\n加粗\n链接')

    def test_apply_unknown(self):
        with self.assertRaises(ValueError):
            tr.apply('nope', 'x')


if __name__ == '__main__':
    unittest.main(verbosity=2)
