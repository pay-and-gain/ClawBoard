# -*- coding: utf-8 -*-
"""P1-3 自动更新（只提示 + 跳下载页）回归自测。

覆盖：
A. 设置与向后兼容：update_check 默认 True、update_checked_at 默认 0；
   validate 补默认 / 保留显式值 / 老数据（无新字段）兼容 / 非法值回退。
B. parse_ver / is_newer 边界：'v2.4.0' vs '2.4.0'、2.4.0<2.4.1、**2.10.0>2.9.9**、
   相同不算新、非法/空输入返回 False 且不抛。
C. should_check 频率闸：关闭开关 / 1 小时内 / 超过 1 小时。
D. fetch_latest：正常解析、**User-Agent 头确实设置**、timeout=5、
   URLError / socket.timeout / 非 200 / 非法 JSON / 缺 tag_name → 一律 None 且不抛。
E. check_async：**立即返回**（不阻塞）、回调在**主线程**执行、拿到结果。
F. GUI 闭环：启动检查的 NO_SAVE 守卫、频率闸（1 小时内跳过 / 超过则触发）、
   手动检查不受限、发现新版就地 tip + ⚙ 染色、无新版不染色、
   设置页三种状态就地反馈 + 「去下载」露出/收起、「去下载」打开 Release 页。
G. 数据不污染：真实 ClawBoard数据.json sha256 前后一致、无新增 .bak。

**全程 mock 掉网络**（urlopen / fetch_latest / check_async），绝不真的联网 —— 否则会拖慢/
不稳定。数据安全：import 业务模块前把 app_services.DATA_FILE 与 timefmt.DATA_FILE **两个**
都指向临时目录，并置 runtime.NO_SAVE / C.NO_SAVE = True。
"""
import ctypes
import glob
import hashlib
import json
import os
import socket
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

# ---- 重定向落盘目标（必须在 import 业务模块之前）----
TMP_DIR = tempfile.mkdtemp(prefix='cb_t40_')
TMP_DATA = os.path.join(TMP_DIR, 'ClawBoard数据.json')

import clawboard.app_services as S            # noqa: E402
S.DATA_FILE = TMP_DATA
S.CRASH_LOG = os.path.join(TMP_DIR, 'crash.log')

import clawboard.timefmt as TF                # noqa: E402
TF.DATA_FILE = TMP_DATA

from clawboard import runtime as RT           # noqa: E402
RT.NO_SAVE = True

from clawboard import update                  # noqa: E402
from clawboard import onboard                 # noqa: E402
from clawboard.config import DEFAULT_SETTINGS  # noqa: E402
from clawboard.app_services import DataMixin   # noqa: E402
from clawboard.timefmt import now_ms           # noqa: E402

OK = True
LOG = []


def check(name, cond, extra=''):
    global OK
    if not cond:
        OK = False
    LOG.append('%s  %s%s' % ('OK  ' if cond else 'FAIL', name,
                             ('  ' + extra) if extra else ''))


def section(t):
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
# A. 设置与向后兼容
# ============================================================
section('A. 设置与向后兼容')
check('update_check 在 DEFAULT_SETTINGS', 'update_check' in DEFAULT_SETTINGS)
check('update_check 默认 True', DEFAULT_SETTINGS.get('update_check') is True)
check('update_checked_at 在 DEFAULT_SETTINGS', 'update_checked_at' in DEFAULT_SETTINGS)
check('update_checked_at 默认 0', DEFAULT_SETTINGS.get('update_checked_at') == 0)

_v = DataMixin.validate({'clip': [], 'groups': [], 'settings': {}, 'schema_version': 3})
check('validate 补默认 update_check=True', _v['settings'].get('update_check') is True)
check('validate 补默认 update_checked_at=0', _v['settings'].get('update_checked_at') == 0)

_v2 = DataMixin.validate({'clip': [], 'groups': [],
                          'settings': {'update_check': False, 'update_checked_at': 123},
                          'schema_version': 3})
check('validate 保留显式值',
      _v2['settings'].get('update_check') is False
      and _v2['settings'].get('update_checked_at') == 123)

_v3 = DataMixin.validate({'clip': [], 'groups': [],
                          'settings': {'theme': 'dark', 'listen': True}, 'schema_version': 3})
check('老数据（无新字段）→ 兼容为默认',
      _v3['settings'].get('update_check') is True
      and _v3['settings'].get('update_checked_at') == 0)

_v4 = DataMixin.validate({'clip': [], 'groups': [],
                          'settings': {'update_checked_at': 'not-an-int'},
                          'schema_version': 3})
check('非法 update_checked_at 回退为 0', _v4['settings'].get('update_checked_at') == 0)

# ============================================================
# B. parse_ver / is_newer
# ============================================================
section('B. parse_ver / is_newer')
check("parse 'v2.4.0' → (2,4,0)", update.parse_ver('v2.4.0') == (2, 4, 0))
check("parse '2.4.0' → (2,4,0)", update.parse_ver('2.4.0') == (2, 4, 0))
check('带前缀的 tag 也能解析', update.parse_ver('release-2.4.0') == (2, 4, 0))
check('空串 → None', update.parse_ver('') is None)
check('非 str → None', update.parse_ver(None) is None and update.parse_ver(123) is None)
check('无数字 → None', update.parse_ver('vX.Y') is None)

check('2.4.1 > 2.4.0', update.is_newer('2.4.1', '2.4.0') is True)
check('2.4.0 不比 2.4.0 新', update.is_newer('2.4.0', '2.4.0') is False)
check("'v2.4.0' 不比 '2.4.0' 新（等价）", update.is_newer('v2.4.0', '2.4.0') is False)
check("'2.4.0' 不比 'v2.4.0' 新（等价）", update.is_newer('2.4.0', 'v2.4.0') is False)
check('2.10.0 > 2.9.9（按整数段比，不是字符串比）',
      update.is_newer('2.10.0', '2.9.9') is True)
check('2.4 < 2.4.0 视为相同（补齐 0）', update.is_newer('2.4', '2.4.0') is False)
check('2.4.0.1 > 2.4.0', update.is_newer('2.4.0.1', '2.4.0') is True)
check('旧于本地 → False', update.is_newer('2.3.9', '2.4.0') is False)
check('非法输入不抛且 False',
      update.is_newer('', '2.4.0') is False
      and update.is_newer(None, '2.4.0') is False
      and update.is_newer('2.4.0', '') is False
      and update.is_newer('abc', 'def') is False)

# ============================================================
# C. should_check 频率闸
# ============================================================
section('C. should_check 频率闸')
NOW = 1700000000000
check('开关关闭 → 不检查',
      update.should_check({'update_check': False, 'update_checked_at': 0}, NOW) is False)
check('从未查过（0）→ 检查',
      update.should_check({'update_check': True, 'update_checked_at': 0}, NOW) is True)
check('1 小时内查过 → 跳过',
      update.should_check({'update_check': True, 'update_checked_at': NOW - 1000}, NOW) is False)
check('恰好 1 小时 → 检查',
      update.should_check({'update_check': True, 'update_checked_at': NOW - 3600000}, NOW) is True)
check('超过 1 小时 → 检查',
      update.should_check({'update_check': True, 'update_checked_at': NOW - 3600001}, NOW) is True)

# ============================================================
# D. fetch_latest（全程 mock，不联网）
# ============================================================
section('D. fetch_latest')
_orig_urlopen = urllib.request.urlopen


class _Resp:
    def __init__(self, status=200, body=b'{}'):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def close(self):
        pass


def _install(responder):
    urllib.request.urlopen = responder


def _restore():
    urllib.request.urlopen = _orig_urlopen


# D1. 正常 + 捕获 headers / timeout
_cap = {}


def resp_ok(req, timeout=None):
    _cap['url'] = req.full_url
    _cap['headers'] = dict(req.headers)
    _cap['timeout'] = timeout
    return _Resp(200, json.dumps({'tag_name': 'v9.9.9'}).encode('utf-8'))


_install(resp_ok)
try:
    ver = update.fetch_latest()
except Exception as e:
    ver = 'EXC:%r' % e
_restore()
check('正常响应解析出 tag_name', ver == 'v9.9.9', 'got=%r' % ver)
check('请求命中 latest API', _cap.get('url') == update.LATEST_API, 'url=%r' % _cap.get('url'))
_hdr = {k.lower(): v for k, v in _cap.get('headers', {}).items()}
check('设置了 User-Agent 头（GitHub 无 UA 会 403）', 'user-agent' in _hdr,
      'headers=%r' % _cap.get('headers'))
check('User-Agent 非空', bool(_hdr.get('user-agent')), 'ua=%r' % _hdr.get('user-agent'))
check('timeout 默认 5s', _cap.get('timeout') == 5, 'got=%r' % _cap.get('timeout'))

# D2. 错误路径：一律 None 且不抛
def raise_urlerr(req, timeout=None):
    raise urllib.error.URLError('dns fail')


def raise_timeout(req, timeout=None):
    raise socket.timeout('timed out')


def raise_generic(req, timeout=None):
    raise RuntimeError('boom')


def resp_404(req, timeout=None):
    return _Resp(404, b'{}')


def resp_500(req, timeout=None):
    return _Resp(500, b'{}')


def resp_badjson(req, timeout=None):
    return _Resp(200, b'{not valid json')


def resp_notag(req, timeout=None):
    return _Resp(200, json.dumps({'name': 'x'}).encode('utf-8'))


def resp_emptytag(req, timeout=None):
    return _Resp(200, json.dumps({'tag_name': '   '}).encode('utf-8'))


def resp_nonstr_tag(req, timeout=None):
    return _Resp(200, json.dumps({'tag_name': 123}).encode('utf-8'))


def _expect_none(label, responder):
    _install(responder)
    ok = True
    try:
        r = update.fetch_latest()
        ok = (r is None)
    except Exception as e:
        ok = False
        LOG.append('   （%s 抛了 %r）' % (label, e))
    _restore()
    check(label, ok)


_expect_none('URLError → None 且不抛', raise_urlerr)
_expect_none('socket.timeout → None 且不抛', raise_timeout)
_expect_none('任意异常 → None 且不抛', raise_generic)
_expect_none('非 200（404）→ None', resp_404)
_expect_none('非 200（500）→ None', resp_500)
_expect_none('非法 JSON → None', resp_badjson)
_expect_none('缺 tag_name → None', resp_notag)
_expect_none('tag_name 为空白 → None', resp_emptytag)
_expect_none('tag_name 非字符串 → None', resp_nonstr_tag)

# _url 被换成 None（模拟极端环境）也不能抛
_saved_url = update._url
update._url = None
try:
    r_none = update.fetch_latest()
    _none_env_ok = (r_none is None)
except Exception:
    _none_env_ok = False
update._url = _saved_url
check('无 urllib 环境 → None 且不抛', _none_env_ok)

# ============================================================
# E. check_async（立即返回 + 主线程回调）
# ============================================================
section('E. check_async')
import tkinter as tk          # noqa: E402

_root0 = tk.Tk()
_main_tid = threading.get_ident()
_got = {}
_orig_fetch = update.fetch_latest
update.fetch_latest = lambda timeout=5: 'v7.7.7'


def _cb(v):
    _got['v'] = v
    _got['tid'] = threading.get_ident()


_t0 = time.perf_counter()
_th = update.check_async(_root0, _cb)
_dt = time.perf_counter() - _t0
check('check_async 立即返回（不阻塞）', _dt < 0.2, '%.4fs' % _dt)
check('返回 daemon 线程对象', isinstance(_th, threading.Thread) and _th.daemon)

for _ in range(200):
    _root0.update()
    if 'v' in _got:
        break
    time.sleep(0.01)
check('回调收到结果', _got.get('v') == 'v7.7.7', 'got=%r' % _got.get('v'))
check('回调在**主线程**执行', _got.get('tid') == _main_tid,
      'cb_tid=%r main=%r' % (_got.get('tid'), _main_tid))
update.fetch_latest = _orig_fetch
try:
    _root0.destroy()
except Exception:
    pass

# ============================================================
# F. GUI 闭环（app + 设置页）
# ============================================================
section('F. GUI 闭环')
import webbrowser          # noqa: E402
import ClawBoard as C      # noqa: E402
from clawboard.dialogs import SettingsWindow   # noqa: E402
from clawboard.theme import T                   # noqa: E402

C.NO_SAVE = True

root = tk.Tk()
root.geometry('420x560+80+80')
app = C.ClawBoard(root)
if app.collapsed:
    app.collapsed = False
    app.st['collapsed'] = False
    app.body.pack(fill='both', expand=True)
    app.root.minsize(*app.min_size())
root.update()

# 探针：把 check_async 换成计数器 / 同步回调器
_calls = {'n': 0}
_sync_ver = {'v': None}


def probe_check(r, on_result, timeout=5):
    _calls['n'] += 1
    return None


def sync_check(r, on_result, timeout=5):
    _calls['n'] += 1
    if _sync_ver['v'] is not None:
        on_result(_sync_ver['v'])
    return None


_orig_check = update.check_async

# ---- F1. 启动检查的 NO_SAVE 守卫（app 构造时就是 NO_SAVE，未联网）----
update.check_async = probe_check
_calls['n'] = 0
RT.NO_SAVE = True
app.st['update_check'] = True
app.st['update_checked_at'] = 0
app.setup_update_check()
check('NO_SAVE 自测模式：启动不发起检查', _calls['n'] == 0, '实际 %d' % _calls['n'])

# ---- F2. 频率闸（临时关掉 NO_SAVE 才能走到闸）----
RT.NO_SAVE = False
app.st['update_check'] = True
app.st['update_checked_at'] = now_ms()        # 刚刚查过
_calls['n'] = 0
app.setup_update_check()
check('频率闸：1 小时内 → 跳过启动检查', _calls['n'] == 0, '实际 %d' % _calls['n'])

app.st['update_checked_at'] = now_ms() - 2 * 3600 * 1000   # 2 小时前
_calls['n'] = 0
app.setup_update_check()
check('频率闸：超过 1 小时 → 触发启动检查', _calls['n'] == 1, '实际 %d' % _calls['n'])

app.st['update_check'] = False
app.st['update_checked_at'] = 0
_calls['n'] = 0
app.setup_update_check()
check('开关关闭 → 不检查', _calls['n'] == 0, '实际 %d' % _calls['n'])
RT.NO_SAVE = True
app.st['update_check'] = True

# ---- F3. 手动检查不受频率闸限制 ----
RT.NO_SAVE = False
app.st['update_checked_at'] = now_ms()        # 刚查过也不影响手动
_calls['n'] = 0
app.start_update_check(manual=True)
check('手动检查不受频率闸限制', _calls['n'] == 1, '实际 %d' % _calls['n'])

# ---- F4. 发现新版：写缓存 + tip + ⚙ 染色 ----
update.check_async = sync_check
update.LATEST = None
update.LATEST_NEW = False
_sync_ver['v'] = 'v9.9.9'
app.st['update_checked_at'] = 0
app.start_update_check(manual=True)
check('发现新版：update.LATEST 记录', update.LATEST == 'v9.9.9', 'got=%r' % update.LATEST)
check('发现新版：LATEST_NEW=True', update.LATEST_NEW is True)
check('发现新版：标题栏 tip 提示', '发现新版本' in app.title_lb.cget('text'),
      'title=%r' % app.title_lb.cget('text'))
check('发现新版：写入 update_checked_at', int(app.st.get('update_checked_at') or 0) > 0)
check('发现新版：工具条 ⚙ 染色为强调色',
      str(app.setting_btn.cget('fg')) == str(T['acc']),
      'fg=%r acc=%r' % (app.setting_btn.cget('fg'), T['acc']))

# ---- F5. 无新版：不染色、无 tip ----
_sync_ver['v'] = 'v2.4.0'
app.start_update_check(manual=True)
check('无新版：LATEST_NEW=False', update.LATEST_NEW is False)
check('无新版：⚙ 恢复常规色', str(app.setting_btn.cget('fg')) == str(T['fg']),
      'fg=%r' % app.setting_btn.cget('fg'))

# ---- F6. 设置页就地反馈 + 去下载 ----
sw = SettingsWindow(app)
sw.win.update_idletasks()
root.update()
check('设置页含更新状态标签', hasattr(sw, '_upd_status') and hasattr(sw, '_upd_btn'))
check('设置页含「去下载」入口', hasattr(sw, '_upd_dl'))

update.LATEST = 'v9.9.9'
update.LATEST_NEW = True
sw.paint_update()
check('设置页：发现新版就地提示', '发现新版本' in sw._upd_status.cget('text'),
      'status=%r' % sw._upd_status.cget('text'))
check('设置页：发现新版时露出「去下载」',
      sw._upd_dl in sw._upd_dl.master.pack_slaves())

update.LATEST = 'v2.4.0'
update.LATEST_NEW = False
sw.paint_update()
check('设置页：无新版显示"已是最新版本"',
      sw._upd_status.cget('text') == '已是最新版本',
      'status=%r' % sw._upd_status.cget('text'))
check('设置页：无新版时收起「去下载」',
      sw._upd_dl not in sw._upd_dl.master.pack_slaves())

# 点「检查更新」→ 后台（此处同步 mock）→ 就地反馈
_sync_ver['v'] = 'v9.9.9'
sw._upd_checking = False
sw.do_update_check()
check('设置页：手动检查后就地反馈新版本',
      'v9.9.9' in sw._upd_status.cget('text'), 'status=%r' % sw._upd_status.cget('text'))
check('设置页：手动检查结果写入缓存',
      update.LATEST == 'v9.9.9' and update.LATEST_NEW is True)
sw.win.destroy()

# ---- F7. 「去下载」打开 Release 页（复用 onboard.RELEASES_URL）----
_opened = {}
_orig_wb = webbrowser.open
webbrowser.open = lambda url: (_opened.__setitem__('url', url), True)[1]
try:
    app.open_releases()
finally:
    webbrowser.open = _orig_wb
check('「去下载」打开 Release 页',
      _opened.get('url') == onboard.RELEASES_URL, 'url=%r' % _opened.get('url'))
check('RELEASES_URL 指向 releases/latest',
      onboard.RELEASES_URL.endswith('/releases/latest'))

# 还原
update.check_async = _orig_check
RT.NO_SAVE = True
update.LATEST = None
update.LATEST_NEW = False

# 收尾：销毁 GUI（不走 quit_app）
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

# ============================================================
# G. 数据不污染
# ============================================================
section('G. 数据不污染')
check('真实数据 sha256 未变', HASH_BEFORE == file_hash(REAL_DATA),
      'before=%s after=%s' % (HASH_BEFORE, file_hash(REAL_DATA)))
check('真实目录无新增 .bak', sidecars() == FILES_BEFORE,
      'before=%s after=%s' % (FILES_BEFORE, sidecars()))
check('临时数据文件未被写入（NO_SAVE 生效）', not os.path.exists(TMP_DATA))

try:
    import shutil
    shutil.rmtree(TMP_DIR, ignore_errors=True)
except Exception:
    pass

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_t40.out')
with open(out, 'w', encoding='utf-8') as f:
    f.write('\n'.join(LOG) + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))
print('\n'.join(LOG), flush=True)
print('全部通过' if OK else '有失败项', flush=True)
os._exit(0)
