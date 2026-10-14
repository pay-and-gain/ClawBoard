# -*- coding: utf-8 -*-
"""补记「程序未运行时复制的内容」回归自测（A 方案 + B 方案落地）。

覆盖：
A. 库为空 → 不补读（clip 仍为空、onboard.is_empty_data 仍为 True）—— 保住首次引导卡片
B. 库非空 + 剪贴板内容与最新一条**不同** → 补 1 条（不多不少）
C. 库非空 + 剪贴板内容与最新一条**相同** → 不补（去重）
D. 剪贴板为空 → 不补
E. listen=False → 不补
F. 图片：与最新一条图片相同 → 不补；不同 → 补；最新一条不是图片 → 补
G. 「别记录我」标记（smart_private）/ skip_sensitive → 不补
H. **不播复制音**：把 sound.play_copy 换成探针，断言调用 0 次（文本与图片两条路径都验）
I. 重复调用 catchup_clipboard() 不会把同一条补多次
J. 触发点①「监听」开关由关变开 → 补一次；触发点② 启动流程调用了 catchup_clipboard
K. tip 文案：未开开机自启时追加建议、已开时不追加
L. 数据不污染：真实 ClawBoard数据.json sha256 前后一致、无新增 .bak

为什么全程 stub 剪贴板：本机剪贴板会被外部进程锁定（OpenClipboard → ERROR_ACCESS_DENIED，
_t35/_t37 已知环境问题），直接读真剪贴板会不稳定；补记逻辑只依赖「读到的内容」，用 stub
喂入受控内容即可完整覆盖分支。

数据安全：import 业务模块前把 app_services.DATA_FILE、timefmt.DATA_FILE、以及
app_services.BASE_DIR（图片落盘目录）**三个**都指向临时目录，并置 runtime.NO_SAVE /
C.NO_SAVE = True。
"""
import ctypes
import glob
import hashlib
import inspect
import os
import sys
import tempfile

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # 与产品一致的 DPI 感知
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ---- 重定向落盘目标（必须在 import 业务模块之前）----
TMP_DIR = tempfile.mkdtemp(prefix='cb_t42_')
TMP_DATA = os.path.join(TMP_DIR, 'ClawBoard数据.json')

import clawboard.app_services as S            # noqa: E402
S.DATA_FILE = TMP_DATA
S.CRASH_LOG = os.path.join(TMP_DIR, 'crash.log')
S.BASE_DIR = TMP_DIR                          # 图片落盘也走临时目录，绝不污染真实 images/

import clawboard.timefmt as TF                # noqa: E402
TF.DATA_FILE = TMP_DATA                       # 与 app_services 同步，避免 backup_data 复制真实存档

from clawboard import runtime as RT           # noqa: E402
RT.NO_SAVE = True

from clawboard import onboard                 # noqa: E402
from clawboard.onboard import is_empty_data   # noqa: E402

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


HASH_BEFORE = file_hash(REAL_DATA)             # 期望 == 5c21d32f...4079
FILES_BEFORE = sidecars()

# ============================================================
# 剪贴板 stub：用受控内容驱动补记逻辑，不动真剪贴板
# ============================================================
# kind: 'empty'（初始值，保证构造期 poll_clip 即便偶发触发也读不到东西）
#       'text' / 'image'
CLIP = {'kind': 'empty', 'text': None, 'private': False, 'image': None, 'files': []}


def _stub_clip_is_private():
    return bool(CLIP['private'])


def _stub_has_image():
    return CLIP['kind'] == 'image'


def _stub_clip_read():
    return CLIP['text'] if CLIP['kind'] == 'text' else None


def _stub_clip_read_files():
    return list(CLIP['files'] or [])


def _stub_read_dib():
    return (b'DIBMARK' if CLIP['kind'] == 'image' else None)


def _stub_dib_to_png(dib):
    # CLIP['image'] 预先放好 (png 字节, 宽, 高)
    return CLIP['image']


def _stub_capture_source(*a, **k):
    # 固定来源，避免 ingest 因 src=='unknown' 另起后台补抓线程
    return ('probe.exe', 0)


S.clip_is_private = _stub_clip_is_private
S.clipboard_has_image = _stub_has_image
S.clip_read = _stub_clip_read
S.clip_read_files = _stub_clip_read_files
S.read_clipboard_dib = _stub_read_dib
S.dib_to_png = _stub_dib_to_png
S.capture_source = _stub_capture_source
# 固定剪贴板序列号 → 轮询永远看不到"变化"，不会在测试间隙偷偷入库
RT.LAST_SEQ = 987654321
S.clip_seq = lambda: 987654321

import tkinter as tk          # noqa: E402
import ClawBoard as C         # noqa: E402

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


def item(text, **kw):
    d = {'id': 'it_%d' % id(text), 'text': text, 'created_at': 1000, 'updated_at': 1000,
         'seq': 1, 'content_type': 'text', 'copy_count': 1, 'fav': 0, 'is_estimated': 0}
    d.update(kw)
    return d


def set_lib(items):
    """设置剪贴板库（groups 置空，避免影响 is_empty_data 判定）。"""
    app.data['clip'] = list(items)
    app.data['groups'] = [{'name': '默认', 'items': []}]


def reset_clip(kind='empty', text=None, private=False, image=None, files=None):
    CLIP['kind'] = kind
    CLIP['text'] = text
    CLIP['private'] = private
    CLIP['image'] = image
    CLIP['files'] = files or []


# 基线状态：默认监听开、smart_private 开、skip_sensitive 关
app.st['listen'] = True
app.st['smart_private'] = True
app.st['skip_sensitive'] = False
app.st['sound_copy'] = False

# ============================================================
# A. 库为空 → 不补读
# ============================================================
section('A. 库为空 → 不补读（保住首次引导）')
set_lib([])
reset_clip('text', text='程序没运行时复制的内容')
r = app.catchup_clipboard()
check('库为空 → 不补', r is False, 'got=%r' % r)
check('库为空 → clip 仍为空', app.data['clip'] == [])
check('库为空 → onboard.is_empty_data 仍为 True', is_empty_data(app.data) is True)

# ============================================================
# B. 库非空 + 与最新一条不同 → 补 1 条
# ============================================================
section('B. 库非空 + 不同 → 补 1 条')
set_lib([item('已存在的内容')])
reset_clip('text', text='关程序期间新复制的内容')
n0 = len(app.data['clip'])
r = app.catchup_clipboard()
check('返回 True', r is True, 'got=%r' % r)
check('恰好补 1 条', len(app.data['clip']) == n0 + 1,
      'n0=%d n1=%d' % (n0, len(app.data['clip'])))
check('补的是新内容且在首位', app.data['clip'][0]['text'] == '关程序期间新复制的内容')

# ============================================================
# C. 库非空 + 与最新一条相同 → 不补
# ============================================================
section('C. 与最新一条相同 → 不补（去重）')
set_lib([item('同一条内容')])
reset_clip('text', text='同一条内容')
r = app.catchup_clipboard()
check('相同 → 不补', r is False, 'got=%r' % r)
check('条数不变', len(app.data['clip']) == 1)

# ============================================================
# D. 剪贴板为空 → 不补
# ============================================================
section('D. 剪贴板为空 → 不补')
set_lib([item('x')])
reset_clip('empty')
r = app.catchup_clipboard()
check('空剪贴板 → 不补', r is False, 'got=%r' % r)
check('条数不变', len(app.data['clip']) == 1)

# ============================================================
# E. listen=False → 不补
# ============================================================
section('E. listen=False → 不补')
set_lib([item('x')])
reset_clip('text', text='监听关闭期间复制的内容')
app.st['listen'] = False
r = app.catchup_clipboard()
check('listen=False → 不补', r is False, 'got=%r' % r)
check('条数不变', len(app.data['clip']) == 1)
app.st['listen'] = True

# ============================================================
# F. 图片：相同 → 不补；不同 → 补；最新一条不是图片 → 补
# ============================================================
section('F. 图片去重')
img_dir = os.path.join(TMP_DIR, 'images')
os.makedirs(img_dir, exist_ok=True)
PNG_A = b'\x89PNG\r\n\x1a\nA' + b'a' * 32
PNG_B = b'\x89PNG\r\n\x1a\nB' + b'b' * 32
with open(os.path.join(img_dir, 'imgA.png'), 'wb') as f:
    f.write(PNG_A)

# F1. 与最新一条图片相同 → 不补
set_lib([item('[图片]', content_type='image', image_path='imgA.png')])
reset_clip('image', image=(PNG_A, 10, 10))
r = app.catchup_clipboard()
check('图片与最新一条相同 → 不补', r is False, 'got=%r' % r)
check('条数不变', len(app.data['clip']) == 1)

# F2. 与最新一条图片不同 → 补
set_lib([item('[图片]', content_type='image', image_path='imgA.png')])
reset_clip('image', image=(PNG_B, 10, 10))
r = app.catchup_clipboard()
check('图片不同 → 补', r is True, 'got=%r' % r)
check('补 1 张图片且在首位',
      len(app.data['clip']) == 2 and app.data['clip'][0]['content_type'] == 'image')
check('补的图片文件已落盘（临时目录）',
      os.path.exists(os.path.join(img_dir, app.data['clip'][0]['image_path'])))

# F3. 最新一条不是图片 → 补
set_lib([item('一段普通文本')])
reset_clip('image', image=(PNG_B, 10, 10))
r = app.catchup_clipboard()
check('最新一条不是图片 → 补', r is True, 'got=%r' % r)
check('补的是图片且在首位',
      len(app.data['clip']) == 2 and app.data['clip'][0]['content_type'] == 'image')

# ============================================================
# G. smart_private / skip_sensitive → 不补
# ============================================================
section('G. smart_private / skip_sensitive → 不补')
set_lib([item('x')])
reset_clip('text', text='带「别记录我」标记的内容', private=True)
r = app.catchup_clipboard()
check('smart_private → 不补', r is False, 'got=%r' % r)
check('条数不变', len(app.data['clip']) == 1)

app.st['skip_sensitive'] = True
set_lib([item('x')])
reset_clip('text', text='我的手机号 13800138000', private=False)
r = app.catchup_clipboard()
check('skip_sensitive → 不补', r is False, 'got=%r' % r)
check('条数不变', len(app.data['clip']) == 1)
app.st['skip_sensitive'] = False

# ============================================================
# H. 不播复制音（探针断言 0 次）
# ============================================================
section('H. 补记不播复制音')
_played = {'n': 0}
_orig_play = S.sound.play_copy
S.sound.play_copy = lambda: _played.__setitem__('n', _played['n'] + 1)
try:
    app.st['sound_copy'] = True         # 开关打开，若补记误播就会被抓到
    # 文本路径
    set_lib([item('x')])
    reset_clip('text', text='补记文本')
    app.catchup_clipboard()
    # 图片路径
    set_lib([item('x')])
    reset_clip('image', image=(PNG_B, 6, 6))
    app.catchup_clipboard()
finally:
    S.sound.play_copy = _orig_play
    app.st['sound_copy'] = False
check('文本+图片补记均不播复制音（调用 0 次）', _played['n'] == 0,
      '实际 %d' % _played['n'])

# ============================================================
# I. 重复调用不会补多次
# ============================================================
section('I. 重复调用不重复补')
set_lib([item('第一条')])
reset_clip('text', text='第二条')
r1 = app.catchup_clipboard()
r2 = app.catchup_clipboard()
r3 = app.catchup_clipboard()
check('首次补记成功', r1 is True)
check('再次调用返回 False', r2 is False and r3 is False)
check('只补了一条（总数 2）', len(app.data['clip']) == 2,
      'got=%d' % len(app.data['clip']))
check('首位是补记的“第二条”', app.data['clip'][0]['text'] == '第二条')

# ============================================================
# J. 触发点
# ============================================================
section('J. 两个触发点')
# 触发点①：监听由关变开
set_lib([item('已有')])
app.st['listen'] = True
app.toggle_listen()                     # -> False（关）
reset_clip('text', text='关闭监听期间复制的内容')
app.toggle_listen()                     # -> True（开，应触发补记）
check('重开监听 → 补记关闭期间的内容',
      any(x.get('text') == '关闭监听期间复制的内容' for x in app.data['clip']))
check('重开后 listen=True', app.st['listen'] is True)

# 触发点②：启动流程里调用了 catchup_clipboard
_src = inspect.getsource(C.ClawBoard.__init__)
check('启动流程调用 catchup_clipboard', 'catchup_clipboard' in _src)
check('启动流程里 catchup 在 poll_clip 之后',
      _src.index('catchup_clipboard') > _src.index('self.poll_clip()'),
      'app.py __init__ 顺序')

# ============================================================
# K. tip 文案随「开机自启」状态变化
# ============================================================
section('K. tip 文案')
_orig_ga = S.get_autostart
try:
    S.get_autostart = lambda: (False, '')
    t_off = app._catchup_tip()
    S.get_autostart = lambda: (True, r'"py" "ClawBoard.py"')
    t_on = app._catchup_tip()
finally:
    S.get_autostart = _orig_ga
check('补记 tip 说明来源', '已补记程序未运行时复制的内容' in t_off)
check('未开开机自启 → 追加建议', '开机自启' in t_off, 'tip=%r' % t_off)
check('已开开机自启 → 不追加建议', '开机自启' not in t_on, 'tip=%r' % t_on)

# ============================================================
# L. 数据不污染
# ============================================================
section('L. 数据不污染')
check('真实数据 sha256 未变',
      HASH_BEFORE == file_hash(REAL_DATA) ==
      '5c21d32f5c8a5173646c7b0927a0a2149d6f2db5b6b35758f5e12c8150314079',
      'before=%s after=%s' % (HASH_BEFORE, file_hash(REAL_DATA)))
check('真实目录无新增 .bak', sidecars() == FILES_BEFORE,
      'before=%s after=%s' % (FILES_BEFORE, sidecars()))
check('临时数据文件未被写入（NO_SAVE 生效）', not os.path.exists(TMP_DATA))

# 收尾：销毁 GUI（不走 quit_app，避免真实落盘）
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

try:
    import shutil
    shutil.rmtree(TMP_DIR, ignore_errors=True)
except Exception:
    pass

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_t42.out')
with open(out, 'w', encoding='utf-8') as f:
    f.write('\n'.join(LOG) + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))
print('\n'.join(LOG), flush=True)
print('全部通过' if OK else '有失败项', flush=True)
os._exit(0)
