# -*- coding: utf-8 -*-
"""文件剪贴板「闭环」自测：把路径列表写回剪贴板时改用 CF_HDROP，
粘出去是真正的文件，而不是一串路径文字。

覆盖：
1. build_hdrop() 的字节结构（DROPFILES 头 + UTF-16 路径 + 双 NUL 结尾）。
2. clip_write_files() 写剪贴板 → clip_read_files() 读回一致（多条 / 中文 / 带空格 / 单条）。
3. looks_like_file_list() 正例与反例 —— 判定从严，避免把普通多行文本误判成文件列表。
4. 回归：普通文本仍走 clip_write()，clip_read() 不受影响。

关键约束：本方案**不改数据格式**。记录里存的仍然只是路径文本，
老版本与共用同一数据文件的 C 版读到的都是普通文本，互不影响。

注意：本机可能开着 ClawBoard 实例（持续轮询剪贴板），会短暂占用剪贴板导致
EmptyClipboard 失败。所以写入统一用「重试 + 回读校验」，避免把环境占用误判成代码缺陷。
"""
import os
import struct
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clawboard.clipboard import (clip_read, clip_write, clip_read_files,
                                 clip_write_files, build_hdrop,
                                 looks_like_file_list)

OK = True
LOG = []
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def check(name, cond, extra=''):
    global OK
    if not cond:
        OK = False
    LOG.append('%s  %s%s' % ('OK  ' if cond else 'FAIL', name,
                             ('  ' + extra) if extra else ''))


def norm(ps):
    return [p.replace('/', '\\') for p in ps]


def set_and_confirm(paths, tries=40):
    """写入 CF_HDROP 并回读确认（应对在场 ClawBoard 实例的剪贴板占用）。"""
    for _ in range(tries):
        if clip_write_files(paths):
            got = clip_read_files()
            if norm(got) == norm(paths):
                return True, got
        time.sleep(0.05)
    return False, clip_read_files()


# 造两个真实存在的文件，供 looks_like_file_list 使用（它要求路径真实存在）
tmpdir = tempfile.mkdtemp(prefix='cb_t37_')
real1 = os.path.join(tmpdir, '真实文件一.txt')
real2 = os.path.join(tmpdir, '带空格 的文件二.log')
for _p in (real1, real2):
    with open(_p, 'w', encoding='utf-8') as f:
        f.write('x')

# ---- 1. build_hdrop 字节结构 ----
try:
    raw = build_hdrop([r'C:\a b\c.txt', r'D:\中 文\x.png'])
    pfiles = struct.unpack_from('<I', raw, 0)[0]
    fwide = struct.unpack_from('<I', raw, 16)[0]
    body = raw[20:]
    check('build_hdrop 头部 pFiles=20', pfiles == 20, 'pFiles=%d' % pfiles)
    check('build_hdrop fWide=1', fwide == 1, 'fWide=%d' % fwide)
    check('build_hdrop 以双 NUL 结尾', body.endswith(b'\x00\x00\x00\x00'),
          repr(body[-6:]))
    decoded = body.decode('utf-16-le')
    check('build_hdrop 路径序列正确（逐条 NUL 分隔 + 双 NUL 收尾）',
          decoded == 'C:\\a b\\c.txt\x00D:\\中 文\\x.png\x00\x00', repr(decoded))
except Exception as e:
    check('build_hdrop 字节结构', False, repr(e))

# ---- 2. clip_write_files → clip_read_files 往返 ----
try:
    multi = [real1, real2, os.path.join(ROOT, 'clawboard', 'clipboard.py')]
    ok, got = set_and_confirm(multi)
    check('clip_write_files 多条（含中文与空格）往返一致',
          ok and norm(got) == norm(multi), 'got=%r' % (got,))
except Exception as e:
    check('clip_write_files 多条往返', False, repr(e))

try:
    ok1, got1 = set_and_confirm([real1])
    check('clip_write_files 单条往返一致',
          ok1 and norm(got1) == norm([real1]), 'got=%r' % (got1,))
except Exception as e:
    check('clip_write_files 单条往返', False, repr(e))

# ---- 3. looks_like_file_list 正例 ----
check('正例：两条真实存在的绝对路径',
      looks_like_file_list(real1 + '\n' + real2) is True)
check('正例：单条真实路径', looks_like_file_list(real1) is True)
check('正例：带前后空行与缩进也能识别',
      looks_like_file_list('\n  ' + real1 + '  \n\n' + real2 + '\n') is True)
check('正例：文件夹也算', looks_like_file_list(tmpdir) is True)

# ---- 4. 反例 ----
check('反例：普通中文文本', looks_like_file_list('你好，这是一段普通文本') is False)
check('反例：多行普通文本', looks_like_file_list('第一行\n第二行\n第三行') is False)
check('反例：不存在的绝对路径',
      looks_like_file_list(r'C:\这个目录肯定不存在_cb_t37\x.txt') is False)
check('反例：相对路径', looks_like_file_list('clawboard/clipboard.py') is False)
check('反例：一行存在一行不存在',
      looks_like_file_list(real1 + '\n' + r'C:\不存在_cb_t37.txt') is False)
check('反例：超过 50 行', looks_like_file_list('\n'.join([real1] * 51)) is False)
check('反例：代码片段', looks_like_file_list('def f():\n    return 1') is False)
check('反例：网址', looks_like_file_list('https://github.com/pay-and-gain/ClawBoard') is False)
check('边界：空字符串', looks_like_file_list('') is False)
check('边界：None', looks_like_file_list(None) is False)
check('边界：纯空白', looks_like_file_list('   \n\t\n') is False)

# ---- 5. 回归：普通文本仍走 clip_write ----
try:
    txt = 'hello 这是一段普通文本 cb_t37'
    written = False
    for _ in range(40):
        if clip_write(txt):
            if clip_read() == txt:
                written = True
                break
        time.sleep(0.05)
    check('回归：普通文本写入/读回正常', written, 'written=%s' % written)
    check('回归：普通文本之后 clip_read_files 为空', clip_read_files() == [],
          '%r' % (clip_read_files(),))
except Exception as e:
    check('回归：普通文本', False, repr(e))

# 清理临时文件
try:
    for _p in (real1, real2):
        os.remove(_p)
    os.rmdir(tmpdir)
except Exception:
    pass

_out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_t37.out')
with open(_out, 'w', encoding='utf-8') as f:
    f.write('\n'.join(LOG) + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))
print('\n'.join(LOG), flush=True)
print('全部通过' if OK else '有失败项', flush=True)
os._exit(0)
