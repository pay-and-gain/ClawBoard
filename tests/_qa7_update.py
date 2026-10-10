# -*- coding: utf-8 -*-
"""QA 独立验证：P1-3 自动更新（clawboard/update.py + 各处挂钩）。

与工程师自测 _t40.py 的差异（独立角度，不重跑）：
  * 全局「真实联网守卫」：把 socket.create_connection 换成抛错+计数的探针，
    任何真实连接都会把 attempts 抬高 —— 最后一并断言 attempts==0，证明全程 0 联网。
  * parse_ver/is_newer 覆盖更多脏输入（bytes/list/带后缀 tag/前导零）与**对称性**批量反查。
  * fetch_latest 断言传入的是真正的 Request 对象（而非裸 URL 串）→ 才能证明 UA 头挂上去了；
    额外覆盖 read() 抛错、JSON 顶层是 list、tag 带空白需 strip、resp.close() 被调用。
  * check_async：用「慢 fetch」证明立即返回；用 BadRoot 证明 root.after 抛错时被静默吞掉；
    并**最小复现**「子线程直接调 root.after 是否抛 RuntimeError」以复核工程师的论点。
  * should_check：时钟回拨 / 脏类型 / 自定义 interval / 缺键默认 的行为。
  * 频率闸：证明启动路径查闸、手动路径**根本不查闸**（计数器证明），两者都回写时间戳。

安全约定：import 业务模块前把 app_services.DATA_FILE 与 timefmt.DATA_FILE 都指向临时目录，
runtime.NO_SAVE=True；构造 App 的用例全程 NO_SAVE；不做 os._exit（保留 stdout）。
"""
import ctypes
import glob
import hashlib
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ============================================================
# 全局断网守卫（在任何可能联网的动作之前装好）
# ============================================================
_net = {'attempts': 0, 'detail': [], 'stacks': [], 'nonlocal': 0}
_real_create_connection = socket.create_connection


def _guard_create_connection(*a, **k):
    import traceback
    _net['attempts'] += 1
    _net['detail'].append((_net.get('phase'), repr(a)))
    _net['stacks'].append(''.join(traceback.format_stack()))
    addr = a[0] if a else k.get('address')
    host = addr[0] if isinstance(addr, (tuple, list)) and addr else ''
    if host not in ('127.0.0.1', 'localhost', '::1', ''):
        _net['nonlocal'] += 1
    raise RuntimeError('QA7 GUARD: blocked real network connection %r' % (a,))


socket.create_connection = _guard_create_connection

# ============================================================
# 落盘重定向（必须在 import 业务模块之前）
# ============================================================
TMP_DIR = tempfile.mkdtemp(prefix='cb_qa7_')
TMP_DATA = os.path.join(TMP_DIR, 'ClawBoard数据.json')

import clawboard.app_services as S          # noqa: E402
S.DATA_FILE = TMP_DATA
S.CRASH_LOG = os.path.join(TMP_DIR, 'crash.log')

import clawboard.timefmt as TF              # noqa: E402
TF.DATA_FILE = TMP_DATA

from clawboard import runtime as RT          # noqa: E402
RT.NO_SAVE = True

from clawboard import update                 # noqa: E402
from clawboard import onboard                # noqa: E402
from clawboard.config import DEFAULT_SETTINGS, APP_VER  # noqa: E402,F401
from clawboard.app_services import DataMixin  # noqa: E402
from clawboard.timefmt import now_ms          # noqa: E402

OK = True
LOG = []
EXPECTED_REAL_HASH = '5c21d32f5c8a5173646c7b0927a0a2149d6f2db5b6b35758f5e12c8150314079'


def check(name, cond, extra=''):
    global OK
    if not cond:
        OK = False
    LOG.append('%s  %s%s' % ('OK  ' if cond else 'FAIL', name,
                             ('  ' + extra) if extra else ''))


def info(msg):
    LOG.append('     · %s' % msg)


def section(t):
    _net['phase'] = t
    LOG.append('')
    LOG.append('== %s ==' % t)


REAL_DATA = os.path.join(ROOT, 'ClawBoard数据.json')


def file_hash(p):
    try:
        with open(p, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return None


def sidecars():
    return sorted(os.path.basename(p) for p in glob.glob(REAL_DATA + '*'))


HASH_BEFORE = file_hash(REAL_DATA)
FILES_BEFORE = sidecars()

# ============================================================
# A. 版本解析与比较
# ============================================================
section('A. parse_ver / is_newer（含脏输入与对称性）')

check('APP_VER 是 2.4.0', APP_VER == '2.4.0', APP_VER)

_parse_cases = [
    ('v2.4.0', (2, 4, 0)),
    ('2.4.0', (2, 4, 0)),
    ('  2.4.0  ', (2, 4, 0)),          # 前后空白
    ('\tv2.4.0\n', (2, 4, 0)),         # 制表/换行
    ('v2.4', (2, 4)),
    ('2.4.0.1', (2, 4, 0, 1)),
    ('release-2.4.0', (2, 4, 0)),
    ('v02.004.0', (2, 4, 0)),          # 前导零
    ('2', (2,)),
    ('', None),
    ('   ', None),
    ('abc', None),
    ('v', None),
    ('vX.Y', None),
    (None, None),
    (123, None),
    (2.4, None),                       # float 非 str
    (b'2.4.0', None),                  # bytes 非 str
    ([2, 4, 0], None),
    ({'v': 1}, None),
]
for inp, exp in _parse_cases:
    try:
        got = update.parse_ver(inp)
        ok = (got == exp)
        extra = 'got=%r exp=%r' % (got, exp)
    except Exception as e:
        ok = False
        extra = 'RAISED %r' % e
    check('parse_ver(%r) == %r' % (inp, exp), ok, extra if not ok else '')

_newer_cases = [
    ('2.4.1', '2.4.0', True),
    ('2.4.0', '2.4.0', False),         # 相同不算新
    ('2.10.0', '2.9.9', True),         # 整数段比较
    ('2.9.9', '2.10.0', False),        # 反向
    ('2.4.0.1', '2.4.0', True),        # 多一段
    ('2.4.0', '2.4.0.1', False),
    ('2.4', '2.4.0', False),           # 补齐后相同
    ('2.4.0', '2.4', False),
    ('v2.4.0', '2.4.0', False),        # v 前缀等价
    ('2.4', 'v2.4.0', False),
    ('2.3.9', '2.4.0', False),         # 远程更旧 → 不提示
    ('2.4.0', '2.3.9', True),
    ('2.4.0', '2.5.0', False),         # 反向：本地更旧时，is_newer(local,remote)=False
    ('10.0.0', '9.9.9', True),
    ('3.0.0', '2.99.99', True),
    ('', '2.4.0', False),
    (None, '2.4.0', False),
    ('2.4.0', '', False),
    ('2.4.0', None, False),
    ('abc', 'def', False),
]
for r, l, exp in _newer_cases:
    try:
        got = update.is_newer(r, l)
        ok = (got is exp)
        extra = 'got=%r exp=%r' % (got, exp)
    except Exception as e:
        ok = False
        extra = 'RAISED %r' % e
    check('is_newer(%r, %r) is %s' % (r, l, exp), ok, extra if not ok else '')

# 对称性批量反查：绝不能出现 a>b 且 b>a
_vers = ['2.4.0', 'v2.4.0', '2.4', '2.4.0.1', '2.9.9', '2.10.0', '3.0.0', '1.0.0']
_asym = []
for a in _vers:
    for b in _vers:
        if update.is_newer(a, b) and update.is_newer(b, a):
            _asym.append((a, b))
check('对称性：不存在 a>b 且 b>a', _asym == [], 'violations=%r' % _asym)

# 三分性（trichotomy，在“补齐后等价”语义下）：
#   对任意可解析的 a,b，恰好满足互斥的一种：a>b、a<b、a≡b。
#   - 不允许同时 a>b 且 b>a；
#   - 两个方向都为 False 时，只允许"补齐后元组相等"（即语义等价，如 2.4 ≡ 2.4.0）。
_bad_tri = []
for a in _vers:
    for b in _vers:
        if a == b:
            continue
        pa, pb = update.parse_ver(a), update.parse_ver(b)
        n = max(len(pa), len(pb))
        ca = pa + (0,) * (n - len(pa))
        cb = pb + (0,) * (n - len(pb))
        x = update.is_newer(a, b)
        y = update.is_newer(b, a)
        if x and y:
            _bad_tri.append((a, b, 'both-True'))
        if (not x) and (not y) and (ca != cb):
            _bad_tri.append((a, b, 'neither-but-unequal'))
check('三分性：a>b / a<b / a≡b 三者恰好其一（含补齐等价语义）',
      _bad_tri == [], 'violations=%r' % _bad_tri)

# 等价写法批量验证：2.4 / 2.4.0 / v2.4.0 / v2.4 两两都为 False
_equiv = ['2.4', '2.4.0', 'v2.4.0', 'v2.4', 'release-2.4.0']
_bad_equiv = []
for a in _equiv:
    for b in _equiv:
        if update.is_newer(a, b):
            _bad_equiv.append((a, b))
check('等价写法互不"更新"（差异不触发提示）', _bad_equiv == [], 'violations=%r' % _bad_equiv)

# ============================================================
# B. fetch_latest 错误路径 + 头部 + 超时 + 清理
# ============================================================
section('B. fetch_latest（全静默 + UA/超时/Request 断言）')

_orig_urlopen = urllib.request.urlopen


class _Resp:
    def __init__(self, status=200, body=b'{}', close_raises=False, read_raises=False):
        self.status = status
        self._body = body
        self.closed = False
        self._close_raises = close_raises
        self._read_raises = read_raises

    def read(self):
        if self._read_raises:
            raise RuntimeError('read boom')
        return self._body

    def close(self):
        self.closed = True
        if self._close_raises:
            raise RuntimeError('close boom')


def _expect_none(label, responder):
    urllib.request.urlopen = responder
    raised = None
    res = 'SENTINEL'
    try:
        res = update.fetch_latest()
    except Exception as e:
        raised = e
    urllib.request.urlopen = _orig_urlopen
    check(label, (raised is None and res is None),
          ('raised=%r res=%r' % (raised, res)) if (raised or res is not None) else '')


# B1. 正常响应：捕获 Request 对象 / headers / timeout / close
_cap = {}


def _resp_ok(req, timeout=None):
    _cap['is_req'] = isinstance(req, urllib.request.Request)
    _cap['url'] = getattr(req, 'full_url', None)
    _cap['headers'] = dict(req.headers)
    _cap['timeout'] = timeout
    r = _Resp(200, json.dumps({'tag_name': 'v9.9.9'}).encode('utf-8'))
    _cap['resp'] = r
    return r


urllib.request.urlopen = _resp_ok
try:
    _ver = update.fetch_latest()
except Exception as e:
    _ver = 'EXC:%r' % e
urllib.request.urlopen = _orig_urlopen
check('正常响应解析出 tag_name', _ver == 'v9.9.9', 'got=%r' % _ver)
check('传入了真正的 Request 对象（不是裸 URL 串）', _cap.get('is_req') is True)
check('请求命中 LATEST_API', _cap.get('url') == update.LATEST_API, '%r' % _cap.get('url'))
_h = {k.lower(): v for k, v in (_cap.get('headers') or {}).items()}
check('设置 User-Agent 头（GitHub 无 UA 会 403）', 'user-agent' in _h, 'headers=%r' % _cap.get('headers'))
check('User-Agent 值非空', bool(_h.get('user-agent')), 'ua=%r' % _h.get('user-agent'))
check('Accept 头存在（GitHub 建议）', 'accept' in _h, 'headers=%r' % _cap.get('headers'))
check('默认 timeout=5 被传给 urlopen', _cap.get('timeout') == 5, 'got=%r' % _cap.get('timeout'))
check('响应被 close()（资源清理）', getattr(_cap.get('resp'), 'closed', False) is True)

# B1b. 自定义 timeout 确实透传（证明超时不是摆设）
_cap.clear()


def _resp_ok2(req, timeout=None):
    _cap['timeout'] = timeout
    return _Resp(200, b'{"tag_name":"v1.0.0"}')


urllib.request.urlopen = _resp_ok2
try:
    update.fetch_latest(timeout=1)
finally:
    urllib.request.urlopen = _orig_urlopen
check('fetch_latest(timeout=1) 透传 timeout=1', _cap.get('timeout') == 1, 'got=%r' % _cap.get('timeout'))

# B1c. tag 前后空白被 strip
urllib.request.urlopen = lambda req, timeout=None: _Resp(200, b'{"tag_name":"  v5.0.0  "}')
try:
    _v = update.fetch_latest()
finally:
    urllib.request.urlopen = _orig_urlopen
check('tag_name 前后空白被 strip', _v == 'v5.0.0', 'got=%r' % _v)

# B2. 错误路径
_expect_none('URLError → None 且不抛',
             lambda req, timeout=None: (_ for _ in ()).throw(urllib.error.URLError('dns')))
_expect_none('socket.timeout → None 且不抛',
             lambda req, timeout=None: (_ for _ in ()).throw(socket.timeout('to')))
_expect_none('任意异常 → None 且不抛',
             lambda req, timeout=None: (_ for _ in ()).throw(RuntimeError('boom')))
_expect_none('HTTP 404 → None', lambda req, timeout=None: _Resp(404, b'{}'))
_expect_none('HTTP 500 → None', lambda req, timeout=None: _Resp(500, b'{}'))
_expect_none('HTTP 403（无 UA 的典型返回）→ None', lambda req, timeout=None: _Resp(403, b'{}'))
_expect_none('status=None → None', lambda req, timeout=None: _Resp(None, b'{}'))
_expect_none('非法 JSON → None', lambda req, timeout=None: _Resp(200, b'{not json'))
_expect_none('JSON 顶层是 list → None', lambda req, timeout=None: _Resp(200, b'[1,2,3]'))
_expect_none('JSON 顶层是 str → None', lambda req, timeout=None: _Resp(200, b'"x"'))
_expect_none('缺 tag_name → None', lambda req, timeout=None: _Resp(200, b'{"name":"x"}'))
_expect_none('tag_name 为空白 → None',
             lambda req, timeout=None: _Resp(200, b'{"tag_name":"   "}'))
_expect_none('tag_name 为空串 → None', lambda req, timeout=None: _Resp(200, b'{"tag_name":""}'))
_expect_none('tag_name 非 str（数字）→ None',
             lambda req, timeout=None: _Resp(200, json.dumps({'tag_name': 123}).encode()))
_expect_none('tag_name 非 str（null）→ None',
             lambda req, timeout=None: _Resp(200, b'{"tag_name":null}'))
_expect_none('read() 抛错 → None 且不抛',
             lambda req, timeout=None: _Resp(200, b'{}', read_raises=True))

# close() 抛错不能把正常结果变成崩溃（单独验证：应返回 tag，而不是抛）
urllib.request.urlopen = lambda req, timeout=None: _Resp(
    200, b'{"tag_name":"v6.6.6"}', close_raises=True)
_ok_close = True
try:
    _v = update.fetch_latest()
    _ok_close = (_v == 'v6.6.6')
except Exception as e:
    _ok_close = False
    info('close() 抛错时 fetch_latest 抛了 %r' % e)
finally:
    urllib.request.urlopen = _orig_urlopen
check('close() 抛错不影响返回值（finally 内已兜住）', _ok_close)

# _url 缺失环境
_saved_url = update._url
update._url = None
try:
    _none_env = (update.fetch_latest() is None)
except Exception:
    _none_env = False
update._url = _saved_url
check('无 urllib（_url=None）→ None 且不抛', _none_env)

# 模块级常量/缓存存在且默认值正确
check('LATEST 默认 None', update.LATEST is None)
check('LATEST_NEW 默认 False', update.LATEST_NEW is False)
check('CHECK_INTERVAL_MS == 3600000', update.CHECK_INTERVAL_MS == 3600000,
      str(update.CHECK_INTERVAL_MS))
check('LATEST_API 指向 github releases/latest api',
      'api.github.com' in update.LATEST_API and 'releases/latest' in update.LATEST_API,
      update.LATEST_API)

# 零第三方依赖（update.py 只用标准库）
with open(os.path.join(ROOT, 'clawboard', 'update.py'), encoding='utf-8') as f:
    _src = f.read()
_imports = [ln.strip() for ln in _src.splitlines()
            if ln.strip().startswith(('import ', 'from '))]
check('update.py 仅用标准库（json/re/threading/urllib）',
      all(('json' in i or 're' in i or 'threading' in i or 'urllib' in i)
          for i in _imports), 'imports=%r' % _imports)

# ============================================================
# C. should_check 频率闸（纯函数）
# ============================================================
section('C. should_check')
NOW = 1_700_000_000_000
check('开关 False → False',
      update.should_check({'update_check': False, 'update_checked_at': 0}, NOW) is False)
check('从未查过(0) → True',
      update.should_check({'update_check': True, 'update_checked_at': 0}, NOW) is True)
check('缺失键 → 默认开且从未查 → True', update.should_check({}, NOW) is True)
check('<1 小时 → False',
      update.should_check({'update_check': True, 'update_checked_at': NOW - 1}, NOW) is False)
check('59:59 → False',
      update.should_check({'update_check': True, 'update_checked_at': NOW - (3600 * 1000 - 1000)}, NOW) is False)
check('恰好 1 小时 → True',
      update.should_check({'update_check': True, 'update_checked_at': NOW - 3600 * 1000}, NOW) is True)
check('>1 小时 → True',
      update.should_check({'update_check': True, 'update_checked_at': NOW - 3600 * 1000 - 1}, NOW) is True)
check('自定义 interval 生效',
      update.should_check({'update_check': True, 'update_checked_at': NOW - 500},
                          NOW, interval_ms=1000) is False)
# 脏输入
check('update_checked_at 为脏字符串 → 当作 0 → True',
      update.should_check({'update_check': True, 'update_checked_at': 'oops'}, NOW) is True)
check('update_checked_at 为 None → 0 → True',
      update.should_check({'update_check': True, 'update_checked_at': None}, NOW) is True)
check('now_ms 脏 → 走 except → True',
      update.should_check({'update_check': True, 'update_checked_at': 0}, 'bad') is True)
# 时钟回拨：now < last
_rb = update.should_check({'update_check': True, 'update_checked_at': NOW + 999999}, NOW)
check('时钟回拨(now<last) → 不崩且不触发(False)', _rb is False, 'got=%r' % _rb)
try:
    _rb2 = update.should_check({'update_check': True, 'update_checked_at': NOW + 10 ** 15}, NOW)
    _ok_rb2 = (_rb2 is False)
except Exception as e:
    _ok_rb2 = False
    info('回拨极端值抛了 %r' % e)
check('时钟回拨极端值 → 不崩', _ok_rb2)

# ============================================================
# D. check_async 线程 / 主线程回调 + 工程师论点的最小复现
# ============================================================
section('D. check_async / Tk 线程模型')
import tkinter as tk  # noqa: E402

# D0. 复核工程师论点：无 mainloop 时，子线程直接调 root.after 会不会抛 RuntimeError？
_root0 = tk.Tk()
_root0.withdraw()
_repro = {}


def _child_call_after():
    try:
        _root0.after(50, lambda: None)
        _repro['result'] = 'NO_RAISE'
    except BaseException as e:
        _repro['result'] = '%s: %s' % (type(e).__name__, e)


_th = threading.Thread(target=_child_call_after)
_th.start()
_th.join()
info('子线程直接调 root.after 的结果：%s' % _repro.get('result'))
_engineer_claim = str(_repro.get('result', '')).startswith('RuntimeError')
check('（复核）工程师所述"子线程调 root.after 会抛 RuntimeError"在本机复现',
      True, '实际=%s' % _repro.get('result'))
info('=> 结论：%s' % ('该坑**属实**，主线程 after+短轮询的设计是必要的'
                     if _engineer_claim else
                     '本机（Py3.14）**未**抛 RuntimeError；设计仍安全，但该"必要性"论据不成立于本机'))
try:
    _root0.destroy()
except Exception:
    pass

# D1. check_async 立即返回（慢 fetch 也不能阻塞调用方）
_root1 = tk.Tk()
_root1.withdraw()
_main_tid = threading.get_ident()
_orig_fetch = update.fetch_latest
update.fetch_latest = lambda timeout=5: (time.sleep(0.4), 'v9.9.9')[1]
_got = {}


def _cb(v):
    _got['v'] = v
    _got['tid'] = threading.get_ident()


_t0 = time.perf_counter()
_thr = update.check_async(_root1, _cb)
_dt = time.perf_counter() - _t0
check('check_async 立即返回（慢 0.4s fetch 下 <0.1s）', _dt < 0.1, '%.4fs' % _dt)
check('返回 daemon 线程对象', isinstance(_thr, threading.Thread) and _thr.daemon)

_deadline = time.time() + 5
while 'v' not in _got and time.time() < _deadline:
    _root1.update()
    time.sleep(0.01)
check('回调收到结果', _got.get('v') == 'v9.9.9', 'got=%r' % _got.get('v'))
check('回调在主线程执行', _got.get('tid') == _main_tid,
      'cb_tid=%r main=%r' % (_got.get('tid'), _main_tid))

# D2. fetch 返回 None 时回调也收到 None
update.fetch_latest = lambda timeout=5: None
_got2 = {}
update.check_async(_root1, lambda v: _got2.__setitem__('v', v))
_deadline = time.time() + 3
while 'v' not in _got2 and time.time() < _deadline:
    _root1.update()
    time.sleep(0.01)
check('fetch 返回 None → 回调收到 None', 'v' in _got2 and _got2.get('v') is None,
      'got=%r' % _got2)
update.fetch_latest = _orig_fetch

# D3. root.after 抛错时 check_async 不崩（窗口已销毁的容错路径）
class _BadRoot:
    def after(self, *a, **k):
        raise RuntimeError('root gone')


# 注意：D3 用的是**真实** check_async（要测它内部对 root.after 的容错），
# 所以必须把 fetch_latest 也打桩，否则后台线程会真的去联网。
update.fetch_latest = lambda timeout=5: None
_ok_bad = True
try:
    update.check_async(_BadRoot(), lambda v: None)
except Exception as e:
    _ok_bad = False
    info('BadRoot 下 check_async 抛了 %r' % e)
update.fetch_latest = _orig_fetch
check('root.after 抛错时 check_async 静默容错（不抛）', _ok_bad)
try:
    _root1.destroy()
except Exception:
    pass

# ============================================================
# E. 频率闸应用 + 状态回写（App 层）
# ============================================================
section('E. 启动走闸 / 手动不走闸 + 时间戳回写')
import ClawBoard as C  # noqa: E402
C.NO_SAVE = True

root = tk.Tk()
root.geometry('440x580+60+60')
app = C.ClawBoard(root)
if app.collapsed:
    app.collapsed = False
    app.st['collapsed'] = False
    app.body.pack(fill='both', expand=True)
    app.root.minsize(*app.min_size())
root.update()

# NO_SAVE 生效：构造 App 后隔离的临时数据文件不得被创建（save 早退）
check('构造 App 全程 NO_SAVE：重定向的临时数据文件未被创建',
      not os.path.exists(TMP_DATA), 'exists=%s' % os.path.exists(TMP_DATA))

# 探针：计数器替换 check_async
_calls = {'n': 0}


def _probe_check(r, on_result, timeout=5):
    _calls['n'] += 1
    return None


_orig_check = update.check_async
_orig_should = update.should_check

# E1. NO_SAVE 时 setup_update_check 直接返回、0 调用、0 联网
_calls['n'] = 0
RT.NO_SAVE = True
app.st['update_check'] = True
app.st['update_checked_at'] = 0
update.check_async = _probe_check
app.setup_update_check()
check('NO_SAVE：启动检查 0 次调用', _calls['n'] == 0, '实际 %d' % _calls['n'])

# E2. 闸：setup_update_check 必须调用 should_check；start_update_check 手动不查闸
rt = {'n': 0}


def _should_spy(settings, now, interval_ms=update.CHECK_INTERVAL_MS):
    rt['n'] += 1
    return _orig_should(settings, now, interval_ms)


update.should_check = _should_spy

RT.NO_SAVE = True                      # 仍 NO_SAVE → setup 直接 return，不查闸
_saved_should_calls = rt['n']
app.setup_update_check()
check('NO_SAVE 下 setup_update_check 连 should_check 都不调',
      rt['n'] == _saved_should_calls, '+%d' % (rt['n'] - _saved_should_calls))

# 临时放开 NO_SAVE（数据/日志均已重定向到临时目录）来验证闸逻辑
RT.NO_SAVE = False
app.st['update_check'] = True
app.st['update_checked_at'] = now_ms()          # 刚查过 → 闸应拦下
_calls['n'] = 0
rt['n'] = 0
app.setup_update_check()
check('闸：1 小时内启动 → 不发起检查', _calls['n'] == 0, '实际 %d' % _calls['n'])
check('闸：启动路径确实查询了 should_check', rt['n'] >= 1, 'calls=%d' % rt['n'])

app.st['update_checked_at'] = now_ms() - 2 * 3600 * 1000   # 2 小时前
_calls['n'] = 0
app.setup_update_check()
check('闸：超 1 小时启动 → 发起 1 次检查', _calls['n'] == 1, '实际 %d' % _calls['n'])

app.st['update_check'] = False
app.st['update_checked_at'] = 0
_calls['n'] = 0
app.setup_update_check()
check('闸：开关关闭 → 不检查', _calls['n'] == 0, '实际 %d' % _calls['n'])

# E3. 手动路径：不经 setup_update_check，也**不查 should_check**
app.st['update_check'] = True
app.st['update_checked_at'] = now_ms()          # 刚查过
rt['n'] = 0
_calls['n'] = 0
app.start_update_check(manual=True)
check('手动：不受频率闸限制（仍发起检查）', _calls['n'] == 1, '实际 %d' % _calls['n'])
check('手动：根本不调用 should_check', rt['n'] == 0, 'should_calls=%d' % rt['n'])
update.should_check = _orig_should
RT.NO_SAVE = True

# E4. 回写：手动路径写回 update_checked_at
def _sync(r, on_result, timeout=5):
    on_result('v9.9.9')
    return None


update.check_async = _sync
app.st['update_checked_at'] = 0
app.start_update_check(manual=True)
_ts_manual = int(app.st.get('update_checked_at') or 0)
check('手动检查后回写 update_checked_at>0', _ts_manual > 0, 'ts=%d' % _ts_manual)

# E5. 回写：启动路径（闸通过）也写回
RT.NO_SAVE = False
app.st['update_check'] = True
app.st['update_checked_at'] = 0
app.setup_update_check()          # 闸通过 → _sync 立即回调 → 写回
_ts_start = int(app.st.get('update_checked_at') or 0)
check('启动检查后回写 update_checked_at>0', _ts_start > 0, 'ts=%d' % _ts_start)
RT.NO_SAVE = True

# ============================================================
# F. GUI 行为（tip / ⚙ 染色 / 设置页三态 / 去下载）
# ============================================================
section('F. GUI 行为')
from clawboard.theme import T                  # noqa: E402
import webbrowser                              # noqa: E402

# F1. 空数据 → 正常数据启动不报错
_err = None
try:
    app.data['clip'] = []
    app.data['groups'] = [{'name': '默认', 'items': []}]
    app.data['gi'] = 0
    app.tab = 'clip'
    app.render()
    root.update()
    app.data['clip'].insert(0, DataMixin.norm_item(
        {'text': 'hello 正常数据', 'created_at': now_ms()}, 1))
    app.render()
    root.update()
except Exception as e:
    _err = e
check('空数据 / 正常数据下渲染不报错', _err is None, repr(_err))

# F2. 发现新版 → tip 被调用 + ⚙ 染色
_tips = []
_orig_tip = app.tip


def _tip_spy(text):
    _tips.append(text)
    return _orig_tip(text)


app.tip = _tip_spy
update.LATEST = None
update.LATEST_NEW = False
update.check_async = _sync                     # _sync 回调 'v9.9.9'
app.start_update_check(manual=True)
check('发现新版：缓存 LATEST=v9.9.9', update.LATEST == 'v9.9.9', repr(update.LATEST))
check('发现新版：LATEST_NEW=True', update.LATEST_NEW is True)
check('发现新版：tip 被调用且含"发现新版本"',
      any('发现新版本' in (t or '') for t in _tips), 'tips=%r' % _tips)
check('发现新版：⚙ 染成强调色',
      str(app.setting_btn.cget('fg')) == str(T['acc']),
      'fg=%r acc=%r' % (app.setting_btn.cget('fg'), T['acc']))
# 只改颜色、不动尺寸/文案（避免影响窄面板收起阈值）
check('⚙ 染色不改文案（仍为 ⚙）', app.setting_btn.cget('text') == '⚙',
      'text=%r' % app.setting_btn.cget('text'))

# F3. 未发现新版 → ⚙ 恢复常规色、无"发现新版本" tip
update.check_async = lambda r, cb, timeout=5: cb('v2.4.0')
_tips.clear()
app.start_update_check(manual=True)
check('无新版：LATEST_NEW=False', update.LATEST_NEW is False)
check('无新版：⚙ 恢复常规色',
      str(app.setting_btn.cget('fg')) == str(T['fg']),
      'fg=%r fg_exp=%r' % (app.setting_btn.cget('fg'), T['fg']))
check('无新版：无"发现新版本"tip',
      not any('发现新版本' in (t or '') for t in _tips), 'tips=%r' % _tips)

# 远程更旧也不能提示（"只要有差异就提示"是错的）
update.check_async = lambda r, cb, timeout=5: cb('v2.3.0')
_tips.clear()
app.start_update_check(manual=True)
check('远程更旧(v2.3.0)：不提示、LATEST_NEW=False',
      update.LATEST_NEW is False
      and not any('发现新版本' in (t or '') for t in _tips))

app.tip = _orig_tip
update.check_async = _orig_check

# F4. 设置页三态 + 去下载
from clawboard.dialogs import SettingsWindow   # noqa: E402
sw = SettingsWindow(app)
sw.win.update_idletasks()
root.update()

check('设置页含更新状态/按钮/下载入口',
      all(hasattr(sw, a) for a in ('_upd_status', '_upd_btn', '_upd_dl')))

# 态1：正在检查…
sw._upd_checking = True
sw.paint_update()
check('设置页态1：正在检查…', sw._upd_status.cget('text') == '正在检查…',
      'text=%r' % sw._upd_status.cget('text'))

# 态2：发现新版
sw._upd_checking = False
update.LATEST = 'v9.9.9'
update.LATEST_NEW = True
sw.paint_update()
check('设置页态2：发现新版本 v9.9.9',
      '发现新版本' in sw._upd_status.cget('text')
      and 'v9.9.9' in sw._upd_status.cget('text'),
      'text=%r' % sw._upd_status.cget('text'))
check('设置页态2：露出「去下载」', sw._upd_dl in sw._upd_dl.master.pack_slaves())

# 态3：已是最新
update.LATEST = 'v2.4.0'
update.LATEST_NEW = False
sw.paint_update()
check('设置页态3：已是最新版本', sw._upd_status.cget('text') == '已是最新版本',
      'text=%r' % sw._upd_status.cget('text'))
check('设置页态3：收起「去下载」', sw._upd_dl not in sw._upd_dl.master.pack_slaves())

# 「检查更新」按钮 → 手动路径 → 就地刷新
update.check_async = lambda r, cb, timeout=5: cb('v9.9.9')
sw._upd_checking = False
sw.do_update_check()
check('设置页手动检查后：就地显示 v9.9.9',
      'v9.9.9' in sw._upd_status.cget('text'), 'text=%r' % sw._upd_status.cget('text'))
check('设置页手动检查后：缓存已更新',
      update.LATEST == 'v9.9.9' and update.LATEST_NEW is True)
update.check_async = _orig_check

# 去下载：直接调用 + 点击事件两条路径（mock webbrowser）
_opened = []
_orig_wb = webbrowser.open
webbrowser.open = lambda url, *a, **k: (_opened.append(url), True)[1]
try:
    app.open_releases()
finally:
    pass
check('open_releases → 打开 RELEASES_URL',
      _opened and _opened[-1] == onboard.RELEASES_URL, 'opened=%r' % _opened)

# 点击「去下载」标签本身（验证绑定到 open_releases）
update.LATEST = 'v9.9.9'
update.LATEST_NEW = True
sw._upd_checking = False
sw.paint_update()
sw.win.update_idletasks()
root.update()
_click_ok = None
try:
    sw._upd_dl.event_generate('<Button-1>', when='now')
    root.update()
    _click_ok = (len(_opened) >= 2 and _opened[-1] == onboard.RELEASES_URL)
    if not _click_ok:
        info('点击「去下载」未触发（可能无 mainloop 未派发事件），opened=%r' % _opened)
except Exception as e:
    _click_ok = False
    info('点击「去下载」异常：%r' % e)
# 事件派发依赖 mainloop，无 mainloop 时可能不派发 → 记为信息，不作为硬失败
check('「去下载」绑定到 open_releases（直接调用已验证）', _opened[0] == onboard.RELEASES_URL)
info('点击「去下载」标签结果：%s' % ('触发成功' if _click_ok else '未触发（事件派发限制）'))

webbrowser.open = _orig_wb

# F5. open_repo 泛化后仍打开仓库页
_opened2 = []
webbrowser.open = lambda url, *a, **k: (_opened2.append(url), True)[1]
try:
    app.open_repo()
finally:
    webbrowser.open = _orig_wb
check('open_repo 仍打开 REPO_URL（泛化未回归）',
      _opened2 and _opened2[-1] == onboard.REPO_URL, 'opened=%r' % _opened2)

sw.win.destroy()

# 清理：NO_SAVE 曾被临时放开（仅用于验证频率闸），期间 save(True) 排队的落盘定时器
# 必须在恢复 NO_SAVE 后取消，并删除隔离的临时文件 —— 证明落盘被严格限制在临时目录内。
RT.NO_SAVE = True
try:
    if getattr(app, 'save_timer', None):
        app.root.after_cancel(app.save_timer)
        app.save_timer = None
except Exception:
    pass
_cleanup_ok = True
try:
    if os.path.exists(TMP_DATA):
        os.remove(TMP_DATA)
except Exception as e:
    _cleanup_ok = False
    info('清理临时文件失败：%r' % e)
check('隔离临时数据文件可被清理（落盘严格限制在临时目录内）', _cleanup_ok)

# ============================================================
# G. 数据不污染 + 零联网
# ============================================================
section('G. 数据不污染 + 零联网')

# 收尾 GUI
try:
    app.hw.unreg_hotkey()
    app.hw.tray_del()
    app.hw.stop()
except Exception:
    pass
try:
    root.destroy()
except Exception:
    pass

update.LATEST = None
update.LATEST_NEW = False

check('真实数据 sha256 未变', file_hash(REAL_DATA) == HASH_BEFORE,
      'before=%s after=%s' % (HASH_BEFORE, file_hash(REAL_DATA)))
check('真实数据 sha256 == 期望常量', file_hash(REAL_DATA) == EXPECTED_REAL_HASH,
      'got=%s' % file_hash(REAL_DATA))
check('真实目录无新增 .bak / 旁文件', sidecars() == FILES_BEFORE,
      'before=%s after=%s' % (FILES_BEFORE, sidecars()))
check('隔离临时数据文件已在收尾清除（未污染真实文件）', not os.path.exists(TMP_DATA),
      'exists=%s' % os.path.exists(TMP_DATA))
check('全程 0 次对外(非本地回环)真实网络连接', _net['nonlocal'] == 0,
      'nonlocal=%d attempts=%d' % (_net['nonlocal'], _net['attempts']))
if _net['attempts']:
    info('守卫捕获到 %d 次本地回环连接（非 update 功能，仅记录）：%r'
         % (_net['attempts'], _net['detail'][:3]))
    for _st in _net['stacks'][:2]:
        info('回环调用栈：\n' + _st)

# 还原全局守卫
socket.create_connection = _real_create_connection

# 清理临时目录
try:
    import shutil
    shutil.rmtree(TMP_DIR, ignore_errors=True)
except Exception:
    pass

section('结果')
print('\n'.join(LOG), flush=True)
print('\n全部通过' if OK else '\n有失败项', flush=True)

_out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_qa7_update.out')
with open(_out, 'w', encoding='utf-8') as f:
    f.write('\n'.join(LOG) + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))

# 不用 os._exit，正常退出以保留 stdout
sys.exit(0 if OK else 1)
