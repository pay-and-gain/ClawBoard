# -*- coding: utf-8 -*-
"""D. 回归与边界：纯文本仍入库；敏感词过滤链路不破；图片优先已另测。"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from clawboard.clipboard import clip_write, clip_read
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


class Stub(SystemMixin):
    def __init__(self, data, st):
        self.data = data
        self.st = st
        self.tab = 'clip'
        self.root = self
        self.ingested = []
        self.tips = []

    def after(self, ms, fn=None):
        return None

    def ingest(self, txt, hits=None, manual=False):
        self.ingested.append({'text': txt, 'hits': hits})

    def tip(self, msg):
        self.tips.append(msg)

    def render(self):
        pass

    def save(self, later=False):
        pass

    def show_copy_toast(self, txt):
        pass


def fresh():
    from clawboard.config import DEFAULT_SETTINGS
    return {'clip': [], 'groups': [{'name': '默认', 'items': []}], 'gi': 0,
            'geom': None, 'settings': dict(DEFAULT_SETTINGS), 'schema_version': 3}


def write_text(txt, tries=60):
    for _ in range(tries):
        if clip_write(txt) and clip_read() == txt:
            return True
        time.sleep(0.05)
    return False


# D1. 纯文本复制仍正常记录
try:
    t = '这是一段普通文本 QA-text-123'
    w = write_text(t)
    stub = Stub(fresh(), dict(fresh()['settings']))
    stub.st['listen'] = True
    stub.st['skip_sensitive'] = False
    runtime.LAST_SEQ = -1
    stub.poll_clip()
    check('D1 纯文本仍被 ingest 且内容一致',
          w and len(stub.ingested) == 1 and stub.ingested[0]['text'] == t,
          'ingested=%r' % (stub.ingested,))
except Exception as e:
    check('D1 纯文本仍被 ingest 且内容一致', False, repr(e))

# D2. 敏感词（手机号）：skip_sensitive=False → ingest 且带 hits
try:
    t = '联系方式 13800138000 请惠存'
    w = write_text(t)
    stub = Stub(fresh(), dict(fresh()['settings']))
    stub.st['listen'] = True
    stub.st['skip_sensitive'] = False
    runtime.LAST_SEQ = -1
    stub.poll_clip()
    ok = w and len(stub.ingested) == 1 and '手机号' in (stub.ingested[0]['hits'] or [])
    check('D2 敏感词 skip=False → ingest 且 hits 含手机号', ok,
          'ingested=%r' % (stub.ingested,))
except Exception as e:
    check('D2 敏感词 skip=False → ingest 且 hits 含手机号', False, repr(e))

# D3. 敏感词 skip=True → 不 ingest，仅 tip
try:
    t = '密码：abcd1234'
    w = write_text(t)
    stub = Stub(fresh(), dict(fresh()['settings']))
    stub.st['listen'] = True
    stub.st['skip_sensitive'] = True
    runtime.LAST_SEQ = -1
    stub.poll_clip()
    check('D3 敏感词 skip=True → 不入库，仅提示',
          w and len(stub.ingested) == 0 and len(stub.tips) >= 1,
          'ingested=%r tips=%r' % (stub.ingested, stub.tips))
except Exception as e:
    check('D3 敏感词 skip=True → 不入库，仅提示', False, repr(e))

# D4. 复制文件路径同时含敏感数字串 → 仍按文本走敏感词链路（不特殊对待）
try:
    t = r'C:\data\13800138000.jpg'
    w = write_text(t)
    stub = Stub(fresh(), dict(fresh()['settings']))
    stub.st['listen'] = True
    stub.st['skip_sensitive'] = False
    runtime.LAST_SEQ = -1
    stub.poll_clip()
    ok = w and len(stub.ingested) == 1 and stub.ingested[0]['text'] == t
    check('D4 含敏感数字的文本路径正常入库', ok, 'ingested=%r' % (stub.ingested,))
except Exception as e:
    check('D4 含敏感数字的文本路径正常入库', False, repr(e))

out = os.path.join(ROOT, 'tests', '_qa3_regress.out')
with open(out, 'w', encoding='utf-8') as f:
    f.write('\n'.join(LOG) + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))
sys.stdout.write('\n'.join(LOG) + '\nRESULT: %s\n' % ('PASS' if OK else 'FAIL'))
sys.stdout.flush()
os._exit(0)
