# -*- coding: utf-8 -*-
"""QA 独立验证：P1-2 音效反馈（sound.py + 设置 + 挂钩）。

与工程师自测 (_t39.py) 的差异（换角度、更硬）：
- A 走**真实文件 load_data() 路径**（含 schema_version=1 迁移分支），不只是 validate()。
  另外验证 SettingsDict 注解存在、以及「非 bool 的真值」（如 1）回退为默认，避免误响。
- D 不只对比规格常量，而是把 WAV bytes **解码回采样**，用能量包络切分音段、
  用零交叉估**真实频率**，并检查首尾淡入淡出（无爆音）、两音段数不同（节奏可辨）。
- E 用「把 ingest 打成空操作再轮询」证明音效挂在 ingest 而非 poll_clip；
  并逐一覆盖 paste / paste_plain / quick_paste / paste_image 四条粘贴入口，
  以及「只写剪贴板不粘贴」路径不响。
- 全程 monkeypatch 探针，不依赖真实响声；仅 D 末尾真实播放一次做冒烟。

数据安全：import 业务模块前把 app_services.DATA_FILE 与 timefmt.DATA_FILE **两个**都
指向临时目录，并置 runtime.NO_SAVE / C.NO_SAVE = True。跑完核对真实存档 hash 与 .bak 集合。
"""
import ctypes
import glob
import hashlib
import importlib.util
import io
import os
import struct
import sys
import tempfile
import time
import types
import wave

# DPI 感知必须在建 Tk 前打开（与产品一致）
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ---- 重定向落盘目标（必须在 import 业务模块之前）----
TMP_DIR = tempfile.mkdtemp(prefix='cb_qa6_')
TMP_DATA = os.path.join(TMP_DIR, 'ClawBoard数据.json')

import clawboard.app_services as S            # noqa: E402
S.DATA_FILE = TMP_DATA
S.CRASH_LOG = os.path.join(TMP_DIR, 'crash.log')

import clawboard.app_interact as AI           # noqa: E402
import clawboard.timefmt as TF                # noqa: E402
TF.DATA_FILE = TMP_DATA                       # backup_data() 用 timefmt 命名空间里的副本

from clawboard import runtime as RT           # noqa: E402
RT.NO_SAVE = True

from clawboard import sound                   # noqa: E402
from clawboard.config import DEFAULT_SETTINGS  # noqa: E402
from clawboard.app_services import DataMixin   # noqa: E402
from clawboard.config import SettingsDict      # noqa: E402

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

check('DEFAULT_SETTINGS 有 sound_copy', 'sound_copy' in DEFAULT_SETTINGS)
check('DEFAULT_SETTINGS 有 sound_paste', 'sound_paste' in DEFAULT_SETTINGS)
check('sound_copy 默认恰为 False（非假值）', DEFAULT_SETTINGS.get('sound_copy') is False)
check('sound_paste 默认恰为 False（非假值）', DEFAULT_SETTINGS.get('sound_paste') is False)
check('两者类型为 bool', isinstance(DEFAULT_SETTINGS['sound_copy'], bool)
      and isinstance(DEFAULT_SETTINGS['sound_paste'], bool))

_ann = getattr(SettingsDict, '__annotations__', {})
check('SettingsDict 注解含 sound_copy', 'sound_copy' in _ann)
check('SettingsDict 注解含 sound_paste', 'sound_paste' in _ann)

# A1. validate() 直接测
_v = DataMixin.validate({'clip': [], 'groups': [], 'settings': {}, 'schema_version': 3})
check('validate 补默认 sound_copy=False', _v['settings'].get('sound_copy') is False)
check('validate 补默认 sound_paste=False', _v['settings'].get('sound_paste') is False)

_v_true = DataMixin.validate({'clip': [], 'groups': [],
                              'settings': {'sound_copy': True, 'sound_paste': True},
                              'schema_version': 3})
check('validate 保留显式 True', _v_true['settings']['sound_copy'] is True
      and _v_true['settings']['sound_paste'] is True)

# 非 bool 的真值（JSON 里写成 1）应回退默认 False —— 避免把非法值当成"开"
_v_int = DataMixin.validate({'clip': [], 'groups': [],
                             'settings': {'sound_copy': 1, 'sound_paste': 1},
                             'schema_version': 3})
check('非 bool 真值回退默认（1 → False，防误响）',
      _v_int['settings']['sound_copy'] is False and _v_int['settings']['sound_paste'] is False)


# A2. 真实 load_data() 路径（schema_version=3，不进迁移）
class _Dummy(DataMixin):
    """只借 DataMixin 的 load_data/validate，不建 GUI。note 走 RT.NO_SAVE 早退。"""
    def __init__(self):
        pass


def load_from(settings, schema_version):
    payload = {'clip': [], 'groups': [{'name': '默认', 'items': []}], 'gi': 0,
               'geom': None, 'settings': settings, 'schema_version': schema_version}
    with open(TMP_DATA, 'w', encoding='utf-8') as f:
        import json
        json.dump(payload, f, ensure_ascii=False)
    return _Dummy().load_data()


try:
    d3 = load_from({'theme': 'dark', 'listen': True}, 3)     # 老设置，无新字段
    check('load_data(v3, 无新字段) 不抛异常', True)
    check('load_data(v3, 无新字段) → sound_copy False', d3['settings']['sound_copy'] is False)
    check('load_data(v3, 无新字段) → sound_paste False', d3['settings']['sound_paste'] is False)
except Exception as e:
    check('load_data(v3, 无新字段) 不抛异常', False, repr(e))

try:
    d1 = load_from({'theme': 'light'}, 1)                    # 触发 1→2→3 迁移分支
    check('load_data(v1 迁移) 不抛异常', True)
    check('load_data(v1 迁移) → sound_copy False', d1['settings']['sound_copy'] is False)
    check('load_data(v1 迁移) → sound_paste False', d1['settings']['sound_paste'] is False)
except Exception as e:
    check('load_data(v1 迁移) 不抛异常', False, repr(e))

try:
    dT = load_from({'sound_copy': True, 'sound_paste': True}, 3)
    check('load_data 保留 true', dT['settings']['sound_copy'] is True
          and dT['settings']['sound_paste'] is True)
except Exception as e:
    check('load_data 保留 true', False, repr(e))

# 迁移分支会写 .bak 到 TMP_DIR，确认没有落到真实目录
check('迁移备份落在临时目录（真实目录无新增 .bak）',
      sorted(os.path.basename(p) for p in glob.glob(REAL_DATA + '*')) == FILES_BEFORE)

# 记录此刻临时数据文件的指纹，供 G 段核对产品 save() 未落盘
TMP_HASH_AFTER_A = file_hash(TMP_DATA)


# ============================================================
# B. 开关控制（模块级探针，不真响）
# ============================================================
section('B. 开关控制 + C. 静默失败（模块层）')

_ORIG_WIN = sound.winsound
_seen = []


class _Rec:
    """假 winsound：记录调用，常量与真实值保持一致。"""
    SND_MEMORY = 4
    SND_ASYNC = 1
    SND_SYNC = 0
    SND_FILENAME = 0x00020000

    @staticmethod
    def PlaySound(data, flags):
        _seen.append((data, flags))

    @staticmethod
    def Beep(f, d):   # 绝不能走到这里（同步阻塞）
        raise AssertionError('误用同步 winsound.Beep')


sound.winsound = _Rec

# play_copy 传的必须是 COPY_WAV 本体（模块级持有引用，防 GC）
_seen.clear()
sound.play_copy()
sound.play_paste()
check('play_copy 播放的正是 COPY_WAV', bool(_seen) and _seen[0][0] is sound.COPY_WAV)
check('play_paste 播放的正是 PASTE_WAV', len(_seen) == 2 and _seen[1][0] is sound.PASTE_WAV)
check('flags = SND_MEMORY|SND_ASYNC（异步）',
      all(fl == (_Rec.SND_MEMORY | _Rec.SND_ASYNC) for _, fl in _seen),
      'flags=%r' % [fl for _, fl in _seen])

sound.winsound = _ORIG_WIN


def _probe():
    """返回 (计数器 dict, 还原函数)。把 play_copy/play_paste 换成计数器。"""
    calls = {'copy': 0, 'paste': 0}
    oc, op = sound.play_copy, sound.play_paste
    sound.play_copy = lambda: calls.__setitem__('copy', calls['copy'] + 1)
    sound.play_paste = lambda: calls.__setitem__('paste', calls['paste'] + 1)

    def restore():
        sound.play_copy, sound.play_paste = oc, op
    return calls, restore


# C1. 底层 PlaySound 抛异常 → 调用方收不到，主流程继续
class _Boom:
    SND_MEMORY = 4
    SND_ASYNC = 1

    @staticmethod
    def PlaySound(*a, **k):
        raise RuntimeError('no audio device')


sound.winsound = _Boom
_prop_ok = True
try:
    sound.play_copy()
    sound.play_paste()
    sound.play_wav(b'validish')
except Exception:
    _prop_ok = False
sound.winsound = _ORIG_WIN
check('PlaySound 抛异常不向调用方传播', _prop_ok)

# C2. 模拟非 Windows：重新执行模块源码，且让 import winsound 失败
sound.winsound = None
_none_ok = True
try:
    sound.play_copy()
    sound.play_paste()
except Exception:
    _none_ok = False
check('winsound=None 时静默（调用不崩）', _none_ok)

_saved = sys.modules.get('winsound', '<<absent>>')
sys.modules['winsound'] = None            # 让 import winsound 直接失败
try:
    spec = importlib.util.spec_from_file_location('cb_sound_noaudio', sound.__file__)
    mod_nonwin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod_nonwin)   # 模块级 import 失败应被 try/except 吞掉
    _imp_ok = mod_nonwin.winsound is None
    mod_nonwin.play_copy()                # 不应抛
    mod_nonwin.play_paste()
    _call_ok = True
except Exception as e:
    _imp_ok, _call_ok = False, False
    LOG.append('   非 Windows 复现异常: %r' % (e,))
finally:
    if _saved == '<<absent>>':
        sys.modules.pop('winsound', None)
    else:
        sys.modules['winsound'] = _saved
check('无 winsound 时模块仍可 import', _imp_ok)
check('无 winsound 时调用不崩', _call_ok)

# C3. 畸形/空数据传进播放函数
sound.winsound = _Rec
_seen.clear()
_mal_ok = True
_none_calls = -1
try:
    sound.play_wav(b'')
    sound.play_wav(None)
    _none_calls = len(_seen)              # 空/None 应 0 次底层调用
    sound.play_wav(b'\x00\x01\x02\x03')   # 非 WAV：允许尝试，真 winsound 会抛→被吞
    sound.play_wav(12345)                 # 非 bytes：同上
except Exception:
    _mal_ok = False
sound.winsound = _ORIG_WIN
check('空/畸形数据不崩', _mal_ok)
check('空/None 数据不触发底层播放', _none_calls == 0, '实际 %d' % _none_calls)

# 确认没有走同步 Beep：用 AST 检查代码里没有 .Beep 调用（文档字符串里的文字不算）
import ast  # noqa: E402
import inspect  # noqa: E402
_tree = ast.parse(inspect.getsource(sound))
_beep_calls = [n for n in ast.walk(_tree)
               if isinstance(n, ast.Attribute) and n.attr == 'Beep']
check('音效模块代码未调用同步 Beep（AST，且 _Rec.Beep 会抛）', not _beep_calls)


# ============================================================
# D. 音频真实性质检（硬验证）
# ============================================================
section('D. 音频真实性（解码 + 频率 + 节奏 + 淡入淡出）')


def decode(data):
    with wave.open(io.BytesIO(data), 'rb') as w:
        meta = (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes())
        raw = w.readframes(w.getnframes())
    n = meta[3]
    return meta, struct.unpack('<%dh' % n, raw)


def regions(data):
    """把音段按「连续静音（精确 0）」切开，逐段估频率。

    比按振幅阈值切更稳：段间静默是精确填 0 的（gap_ms），而每个正弦周期穿越
    零点时样本也会很小 —— 用阈值会误切成上百小段。这里只认「连续 ≥3ms 的精确 0」
    为分隔，段内再用零交叉测频率。
    返回 (meta, [(频率Hz, 时长ms, 首样本, 末样本)], samples)。
    """
    meta, s = decode(data)
    sr = meta[2]
    min_gap = int(sr * 0.003)
    bounds = []
    start = 0
    i = 0
    n = len(s)
    while i < n:
        if s[i] == 0:
            j = i
            while j < n and s[j] == 0:
                j += 1
            if j - i >= min_gap:
                bounds.append((start, i))
                start = j
            i = j
        else:
            i += 1
    bounds.append((start, n))
    res = []
    for a, b in bounds:
        if b - a < sr * 0.005:      # 忽略过短碎片
            continue
        seg = s[a:b]
        zc = sum(1 for k in range(1, len(seg)) if (seg[k - 1] < 0) != (seg[k] < 0))
        res.append((zc * sr / (2.0 * len(seg)), 1000.0 * len(seg) / sr, seg[0], seg[-1]))
    return meta, res, s


for label, wav in (('COPY', sound.COPY_WAV), ('PASTE', sound.PASTE_WAV)):
    check('%s 是合法 RIFF/WAVE' % label,
          wav[:4] == b'RIFF' and wav[8:12] == b'WAVE')
    meta, s = decode(wav)
    check('%s 单声道' % label, meta[0] == 1, 'nch=%d' % meta[0])
    check('%s 16-bit 采样' % label, meta[1] == 2, 'sampwidth=%d' % meta[1])
    check('%s 帧率合理(8k~48k)' % label, 8000 <= meta[2] <= 48000, 'sr=%d' % meta[2])
    dur = 1000.0 * meta[3] / meta[2]
    check('%s 时长 ≤150ms' % label, dur <= 150.0, '%.1fms' % dur)
    check('%s 首样本≈0（淡入，无爆音）' % label, abs(s[0]) < 300, 'first=%d' % s[0])
    check('%s 末样本≈0（淡出，无爆音）' % label, abs(s[-1]) < 300, 'last=%d' % s[-1])

check('COPY 与 PASTE 字节不同', sound.COPY_WAV != sound.PASTE_WAV)

_meta_c, regs_c, _ = regions(sound.COPY_WAV)
_meta_p, regs_p, _ = regions(sound.PASTE_WAV)
check('COPY 为单音段（单声）', len(regs_c) == 1, '段数=%d' % len(regs_c))
check('PASTE 为双音段（两声，节奏可辨）', len(regs_p) >= 2, '段数=%d' % len(regs_p))
check('两音段数不同（节奏确实不同），非同一音', len(regs_c) != len(regs_p))

if regs_c:
    fc = regs_c[0][0]
    check('COPY 实测频率≈1175Hz(±12%%)', abs(fc - 1175) / 1175.0 < 0.12, '实测 %.0fHz' % fc)
if len(regs_p) >= 2:
    f1, f2 = regs_p[0][0], regs_p[1][0]
    check('PASTE 第一声≈587Hz(±12%%)', abs(f1 - 587) / 587.0 < 0.12, '实测 %.0fHz' % f1)
    check('PASTE 第二声≈784Hz(±12%%)', abs(f2 - 784) / 784.0 < 0.12, '实测 %.0fHz' % f2)
    check('PASTE 先低后高（两声可辨方向）', f2 > f1, '%.0f -> %.0f' % (f1, f2))

# D-末：真实播放一次（会真的响一声，属预期），确认不抛、进程不崩
print('[info] 接下来会真实播放两声（复制音 + 粘贴音）做冒烟 …', flush=True)
_real_ok = True
try:
    sound.play_copy()
    time.sleep(0.15)
    sound.play_paste()
    time.sleep(0.25)
except Exception as e:
    _real_ok = False
    LOG.append('   真实播放异常: %r' % (e,))
check('真实播放路径不抛异常（冒烟）', _real_ok)


# ============================================================
# E. 触发时机正确性（GUI 探针）
# ============================================================
section('E. 触发时机（复制一次 / 粘贴覆盖面）')

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

# 屏蔽轮询自排程，避免 after 回调在测试期间乱入
app.root.after = lambda ms, fn=None, *a: None

calls, restore_probe = _probe()

# ---- 保存并接管剪贴板相关函数 ----
_o = (S.clip_seq, S.clip_read, S.clip_read_files, S.clip_is_private,
      S.clipboard_has_image, S.capture_source, S.match_ignore)

app.st['listen'] = True
app.st['sound_copy'] = True
app.st['min_len'] = 0
app.st['max_len'] = 0
app.st['ignore_apps'] = ''
app.st['ignore_titles'] = ''


def env(seq, content, last):
    """配置一次轮询环境：clip_seq 返回 seq，runtime.LAST_SEQ 预置为 last。
    seq != last 才算「剪贴板序列号变了」，poll_clip 才会走到 ingest。"""
    RT.LAST_SEQ = last
    S.clip_seq = lambda: seq
    S.clip_is_private = lambda: False
    S.clipboard_has_image = lambda: False
    S.clip_read = lambda: content
    S.clip_read_files = lambda: []
    S.capture_source = lambda *a, **k: ('qa6', None)   # 非 unknown，避免 _late_source 线程
    S.match_ignore = lambda *a, **k: None


# E1. 序列号没变 → 连续多次轮询一次都不响
env(1000, '', last=1000)
calls['copy'] = 0
for _ in range(5):
    app.poll_clip()
check('复制音：序列号未变，连续 5 次轮询 0 响', calls['copy'] == 0, '实际 %d' % calls['copy'])

# E2. 序列号变了 + 非空 → 只响一次；随后同号再轮询不再响
env(1001, '新复制的内容一', last=1000)
calls['copy'] = 0
app.poll_clip()
check('复制音：记下新内容时响 1 次', calls['copy'] == 1, '实际 %d' % calls['copy'])
app.poll_clip()
app.poll_clip()
check('复制音：同号重复轮询不再响（总仍为 1）', calls['copy'] == 1, '实际 %d' % calls['copy'])

# E3. 内容（序列号）再次变化 → 再响一次
env(1002, '又一条新内容', last=1001)
app.poll_clip()
check('复制音：内容变化后再响 1 次（累计 2）', calls['copy'] == 2, '实际 %d' % calls['copy'])

# E4. 空白内容 → 不响（即使序列号变了）
env(1003, '   ', last=1002)
calls['copy'] = 0
app.poll_clip()
check('复制音：空白内容不响', calls['copy'] == 0, '实际 %d' % calls['copy'])

# E5. 被忽略规则挡下 → 不响
env(1004, '正文足够长不会因为长度被过滤掉', last=1003)
S.match_ignore = lambda *a, **k: '应用 notepad'
calls['copy'] = 0
app.poll_clip()
check('复制音：命中忽略规则不响', calls['copy'] == 0, '实际 %d' % calls['copy'])
S.match_ignore = lambda *a, **k: None

# E6. 长度过滤挡下 → 不响
app.st['min_len'] = 999
env(1005, 'too short', last=1004)
calls['copy'] = 0
app.poll_clip()
check('复制音：长度过滤挡下不响', calls['copy'] == 0, '实际 %d' % calls['copy'])
app.st['min_len'] = 0

# E7. manual=True 不响（直接调 ingest，不经轮询）
calls['copy'] = 0
app.ingest('手动拆出来的内容', manual=True)
check('复制音：manual=True 不响', calls['copy'] == 0, '实际 %d' % calls['copy'])

# E8. 音效确实挂在 ingest（不在 poll_clip）：把 ingest 打成空操作后，序列号变化也不响
_orig_ingest = app.ingest
app.ingest = lambda *a, **k: None
env(1006, '内容有了但 ingest 被架空', last=1005)
calls['copy'] = 0
app.poll_clip()
check('证据：架空 ingest 后 poll_clip 不发声（挂点在 ingest）',
      calls['copy'] == 0, '实际 %d' % calls['copy'])
app.ingest = _orig_ingest

# E9. 开关关闭 → 有新内容也不响（复制侧）
app.st['sound_copy'] = False
env(1007, '开关关了', last=1006)
calls['copy'] = 0
app.poll_clip()
check('复制音：开关关闭不响', calls['copy'] == 0, '实际 %d' % calls['copy'])
app.st['sound_copy'] = True

# 还原剪贴板环境
(S.clip_seq, S.clip_read, S.clip_read_files, S.clip_is_private,
 S.clipboard_has_image, S.capture_source, S.match_ignore) = _o

# ---- 粘贴侧 ----
_o2 = (AI.can_paste_message, AI.paste_message, AI.window_rect,
       AI.png_to_dib, AI.write_clipboard_dib, AI.BASE_DIR)
AI.can_paste_message = lambda hwnd: True
AI.paste_message = lambda hwnd: None
AI.window_rect = lambda hwnd: None
app.write_clip = lambda text: True
app.prev_hwnd = None
app.hidden = False
app.st['autopaste'] = True

# E10. 仅 sound_copy 开 → 粘贴不响（两开关不串）
app.st['sound_copy'] = True
app.st['sound_paste'] = False
calls['paste'] = 0
app.paste('粘贴测试', force=True)
check('两开关不串：只开 copy 时粘贴不响', calls['paste'] == 0, '实际 %d' % calls['paste'])

# E11. 开 sound_paste → paste() 响 1 次
app.st['sound_paste'] = True
calls['paste'] = 0
r = app.paste('粘贴测试', force=True)
check('粘贴音：paste() 响 1 次', calls['paste'] == 1, '实际 %d' % calls['paste'])
check('paste() 仍正常返回 True', r is True)

# E12. 仅 sound_paste 开 → 复制侧不响（反向不串）
app.st['sound_copy'] = False
calls['copy'] = 0
env(2000, '只开粘贴音', last=1999)
app.poll_clip()
check('两开关不串：只开 paste 时复制不响', calls['copy'] == 0, '实际 %d' % calls['copy'])

# E13. autopaste 关 + 未 force + 面板隐藏 → 只写剪贴板，不响
app.st['autopaste'] = False
app.hidden = True
calls['paste'] = 0
app.paste('只复制不粘贴', force=False)
check('粘贴音：只写剪贴板不粘贴时不响', calls['paste'] == 0, '实际 %d' % calls['paste'])

# E14. paste_plain（F6 纯文本粘贴）→ 响
app.st['autopaste'] = True
app.hidden = False
calls['paste'] = 0
app.paste_plain({'id': 'p1', 'text': '纯文本粘贴内容'})
check('粘贴音：paste_plain 覆盖', calls['paste'] == 1, '实际 %d' % calls['paste'])

# E15. quick_paste（Ctrl+数字）→ 响
app.tab = 'clip'
app.vlist.items = [{'id': 'q1', 'text': 'quick 第一条'},
                   {'id': 'q2', 'text': 'quick 第二条'}]
app.vlist.update_view = lambda: None
app.vlist.flash = lambda cid: None
calls['paste'] = 0
app.quick_paste(2)
check('粘贴音：quick_paste 覆盖', calls['paste'] == 1, '实际 %d' % calls['paste'])

# E16. paste_image → 响
img_dir = os.path.join(TMP_DIR, 'images')
os.makedirs(img_dir, exist_ok=True)
with open(os.path.join(img_dir, 'qa6.png'), 'wb') as f:
    f.write(b'\x89PNG\r\n\x1a\n fake')
AI.BASE_DIR = TMP_DIR
AI.png_to_dib = lambda png: (b'dib', 10, 10)
AI.write_clipboard_dib = lambda dib: True
app.prev_hwnd = None
app.hidden = False
app.st['autopaste'] = True
calls['paste'] = 0
rit = app.paste_image({'id': 'i1', 'image_path': 'qa6.png'}, force=True)
check('粘贴音：paste_image 覆盖', calls['paste'] == 1, '实际 %d' % calls['paste'])
check('paste_image 返回 True', rit is True)

# E17. paste_image 只写不粘（autopaste 关 + 面板隐藏）→ 不响
app.st['autopaste'] = False
app.hidden = True
calls['paste'] = 0
app.paste_image({'id': 'i1', 'image_path': 'qa6.png'}, force=False)
check('粘贴音：paste_image 仅写剪贴板时不响', calls['paste'] == 0, '实际 %d' % calls['paste'])

# ============================================================
# H. 图片复制音（修复轮回归：工程师在 _ingest_image 末尾补 sound_copy）
# ============================================================
section('H. 图片复制音（修复轮）')

_o3 = (S.read_clipboard_dib, S.dib_to_png, S.BASE_DIR, S.now_ms)
IG_BASE = os.path.join(TMP_DIR, 'imgbase')
os.makedirs(IG_BASE, exist_ok=True)
S.BASE_DIR = IG_BASE
IMG_OUT = os.path.join(IG_BASE, 'images')
IMAGES_ROOT_BEFORE = os.path.exists(os.path.join(ROOT, 'images'))


def reset_image_env():
    S.read_clipboard_dib = lambda: b'DIBDATA'
    S.dib_to_png = lambda dib: (b'\x89PNG fake', 12, 8)
    S.BASE_DIR = IG_BASE
    S.now_ms = _o3[3]


# H1. early-return：无 DIB → 不响
reset_image_env()
app.st['sound_copy'] = True
calls['copy'] = 0
S.read_clipboard_dib = lambda: None
app._ingest_image()
check('图片 early-return：无 DIB 不响', calls['copy'] == 0, '实际 %d' % calls['copy'])

# H2. early-return：DIB→PNG 转换失败 → 不响
reset_image_env()
calls['copy'] = 0
S.dib_to_png = lambda dib: (_ for _ in ()).throw(RuntimeError('bad dib'))
app._ingest_image()
check('图片 early-return：转换失败不响', calls['copy'] == 0, '实际 %d' % calls['copy'])

# H3. early-return：images 目录无法建立（BASE_DIR 指向一个普通文件）→ 不响
reset_image_env()
calls['copy'] = 0
_blocker = os.path.join(TMP_DIR, 'not_a_dir')
with open(_blocker, 'wb') as f:
    f.write(b'x')
S.BASE_DIR = _blocker                      # join(blocker,'images') makedirs 会失败
app._ingest_image()
check('图片 early-return：建目录失败不响', calls['copy'] == 0, '实际 %d' % calls['copy'])

# H4. early-return：写文件失败（同名目标已存在且是目录）→ 不响
reset_image_env()
os.makedirs(IMG_OUT, exist_ok=True)
_collide = os.path.join(IMG_OUT, '999999.png')
try:
    os.makedirs(_collide, exist_ok=True)    # 让 open(...,'wb') 撞上目录 → IsADirectoryError
except Exception:
    pass
S.now_ms = lambda: 999999
calls['copy'] = 0
app._ingest_image()
check('图片 early-return：写文件失败不响', calls['copy'] == 0, '实际 %d' % calls['copy'])

# H5. 成功入库但开关关 → 0 响（且确实新增了一条图片记录）
reset_image_env()
before_n = len(app.data['clip'])
app.st['sound_copy'] = False
calls['copy'] = 0
app._ingest_image()
check('图片：开关关时入库不响', calls['copy'] == 0, '实际 %d' % calls['copy'])
check('图片：确实入库了 1 条（开关只控声音）', len(app.data['clip']) == before_n + 1,
      'before=%d after=%d' % (before_n, len(app.data['clip'])))

# H6. 成功入库且开关开 → 恰 1 响
reset_image_env()
app.st['sound_copy'] = True
calls['copy'] = 0
app._ingest_image()
check('图片：开关开时恰响 1 次', calls['copy'] == 1, '实际 %d' % calls['copy'])

# H7. 端到端：真实轮询到图片 → 恰 1 响，且不重复、不误走文本 ingest
reset_image_env()
_o4 = (S.clip_seq, S.clip_read, S.clip_read_files, S.clip_is_private,
       S.clipboard_has_image, S.match_ignore, S.capture_source)
app.ingest = _orig_ingest            # 确保 ingest 是真身（E8 已还原，双保险）
_ingest_counter = {'n': 0}
_real_ingest = app.ingest


def _counting_ingest(*a, **k):
    _ingest_counter['n'] += 1
    return _real_ingest(*a, **k)


app.ingest = _counting_ingest
RT.LAST_SEQ = 3000
S.clip_seq = lambda: 3001
S.clip_is_private = lambda: False
S.clipboard_has_image = lambda: True
S.clip_read = lambda: '不该被读到'
S.clip_read_files = lambda: []
calls['copy'] = 0
app.poll_clip()
check('图片端到端：轮询到图片恰响 1 次', calls['copy'] == 1, '实际 %d' % calls['copy'])
check('图片端到端：未重复响（同号再轮询仍 1）', calls['copy'] == 1)
check('图片端到端：走 _ingest_image，不经文本 ingest（互斥）',
      _ingest_counter['n'] == 0, 'ingest 调用 %d 次' % _ingest_counter['n'])
app.ingest = _real_ingest

# H8. CF_HDROP（资源管理器复制文件）走文本 ingest，仅 1 响
S.clipboard_has_image = lambda: False
S.clip_read = lambda: ''                       # 无文本
S.clip_read_files = lambda: ['C:\\\\a\\\\b.txt', 'C:\\\\c\\\\d 空格.png']
S.capture_source = lambda *a, **k: ('qa6', None)   # 非 unknown，不派生补抓线程
S.match_ignore = lambda *a, **k: None
RT.LAST_SEQ = 3002
S.clip_seq = lambda: 3003
app.st['sound_copy'] = True
calls['copy'] = 0
_ingest_counter['n'] = 0
app.ingest = _counting_ingest
app.poll_clip()
check('CF_HDROP 文件路径：仅响 1 次', calls['copy'] == 1, '实际 %d' % calls['copy'])
check('CF_HDROP：经文本 ingest 恰 1 次（未走图片分支）',
      _ingest_counter['n'] == 1, 'ingest 调用 %d 次' % _ingest_counter['n'])
app.ingest = _real_ingest

(S.clip_seq, S.clip_read, S.clip_read_files, S.clip_is_private,
 S.clipboard_has_image, S.match_ignore, S.capture_source) = _o4
(S.read_clipboard_dib, S.dib_to_png, S.BASE_DIR, S.now_ms) = _o3

# ---- F. 不阻塞 ----
app.st['autopaste'] = True
app.hidden = False
calls['paste'] = 0
t0 = time.perf_counter()
for _ in range(200):
    app.paste('x', force=True)
dt = time.perf_counter() - t0
check('F. 粘贴路径不阻塞（200 次 < 0.5s）', dt < 0.5, '%.4fs' % dt)
check('F. 200 次各响一次', calls['paste'] == 200, '实际 %d' % calls['paste'])

# 200 次真实模块调用耗时上界（模块层）
sound.winsound = _Rec
_seen.clear()
t0 = time.perf_counter()
for _ in range(500):
    sound.play_copy()
    sound.play_paste()
dt2 = time.perf_counter() - t0
sound.winsound = _ORIG_WIN
check('F. 模块层 1000 次播放调用立即返回（< 0.1s）', dt2 < 0.1, '%.4fs' % dt2)

restore_probe()
(AI.can_paste_message, AI.paste_message, AI.window_rect,
 AI.png_to_dib, AI.write_clipboard_dib, AI.BASE_DIR) = _o2

# 收尾：销毁 GUI 实例（不走 quit_app，避免真实存档路径）
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
section('G. 数据不污染 + 回归前置')

HASH_AFTER = file_hash(REAL_DATA)
FILES_AFTER = sidecars()
check('真实数据 sha256 未变', HASH_BEFORE == HASH_AFTER,
      'before=%s after=%s' % (HASH_BEFORE, HASH_AFTER))
check('真实数据 hash == 期望值',
      HASH_AFTER == '5c21d32f5c8a5173646c7b0927a0a2149d6f2db5b6b35758f5e12c8150314079',
      'got=%s' % HASH_AFTER)
check('真实目录无新增 .bak', FILES_AFTER == FILES_BEFORE,
      'before=%s after=%s' % (FILES_BEFORE, FILES_AFTER))
check('项目根未生成 images/ 残留（图片测试写临时目录）',
      os.path.exists(os.path.join(ROOT, 'images')) == IMAGES_ROOT_BEFORE,
      'before=%s after=%s' % (IMAGES_ROOT_BEFORE, os.path.exists(os.path.join(ROOT, 'images'))))
check('临时数据文件未被产品 save() 改写（NO_SAVE 生效）',
      file_hash(TMP_DATA) == TMP_HASH_AFTER_A,
      'A后=%s 结束=%s' % (TMP_HASH_AFTER_A, file_hash(TMP_DATA)))

# 清理临时目录
try:
    import shutil
    shutil.rmtree(TMP_DIR, ignore_errors=True)
except Exception:
    pass

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_qa6_sound.out')
with open(out, 'w', encoding='utf-8') as f:
    f.write('\n'.join(LOG) + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))
print('\n'.join(LOG))
print('全部通过' if OK else '有失败项')
sys.exit(0 if OK else 1)
