# -*- coding: utf-8 -*-
"""自测：命令面板纯逻辑（注册表 + 模糊过滤）。

覆盖：
1. COMMANDS 注册表：9 条命令、命令名不重复、每条都有可调用回调
2. build_registry 把回调正确绑定到 app 方法（用 __getattr__ 桩对象验证）
3. filter_commands：空串返回全部 / 大小写不敏感过滤 / 名字前缀优先排序
"""
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from clawboard.command_palette import COMMANDS, build_registry, filter_commands

OK = True
LOG = []


def check(name, cond, extra=''):
    global OK
    if not cond:
        OK = False
    LOG.append('%s  %s%s' % ('OK  ' if cond else 'FAIL', name,
                             ('  ' + extra) if extra else ''))


# ---------- 1. 注册表完整性 ----------
names = [c[0] for c in COMMANDS]
check('命令条数为 9', len(COMMANDS) == 9, '实际 %d' % len(COMMANDS))
check('命令名不重复', len(names) == len(set(names)))
check('每条都是三元组', all(len(c) == 3 for c in COMMANDS))
check('每条都有回调（可调用）', all(callable(c[2]) for c in COMMANDS))
check('命令名非空', all(c[0].strip() for c in COMMANDS))
check('描述非空', all(c[1].strip() for c in COMMANDS))


class FakeApp:
    """用 __getattr__ 桩掉 9 个目标方法，验证 build_registry 能正确解析。"""
    def __getattr__(self, name):
        return lambda: name


reg = build_registry(FakeApp())
check('build_registry 解析出 9 条', len(reg) == 9, '实际 %d' % len(reg))
check('build_registry 回调全部可调用', all(callable(c[2]) for c in reg))
resolved = [c[2]() for c in reg]
expect = ['clear_list', 'toggle_listen', 'open_export', 'open_transform',
          'add_phrase', 'open_settings', 'toggle_pin', 'toggle_collapse', 'quit_app']
check('build_registry 回调指向正确方法', resolved == expect,
      '实际 %s' % resolved)

# ---------- 2. 模糊过滤 ----------
sample = [
    ('清空历史', '清空当前列表', 'a'),
    ('导出全部', '导出当前内容', 'b'),
    ('文本变换', '大小写转换', 'c'),
    ('新增常用语', '存为常用语', 'd'),
]

check('空串返回全部', len(filter_commands('', sample)) == 4)
check('None 返回全部', len(filter_commands(None, sample)) == 4)
check('纯空白返回全部', len(filter_commands('   ', sample)) == 4)
check('无命中返回空', filter_commands('zzz', sample) == [])

got = filter_commands('清空', sample)
check("'清空' 命中 1 条", len(got) == 1 and got[0][0] == '清空历史',
      '实际 %s' % [c[0] for c in got])

# 同一个词同时命中「名字」和「描述」两条
mix = [('导出全部', '导出当前内容', 'b'), ('复制', '导出为文件', 'x')]
got = filter_commands('导出', mix)
check("'导出' 名字+描述各命中一条", len(got) == 2, '实际 %d' % len(got))
check("'导出' 名字命中排前", got[0][0] == '导出全部', '实际 %s' % [c[0] for c in got])

# 排序：名字前缀命中 > 名字包含 > 描述包含
sort_sample = [
    ('desc', 'has abc inside', None),
    ('abc', 'prefix match', None),
    ('xabcx', 'contains match', None),
]
got = filter_commands('abc', sort_sample)
check('前缀命中排最前', got[0][0] == 'abc', '实际 %s' % [c[0] for c in got])
check('名字包含次之', got[1][0] == 'xabcx', '实际 %s' % [c[0] for c in got])
check('描述包含最后', got[2][0] == 'desc', '实际 %s' % [c[0] for c in got])

# 大小写不敏感（英文）
eng = [('Transform', 'JSON format', None), ('plain', 'nothing', None)]
got = filter_commands('TRANSFORM', eng)
check('英文名字大小写不敏感', len(got) == 1 and got[0][0] == 'Transform')
got = filter_commands('json', eng)
check('英文描述大小写不敏感', len(got) == 1 and got[0][0] == 'Transform')

with io.open(os.path.join(tempfile.gettempdir(), '_t30.out'), 'w',
             encoding='utf-8') as f:
    f.write('\n'.join(LOG) + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))
os._exit(0)
