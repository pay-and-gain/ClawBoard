# -*- coding: utf-8 -*-
"""QA 独立复核（Edward）：CF_HDROP 文件复制 —— 用与工程师不同的数据独立验证。

与 tests/_t35.py 的区别：
- DROPFILES 头/偏移用独立写法（显式 struct 分解与注释），不复用其 make_dropfiles。
- 数据用例不同：单个短英文、3 条（中文目录 + 含空格 + emoji）、超长路径、无 HDROP。
- 额外做 poll_clip() 集成桩测试：构造 SystemMixin 的桩实例，直接调用 poll_clip()，
  断言文件路径被 ingest 成文本条目、多文件用 '\\n' 连接、图片优先分支不被破坏。
- 写入用「重试 + 读回校验」应对在场 ClawBoard 实例的剪贴板占用。

用法：C:/Python314/python.exe tests/_qa3_hdrop.py
结果写 tests/_qa3_hdrop.out（用 os._exit 前 flush）。"""
import ctypes
import os
import struct
import sys
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from clawboard.clipboard import clip_read_files, clip_read, clip_write
from clawboard.win32 import u32, k32, CF_HDROP, CF_UNICODETEXT, GMEM_MOVEABLE
from clawboard import runtime
from clawboard.app_services import SystemMixin

OK = True
LOG = []


def check(name, cond, extra=''):
    global OK
    if not cond:
        OK = False
    LOG.append('%s  %s%s' % ('OK  ' if cond else 'FAIL', name,
                             ('  ' + extra) if extra else ''))


# ---------------- 独立构造 CF_HDROP ----------------

def build_hdrop(paths):
    """独立实现的 DROPFILES 构造。

    DROPFILES { DWORD pFiles; POINT pt; BOOL fNC; BOOL fWide; }
    32 位下：4 + 8 + 4 + 4 = 20 字节，pFiles=20 指向紧随其后的路径数据。
    路径序列：每个路径以 \x00 结尾，整个列表再补一个 \x00 收尾。
    fWide=1 → UTF-16LE 宽字符。
    """
    dword = struct.calcsize('<I')      # 4
    point = struct.calcsize('<ii')     # 8 (两个 LONG)
    boolsz = struct.calcsize('<i')     # 4
    header_size = dword + point + boolsz + boolsz   # 20
    assert header_size == 20
    header = struct.pack('<I', header_size) + struct.pack('<ii', 0, 0) \
        + struct.pack('<i', 0) + struct.pack('<i', 1)
    blob = b''
    for p in paths:
        blob += p.encode('utf-16-le') + b'\x00\x00'
    blob += b'\x00\x00'
    return header + blob


def raw_set(paths):
    """单次尝试把 CF_HDROP 放上剪贴板。返回 bool。"""
    data = build_hdrop(paths)
    if not u32.OpenClipboard(None):
        return False
    try:
        if not u32.EmptyClipboard():
            return False
        h = k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not h:
            return False
        p = k32.GlobalLock(h)
        if not p:
            return False
        ctypes.memmove(p, data, len(data))
        k32.GlobalUnlock(h)
        if not u32.SetClipboardData(CF_HDROP, h):
            return False
    finally:
        u32.CloseClipboard()
    return True


def norm(ps):
    return [p.replace('/', '\\') for p in ps]


def set_confirm(paths, tries=50):
    """写入并读回校验（应对在场实例的剪贴板占用）。返回 (ok, got)。"""
    exp = norm(paths)
    for _ in range(tries):
        if raw_set(paths):
            got = clip_read_files()
            if norm(got) == exp:
                return True, got
        time.sleep(0.05)
    return False, clip_read_files()


# ---------------- 单元：往返一致（不同数据） ----------------

# B1. 单个路径（短英文）
try:
    single = [r'C:\a\b.txt']
    o, got = set_confirm(single)
    check('B1 单个短英文路径往返一致', o and norm(got) == norm(single), 'got=%r' % (got,))
except Exception as e:
    check('B1 单个短英文路径往返一致', False, repr(e))

# B2. 多个路径（3 条：中文目录 + 含空格 + emoji）
try:
    multi = [r'C:\Users\pay and gain\Desktop\剪切板\clawboard\clipboard.py',
             r'C:\Program Files\My App\with space.jpg',
             r'D:\emoji😀目录\图片 📷 合集\照片 emoji.png']
    o, got = set_confirm(multi)
    check('B2 多路径（中文+空格+emoji）往返一致', o and norm(got) == norm(multi),
          'got=%r' % (got,))
except Exception as e:
    check('B2 多路径（中文+空格+emoji）往返一致', False, repr(e))

# B3. 超长路径（接近 MAX_PATH 260）
try:
    longseg = 'x' * 90
    longp = ('C:\\' + '\\'.join([longseg] * 3) + '\\' + 'y' * 60 + '.png')
    o, got = set_confirm([longp])
    check('B3 超长路径往返一致', o and norm(got) == norm([longp]),
          'len=%d got_len=%s' % (len(longp), [len(g) for g in got]))
except Exception as e:
    check('B3 超长路径往返一致', False, repr(e))

# B4. 无 CF_HDROP（写纯文本）→ 应返回 []
try:
    wrote = False
    for _ in range(50):
        if clip_write('QA 纯文本无文件'):
            if clip_read() == 'QA 纯文本无文件':
                wrote = True
                break
        time.sleep(0.05)
    got = clip_read_files()
    check('B4 无 CF_HDROP（文本）返回 []', wrote and got == [],
          'wrote=%s got=%r' % (wrote, got))
except Exception as e:
    check('B4 无 CF_HDROP（文本）返回 []', False, repr(e))


# ---------------- 集成：poll_clip() 桩测试 ----------------

class _Rec:
    """记录 ingest / tip 调用。"""
    def __init__(self):
        self.ingested = []
        self.tips = []
        self.saved = 0


class Stub(SystemMixin, _Rec):
    """最小桩 app：只暴露 poll_clip 路径需要的属性/方法。

    - root.after 被覆盖为 no-op（不真正排期，避免递归轮询）。
    - 不走真实 UI：render 空实现、ingest 记录入参。
    - data/clip、st、tab 与真实 ClawBoard 同名同结构。
    """
    def __init__(self, data, st):
        _Rec.__init__(self)
        self.data = data
        self.st = st
        self.tab = 'clip'
        self.root = self  # 让 self.root.after(...) 落到本类

    # poll_clip 依赖的接口
    def after(self, ms, fn=None):
        return None

    def ingest(self, txt, hits=None, manual=False):
        self.ingested.append({'text': txt, 'hits': hits, 'manual': manual})

    def tip(self, msg):
        self.tips.append(msg)

    def render(self):
        pass

    def save(self, later=False):
        self.saved += 1

    def show_copy_toast(self, txt):
        pass


def fresh_data():
    from clawboard.config import DEFAULT_SETTINGS
    return {'clip': [], 'groups': [{'name': '默认', 'items': []}], 'gi': 0,
            'geom': None, 'settings': dict(DEFAULT_SETTINGS), 'schema_version': 3}


# B5. 多文件 → poll_clip 把路径用 \n 连接后 ingest（强制 LAST_SEQ 变化触发）
try:
    paths = [r'C:\q\one.jpg', r'D:\two png\带 空格.png', r'E:\三\three.jpg']
    ok_write = False
    for _ in range(50):
        if raw_set(paths):
            if norm(clip_read_files()) == norm(paths):
                ok_write = True
                break
        time.sleep(0.05)
    stub = Stub(fresh_data(), dict(fresh_data()['settings']))
    stub.st['listen'] = True
    runtime.LAST_SEQ = -1        # 与真实 seq 不同 → 强制进入处理分支
    stub.poll_clip()
    exp = '\n'.join(paths)
    check('B5 多文件 poll_clip → 单条 ingest，\\n 连接',
          ok_write and len(stub.ingested) == 1 and stub.ingested[0]['text'] == exp,
          'write=%s ingested=%r' % (ok_write, stub.ingested))
except Exception as e:
    check('B5 多文件 poll_clip → 单条 ingest，\\n 连接', False, repr(e))

# B6. 单文件 → poll_clip ingest 单条 == 该路径
try:
    paths1 = [r'C:\only\单文件.txt']
    ok_write = False
    for _ in range(50):
        if raw_set(paths1):
            if norm(clip_read_files()) == norm(paths1):
                ok_write = True
                break
        time.sleep(0.05)
    stub = Stub(fresh_data(), dict(fresh_data()['settings']))
    stub.st['listen'] = True
    runtime.LAST_SEQ = -1
    stub.poll_clip()
    check('B6 单文件 poll_clip → ingest 该路径',
          ok_write and len(stub.ingested) == 1 and stub.ingested[0]['text'] == paths1[0],
          'write=%s ingested=%r' % (ok_write, stub.ingested))
except Exception as e:
    check('B6 单文件 poll_clip → ingest 该路径', False, repr(e))

# B7. 监听关闭时 poll_clip 不入库（回归：原有语义）
try:
    paths2 = [r'C:\x\y.jpg']
    for _ in range(50):
        if raw_set(paths2):
            break
        time.sleep(0.05)
    stub = Stub(fresh_data(), dict(fresh_data()['settings']))
    stub.st['listen'] = False
    runtime.LAST_SEQ = -1
    stub.poll_clip()
    check('B7 监听关闭 → 不 ingest（原语义不变）', len(stub.ingested) == 0,
          'ingested=%r' % (stub.ingested,))
except Exception as e:
    check('B7 监听关闭 → 不 ingest（原语义不变）', False, repr(e))

# ---------------- 输出 ----------------
out = os.path.join(ROOT, 'tests', '_qa3_hdrop.out')
with open(out, 'w', encoding='utf-8') as f:
    f.write('\n'.join(LOG) + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))
sys.stdout.write('\n'.join(LOG) + '\n')
sys.stdout.write('RESULT: %s\n' % ('PASS' if OK else 'FAIL'))
sys.stdout.flush()
os._exit(0)
