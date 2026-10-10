# -*- coding: utf-8 -*-
"""P1-2 音效反馈回归自测。

覆盖：
1. 两个设置项 sound_copy / sound_paste 存在于 DEFAULT_SETTINGS 且默认 False；
   validate 对缺字段补默认值、对显式 True 予以保留。
2. 音效模块：两个音可区分（字节/音高/节奏不同）、均为合法 16-bit 单声道 WAV、
   时长 ≤150ms、播放走 SND_MEMORY|SND_ASYNC（异步，不阻塞）。
3. 静默失败：底层 PlaySound 抛异常、或根本没有 winsound（非 Windows），
   调用方都收不到异常，绝不影响主流程。
4. 复制音：只在「剪贴板确实记下一条内容」时响 —— 轮询但序列号没变不响、
   序列号变了但内容为空不响、有新内容响一次、manual=True（拆词/变换）不响、
   开关关闭时不响。
5. 粘贴音：粘贴动作成功执行时响一次；开关关闭不响；只是把内容放进剪贴板、
   并不真的去贴（autopaste 关且未 force、面板隐藏）时不响。
6. 不阻塞：播放调用立即返回；粘贴路径不因音效卡顿。
7. 数据文件未被污染：真实 ClawBoard数据.json 的 sha256 前后一致、无新增 .bak。

不污染真实数据的做法（沿用 _t38 的踩坑经验）：import 业务模块之前，把
app_services.DATA_FILE 与 timefmt.DATA_FILE **两个**都重定向到临时目录，并置
runtime.NO_SAVE=True（另设 C.NO_SAVE=True 双保险）。只重定向一个会让
backup_data() 把真实存档复制成 .bak.1。
"""
import ctypes
import hashlib
import io
import os
import sys
import tempfile
import time
import wave

# DPI 感知必须在建 Tk 前打开
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ---- 重定向落盘目标（必须在 import 业务模块之前）----
TMP_DIR = tempfile.mkdtemp(prefix='cb_t39_')
TMP_DATA = os.path.join(TMP_DIR, 'ClawBoard数据.json')

import clawboard.app_services as S          # noqa: E402
S.DATA_FILE = TMP_DATA
S.CRASH_LOG = os.path.join(TMP_DIR, 'crash.log')

# backup_data() 用的是 timefmt 命名空间里的 DATA_FILE 副本，必须一起重定向，
# 否则迁移分支会把真实存档复制成 .bak.1（本项目踩过的坑）。
import clawboard.timefmt as TF              # noqa: E402
TF.DATA_FILE = TMP_DATA

from clawboard import runtime as RT         # noqa: E402
RT.NO_SAVE = True

from clawboard import sound                 # noqa: E402
from clawboard.config import DEFAULT_SETTINGS  # noqa: E402
from clawboard.app_services import DataMixin   # noqa: E402

OK = True
LOG = []


def check(name, cond, extra=''):
    global OK
    if not cond:
        OK = False
    LOG.append('%s  %s%s' % ('OK  ' if cond else 'FAIL', name,
                             ('  ' + extra) if extra else ''))


REAL_DATA = os.path.join(ROOT, 'ClawBoard数据.json')


def file_hash(p):
    try:
        with open(p, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return None


def sidecars():
    import glob
    return sorted(os.path.basename(p) for p in glob.glob(REAL_DATA + '*'))


HASH_BEFORE = file_hash(REAL_DATA)
FILES_BEFORE = sidecars()

# ---------- 1. 设置项存在且默认关 ----------
check('sound_copy 存在于 DEFAULT_SETTINGS', 'sound_copy' in DEFAULT_SETTINGS)
check('sound_paste 存在于 DEFAULT_SETTINGS', 'sound_paste' in DEFAULT_SETTINGS)
check('sound_copy 默认 False', DEFAULT_SETTINGS.get('sound_copy') is False)
check('sound_paste 默认 False', DEFAULT_SETTINGS.get('sound_paste') is False)

_v = DataMixin.validate({'clip': [], 'groups': [], 'settings': {}, 'schema_version': 3})
check('validate 补默认：sound_copy=False', _v['settings'].get('sound_copy') is False)
check('validate 补默认：sound_paste=False', _v['settings'].get('sound_paste') is False)

_v2 = DataMixin.validate({'clip': [], 'groups': [],
                          'settings': {'sound_copy': True, 'sound_paste': True},
                          'schema_version': 3})
check('validate 保留显式 True',
      _v2['settings'].get('sound_copy') is True
      and _v2['settings'].get('sound_paste') is True)

# 老数据（没有这两个字段）读进来仍是 False，格式向后兼容
_v3 = DataMixin.validate({'clip': [], 'groups': [],
                          'settings': {'theme': 'dark', 'listen': True}, 'schema_version': 3})
check('老设置无新字段 → 兼容为 False',
      _v3['settings'].get('sound_copy') is False
      and _v3['settings'].get('sound_paste') is False)

# ---------- 2. 音效模块本身 ----------
check('winsound 可用（Windows）', sound.winsound is not None)
check('两个音字节不同（可区分）', sound.COPY_WAV != sound.PASTE_WAV)
check('复制音首音高于粘贴音首音（音高可辨）',
      sound.COPY_TONE[0][0] > sound.PASTE_TONE[0][0],
      'copy=%.0f paste=%.0f' % (sound.COPY_TONE[0][0], sound.PASTE_TONE[0][0]))
check('粘贴音为多段（节奏可辨）', len(sound.PASTE_TONE) >= 2)


def _dur_ms(data):
    with wave.open(io.BytesIO(data), 'rb') as w:
        return 1000.0 * w.getnframes() / w.getframerate()


check('复制音 ≤150ms', _dur_ms(sound.COPY_WAV) <= 150.0, '%.1fms' % _dur_ms(sound.COPY_WAV))
check('粘贴音 ≤150ms', _dur_ms(sound.PASTE_WAV) <= 150.0, '%.1fms' % _dur_ms(sound.PASTE_WAV))
check('复制音是合法 RIFF/WAVE',
      sound.COPY_WAV[:4] == b'RIFF' and sound.COPY_WAV[8:12] == b'WAVE')
check('粘贴音是合法 RIFF/WAVE',
      sound.PASTE_WAV[:4] == b'RIFF' and sound.PASTE_WAV[8:12] == b'WAVE')

_ORIG_WIN = sound.winsound

# 记录 flags：必须是 SND_MEMORY|SND_ASYNC，且传入内存 bytes
seen = []


class _Rec:
    SND_MEMORY = 4
    SND_ASYNC = 1

    @staticmethod
    def PlaySound(data, flags):
        seen.append((type(data), flags))


sound.winsound = _Rec
t0 = time.perf_counter()
for _ in range(200):
    sound.play_copy()
    sound.play_paste()
dt = time.perf_counter() - t0
sound.winsound = _ORIG_WIN
check('播放走 SND_MEMORY|SND_ASYNC（异步）',
      bool(seen) and all(f == (4 | 1) for _, f in seen), 'flags=%r' % (seen[:1],))
check('传入的是内存 bytes（非文件/别名）',
      bool(seen) and all(d is bytes for d, _ in seen))
check('播放调用立即返回（400 次 < 0.1s）', dt < 0.1, '%.4fs' % dt)


# 底层抛异常 → 调用方收不到
class _Boom:
    SND_MEMORY = 4
    SND_ASYNC = 1

    @staticmethod
    def PlaySound(*a, **k):
        raise RuntimeError('no audio device')


sound.winsound = _Boom
_prop = True
try:
    sound.play_copy()
    sound.play_paste()
    sound.play_wav(b'x')
except Exception:
    _prop = False
sound.winsound = _ORIG_WIN
check('底层异常不向调用方传播（静默失败）', _prop)

# 无 winsound（非 Windows）→ 静默
sound.winsound = None
try:
    sound.play_copy()
    sound.play_paste()
    _none_ok = True
except Exception:
    _none_ok = False
sound.winsound = _ORIG_WIN
check('无 winsound 时静默（非 Windows 友好）', _none_ok)

# 空数据 → 不播放、不报错
sound.winsound = _Rec
seen.clear()
sound.play_wav(b'')
sound.winsound = _ORIG_WIN
check('空数据不播放（防御式）', seen == [])

# ---------- 3. GUI 闭环：复制音 / 粘贴音 ----------
import tkinter as tk          # noqa: E402
import ClawBoard as C         # noqa: E402

C.NO_SAVE = True              # 模块属性桥接到 runtime.NO_SAVE（双保险）

root = tk.Tk()
root.geometry('420x560+80+80')
app = C.ClawBoard(root)
if app.collapsed:
    app.collapsed = False
    app.st['collapsed'] = False
    app.body.pack(fill='both', expand=True)
    app.root.minsize(*app.min_size())
root.update()

# ---- 探针：把播放函数整体替换为计数器 ----
calls = {'copy': 0, 'paste': 0}


def _probe_copy():
    calls['copy'] += 1


def _probe_paste():
    calls['paste'] += 1


sound.play_copy = _probe_copy
sound.play_paste = _probe_paste

# ---- 3a. 复制音：挂钩在 ingest（只在真正新增记录时响）----
_orig_seq, _orig_read, _orig_files, _orig_priv, _orig_img = (
    S.clip_seq, S.clip_read, S.clip_read_files, S.clip_is_private, S.clipboard_has_image)

app.st['sound_copy'] = True
app.st['listen'] = True

# (a) 剪贴板序列号没变（轮询到但没变化）→ 不响
calls['copy'] = 0
S.clip_seq = lambda: RT.LAST_SEQ
app.poll_clip()
check('复制音：剪贴板没变化时不响', calls['copy'] == 0, '实际 %d' % calls['copy'])

# (b) 序列号变了但内容为空 → 不响
calls['copy'] = 0
S.clip_is_private = lambda: False
S.clipboard_has_image = lambda: False
S.clip_read = lambda: ''
S.clip_read_files = lambda: []
S.clip_seq = lambda: RT.LAST_SEQ + 1
app.poll_clip()
check('复制音：内容为空时不响', calls['copy'] == 0, '实际 %d' % calls['copy'])

# (c) 序列号变了且有内容 → 响一次
calls['copy'] = 0
S.clip_read = lambda: '这是一条新的剪贴板内容'
S.clip_seq = lambda: RT.LAST_SEQ + 1
app.poll_clip()
check('复制音：记下新内容时响一次', calls['copy'] == 1, '实际 %d' % calls['copy'])

# (d) manual=True（拆词/变换）不算「复制」→ 不响
calls['copy'] = 0
app.ingest('手动拆出来的内容', manual=True)
check('复制音：manual=True 不响', calls['copy'] == 0, '实际 %d' % calls['copy'])

# (e) 开关关闭 → 有新内容也不响
calls['copy'] = 0
app.st['sound_copy'] = False
S.clip_read = lambda: '又一条新内容'
S.clip_seq = lambda: RT.LAST_SEQ + 1
app.poll_clip()
check('复制音：开关关闭时不响', calls['copy'] == 0, '实际 %d' % calls['copy'])

# 恢复剪贴板读取相关
(S.clip_seq, S.clip_read, S.clip_read_files, S.clip_is_private,
 S.clipboard_has_image) = (_orig_seq, _orig_read, _orig_files, _orig_priv, _orig_img)

# ---- 3c. 复制音：图片入库路径（走 _ingest_image，不经过 ingest）----
# 图片由 poll_clip 的独立分支处理，与文本分支互斥；这里同时验证「会响」与「不重复响」。
_orig_base = S.BASE_DIR
_orig_dib, _orig_png = S.read_clipboard_dib, S.dib_to_png
_orig_seq2, _orig_priv2, _orig_img2 = S.clip_seq, S.clip_is_private, S.clipboard_has_image
S.BASE_DIR = TMP_DIR                       # 图片写临时目录，绝不碰项目 images/
S.read_clipboard_dib = lambda: b'FAKE-DIB'
S.dib_to_png = lambda dib: (b'\x89PNG\r\n\x1a\nFAKE-IMG', 8, 6)

# (a) 直接调 _ingest_image：开关关闭 → 不响
calls['copy'] = 0
app.st['sound_copy'] = False
app._ingest_image()
check('复制音：图片路径开关关闭时不响', calls['copy'] == 0, '实际 %d' % calls['copy'])

# (b) 开关开启 → 响一次，且图片确已入历史
calls['copy'] = 0
app.st['sound_copy'] = True
app._ingest_image()
check('复制音：记下图片时响一次', calls['copy'] == 1, '实际 %d' % calls['copy'])
check('图片确已入历史（确实走了图片入库路径）',
      any(x.get('content_type') == 'image' for x in app.data['clip']))

# (c) 端到端：轮询到图片 → 恰好响 1 次（图片/文本分支互斥，不重复响）
RT.LAST_SEQ = 5000
S.clip_seq = lambda: 5001
S.clip_is_private = lambda: False
S.clipboard_has_image = lambda: True
calls['copy'] = 0
app.poll_clip()
check('复制音：轮询图片恰好响 1 次（不重复）', calls['copy'] == 1, '实际 %d' % calls['copy'])

# 还原
S.BASE_DIR = _orig_base
S.read_clipboard_dib, S.dib_to_png = _orig_dib, _orig_png
S.clip_seq, S.clip_is_private, S.clipboard_has_image = _orig_seq2, _orig_priv2, _orig_img2

# ---- 3b. 粘贴音：挂钩在 paste（粘贴动作成功执行后响）----
import clawboard.app_interact as AI          # noqa: E402
_orig_cpm, _orig_pm = AI.can_paste_message, AI.paste_message
AI.can_paste_message = lambda hwnd: True      # 一律走「可直接投递」分支
AI.paste_message = lambda hwnd: None          # 投递线程变空操作，避免真去贴
app.write_clip = lambda text: True            # 不碰真实系统剪贴板
app.prev_hwnd = None
app.hidden = False
app.st['autopaste'] = True

# (a) 开关关闭 → 不响
calls['paste'] = 0
app.st['sound_paste'] = False
r = app.paste('粘贴测试文本', force=True)
check('粘贴音：开关关闭时不响', calls['paste'] == 0, '实际 %d' % calls['paste'])
check('粘贴：仍正常返回 True', r is True)

# (b) 开关开启 → 粘贴成功执行时响一次
calls['paste'] = 0
app.st['sound_paste'] = True
r = app.paste('再粘一次', force=True)
check('粘贴音：粘贴执行时响一次', calls['paste'] == 1, '实际 %d' % calls['paste'])

# (c) 只是把内容放进剪贴板、并不真的去贴（autopaste 关 + 未 force + 面板隐藏）→ 不响
calls['paste'] = 0
app.st['autopaste'] = False
app.hidden = True
r = app.paste('只是复制，不粘贴', force=False)
check('粘贴音：仅复制不粘贴时不响', calls['paste'] == 0, '实际 %d' % calls['paste'])

# (d) 不阻塞：连续 50 次粘贴，音效不拖慢路径，且各响一次
calls['paste'] = 0
app.st['sound_paste'] = True
app.st['autopaste'] = True
app.hidden = False
t0 = time.perf_counter()
for _ in range(50):
    app.paste('x', force=True)
dt = time.perf_counter() - t0
check('粘贴路径不因音效阻塞（50 次 < 0.5s）', dt < 0.5, '%.4fs' % dt)
check('50 次粘贴各响一次（探针=50）', calls['paste'] == 50, '实际 %d' % calls['paste'])

# 还原被替换的函数
AI.can_paste_message, AI.paste_message = _orig_cpm, _orig_pm

# 清理 GUI 实例（不调用 quit_app，避免触发真实存档路径）
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

# ---------- 4. 真实数据文件未被污染 ----------
HASH_AFTER = file_hash(REAL_DATA)
check('真实数据文件 hash 未变', HASH_BEFORE == HASH_AFTER,
      'before=%s after=%s' % (HASH_BEFORE, HASH_AFTER))
check('真实数据目录无新增 .bak 副本', sidecars() == FILES_BEFORE,
      'before=%s after=%s' % (FILES_BEFORE, sidecars()))
check('临时数据文件未被写入（NO_SAVE 生效）', not os.path.exists(TMP_DATA),
      '存在=%s' % os.path.exists(TMP_DATA))

# 清理临时目录（图片测试会写 TMP_DIR/images/，用 rmtree 一并清掉）
try:
    import shutil
    shutil.rmtree(TMP_DIR, ignore_errors=True)
except Exception:
    pass

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_t39.out')
with open(out, 'w', encoding='utf-8') as f:
    f.write('\n'.join(LOG) + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))
print('\n'.join(LOG), flush=True)
print('全部通过' if OK else '有失败项', flush=True)
os._exit(0)
