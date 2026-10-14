# -*- coding: utf-8 -*-
"""QA 独立验证：ClawBoard「补记程序未运行时复制的内容」（commit 5f6f9b8 + 783db92）。

作者：严过关（QA）。与工程师自测 _t42.py **独立**：换用例组织、换断言角度、
覆盖 _t42 未覆盖的边界（文件路径补记、smart_private 关掉后私密仍入库、
ignore 规则在补记路径的实证、只比最新一条导致的深层重复、toast 也未被补记触发……）。

设计：
- 剪贴板全程 stub（本机剪贴板被外部进程锁定：_t35/_t37 已知环境问题）。
  用一个带状态的「假剪贴板」模型驱动，既能测补记（catchup）也能测实时轮询（poll_clip）。
- capture_source / window_title_of 可配，用来独立复现「忽略名单在补记路径失效」。
- sound.play_copy / app.tip / app.show_copy_toast / app.render 换成探针，断言副作用次数。
- 数据安全：import 业务模块前把 app_services.DATA_FILE / app_services.BASE_DIR /
  timefmt.DATA_FILE 指向临时目录，并 NO_SAVE=True。
- 绝不修改产品源码。
- 不使用 os._exit（避免丢 stdout）。
"""
import ctypes
import glob
import hashlib
import os
import sys
import tempfile

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ---- 重定向落盘目标（必须在 import 业务模块之前）----
TMP_DIR = tempfile.mkdtemp(prefix='cb_qa9_')
TMP_DATA = os.path.join(TMP_DIR, 'ClawBoard数据.json')

import clawboard.app_services as S            # noqa: E402
S.DATA_FILE = TMP_DATA
S.CRASH_LOG = os.path.join(TMP_DIR, 'crash.log')
S.BASE_DIR = TMP_DIR                          # 图片落盘也走临时目录

import clawboard.timefmt as TF                # noqa: E402
TF.DATA_FILE = TMP_DATA

from clawboard import runtime as RT           # noqa: E402
RT.NO_SAVE = True

from clawboard.onboard import is_empty_data   # noqa: E402

OK = True
LOG = []
_LOGF = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          '_qa9_catchup.out'), 'w', encoding='utf-8')


def _emit(line):
    LOG.append(line)
    try:
        _LOGF.write(line + '\n')
        _LOGF.flush()
    except Exception:
        pass
    print(line, flush=True)


def check(name, cond, extra=''):
    global OK
    if not cond:
        OK = False
    _emit('%s  %s%s' % ('OK  ' if cond else 'FAIL', name,
                        ('  ' + extra) if extra else ''))


def section(t):
    _emit('')
    _emit('== %s ==' % t)


REAL_DATA = os.path.join(ROOT, 'ClawBoard数据.json')
EXPECT_HASH = '5c21d32f5c8a5173646c7b0927a0a2149d6f2db5b6b35758f5e12c8150314079'


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
# 带状态的「假剪贴板」
# ============================================================
CLIP = {'seq': 111, 'kind': 'empty', 'text': None, 'private': False,
        'image': None, 'files': []}
# 来源：可配，用来复现「补记时拿到的只是当前前台窗口」
SRC = {'app': 'clipstub.exe', 'hwnd': 12345, 'title': 'Stub Window'}


def _stub_seq():
    return CLIP['seq']


def _stub_is_private():
    return bool(CLIP['private'])


def _stub_has_image():
    return CLIP['kind'] == 'image'


def _stub_read():
    return CLIP['text'] if CLIP['kind'] == 'text' else None


def _stub_read_files():
    return list(CLIP['files'] or [])


def _stub_read_dib():
    return b'DIBMARK' if CLIP['kind'] == 'image' else None


def _stub_dib_to_png(dib):
    return CLIP['image']


def _stub_capture_source(*a, **k):
    return (SRC['app'], SRC['hwnd'])


def _stub_window_title(hwnd):
    return SRC['title']


S.clip_seq = _stub_seq
S.clip_is_private = _stub_is_private
S.clipboard_has_image = _stub_has_image
S.clip_read = _stub_read
S.clip_read_files = _stub_read_files
S.read_clipboard_dib = _stub_read_dib
S.dib_to_png = _stub_dib_to_png
S.capture_source = _stub_capture_source
S.window_title_of = _stub_window_title

import tkinter as tk          # noqa: E402
import ClawBoard as C         # noqa: E402

C.NO_SAVE = True

# 副作用探针
PLAY = {'n': 0}
TIPS = []
TOASTS = []
RENDERS = {'n': 0}

root = tk.Tk()
root.geometry('420x560+80+80')
app = C.ClawBoard(root)
if app.collapsed:
    app.collapsed = False
    app.st['collapsed'] = False
    app.body.pack(fill='both', expand=True)
    app.root.minsize(*app.min_size())
root.update()

# 换探针（实例属性遮蔽方法）
_orig_play = S.sound.play_copy
S.sound.play_copy = lambda: PLAY.__setitem__('n', PLAY['n'] + 1)
app.tip = lambda t: TIPS.append(t)
app.show_copy_toast = lambda t: TOASTS.append(t)
app.render = lambda: RENDERS.__setitem__('n', RENDERS['n'] + 1)


def item(text, **kw):
    d = {'id': 'it_%d' % id(text), 'text': text, 'created_at': 1000, 'updated_at': 1000,
         'seq': 1, 'content_type': 'text', 'copy_count': 1, 'fav': 0, 'is_estimated': 0}
    d.update(kw)
    return d


def set_lib(items, phrases=None):
    app.data['clip'] = list(items)
    if phrases is None:
        app.data['groups'] = [{'name': '默认', 'items': []}]
    else:
        app.data['groups'] = [{'name': '默认', 'items': list(phrases)}]


def clip(kind='empty', text=None, private=False, image=None, files=None, seq=None):
    CLIP['kind'] = kind
    CLIP['text'] = text
    CLIP['private'] = private
    CLIP['image'] = image
    CLIP['files'] = files or []
    if seq is not None:
        CLIP['seq'] = seq
    else:
        CLIP['seq'] += 1


def reset_probes():
    PLAY['n'] = 0
    del TIPS[:]
    del TOASTS[:]
    RENDERS['n'] = 0


# 基线设置：监听开、smart_private 开、skip_sensitive 关、无忽略名单
def base_settings():
    app.st['listen'] = True
    app.st['smart_private'] = True
    app.st['skip_sensitive'] = False
    app.st['sound_copy'] = False
    app.st['show_toast'] = True
    app.st['min_len'] = 1
    app.st['max_len'] = 0
    app.st['record_title'] = False
    app.st['ignore_apps'] = ''
    app.st['ignore_titles'] = ''


base_settings()
SRC.update({'app': 'clipstub.exe', 'hwnd': 12345, 'title': 'Stub Window'})

# ============================================================
# A. 重构回归：实时记录路径（_handle_clipboard_change quiet=False/dedup=False）
#    —— 这是 poll_clip 在「序列号变化」时唯一调用的东西
# ============================================================
section('A1. 实时复制文本 → 记录 1 条（内容/来源/时间戳/复制音）')
set_lib([])
base_settings()
app.st['sound_copy'] = True          # 打开复制音：验证 quiet 没误伤常规路径
reset_probes()
clip('text', text='实时复制的一段文本')
r = app._handle_clipboard_change()   # poll_clip 的原样调用
check("返回 'text'", r == 'text', 'got=%r' % r)
check('记录 1 条', len(app.data['clip']) == 1, 'n=%d' % len(app.data['clip']))
it = app.data['clip'][0]
check('内容正确', it.get('text') == '实时复制的一段文本')
check('来源正确（stub capture_source）', it.get('source_app') == 'clipstub.exe',
      'src=%r' % it.get('source_app'))
check('created_at 为真实时间戳（非估算）',
      isinstance(it.get('created_at'), int) and it.get('is_estimated') == 0)
check('实时文本路径仍播复制音 1 次（quiet 未误伤）', PLAY['n'] == 1, 'n=%d' % PLAY['n'])
check('实时文本路径仍弹 toast 1 次', len(TOASTS) == 1, 'n=%d' % len(TOASTS))

section('A2. 实时复制文件（CF_HDROP，无文本）→ 记录路径文本')
paths = ['C:\\tmp\\a.txt', 'C:\\tmp\\b.txt']
set_lib([])
base_settings()
reset_probes()
clip('empty')                        # 无文本、无图片
CLIP['files'] = list(paths)
r = app._handle_clipboard_change()
check("返回 'text'", r == 'text', 'got=%r' % r)
check('记录 1 条', len(app.data['clip']) == 1)
check('多条路径用换行连接', app.data['clip'][0].get('text') == '\n'.join(paths),
      'got=%r' % app.data['clip'][0].get('text'))

section('A3. 实时复制图片 → 记录图片条目（含落盘/复制音）')
img_dir = os.path.join(TMP_DIR, 'images')
os.makedirs(img_dir, exist_ok=True)
PNG_A = b'\x89PNG\r\n\x1a\nA' + b'a' * 32
PNG_B = b'\x89PNG\r\n\x1a\nB' + b'b' * 32
with open(os.path.join(img_dir, 'imgA.png'), 'wb') as f:
    f.write(PNG_A)
set_lib([])
base_settings()
app.st['sound_copy'] = True
reset_probes()
clip('image', image=(PNG_A, 12, 7))
r = app._handle_clipboard_change()
check("返回 'image'", r == 'image', 'got=%r' % r)
check('记录 1 条图片', len(app.data['clip']) == 1 and
      app.data['clip'][0].get('content_type') == 'image')
check('图片文件已落盘', os.path.exists(
    os.path.join(img_dir, app.data['clip'][0].get('image_path', ''))))
check('图片路径仍播复制音 1 次', PLAY['n'] == 1, 'n=%d' % PLAY['n'])
check('图片路径仍弹已记录提示 1 次',
      any('已记录图片' in t for t in TIPS), 'tips=%r' % TIPS)

section('A4. 实时「别记录我」(smart_private 开) → 跳过并 tip')
set_lib([])
base_settings()
reset_probes()
clip('text', text='私密内容', private=True)
r = app._handle_clipboard_change()
check("返回 'private'", r == 'private', 'got=%r' % r)
check('未入库', app.data['clip'] == [])
check('非静默时有 tip', any('不要记录' in t for t in TIPS), 'tips=%r' % TIPS)

section('A5. 实时 smart_private 关 → 私密标记被忽略，照常入库')
set_lib([])
base_settings()
app.st['smart_private'] = False
reset_probes()
clip('text', text='私密内容但关了遵守', private=True)
r = app._handle_clipboard_change()
check("smart_private=False → 返回 'text' 并入库", r == 'text' and
      len(app.data['clip']) == 1, 'r=%r n=%d' % (r, len(app.data['clip'])))

section('A6. 实时 skip_sensitive 命中 → 不入库 + tip')
set_lib([])
base_settings()
app.st['skip_sensitive'] = True
reset_probes()
clip('text', text='我的手机号 13800138000')
r = app._handle_clipboard_change()
check("返回 'sensitive'", r == 'sensitive', 'got=%r' % r)
check('未入库', app.data['clip'] == [])
check('有提示', any('不入库' in t for t in TIPS), 'tips=%r' % TIPS)

section('A7. 实时超长文本 → 按 MAX_TEXT 截断')
# 用带空格的超长文本：既能超过 MAX_TEXT 触发截断，又不会踩到 P 节发现的 O(n^2) 正则
# （长"单词型"文本才退化；带空格会把 [\w.+-]+ 的匹配段切短）
_suffix = '\n…（内容超长已截断）'
set_lib([])
base_settings()
reset_probes()
clip('text', text='x ' * (S.MAX_TEXT // 2 + 5))    # 长度 > MAX_TEXT
r = app._handle_clipboard_change()
it = app.data['clip'][0]
check('入库 1 条', len(app.data['clip']) == 1)
check('已截断到 MAX_TEXT 并加后缀',
      it['text'].endswith(_suffix) and len(it['text']) == S.MAX_TEXT + len(_suffix),
      'len=%d' % len(it['text']))
check('截断后前段内容保留', it['text'][:20] == 'x ' * 10)

section('A8. listen=False → poll_clip 不记录、不抛')
set_lib([])
base_settings()
app.st['listen'] = False
clip('text', text='监听关闭时不应该记录')
RT.LAST_SEQ = CLIP['seq']            # 先对齐
clip('text', text='变了序列号也不该记')
RT.LAST_SEQ = CLIP['seq'] - 1        # 制造"序列号变化"
try:
    app.poll_clip()                  # 应早退（listen=False），不记录、不抛
    threw = None
except Exception as e:
    threw = e
check('listen=False 时 poll_clip 不抛', threw is None, 'exc=%r' % threw)
check('listen=False 时不记录', app.data['clip'] == [])
check('listen=False 时同步基线 LAST_SEQ', RT.LAST_SEQ == CLIP['seq'],
      'LAST_SEQ=%r seq=%r' % (RT.LAST_SEQ, CLIP['seq']))

section('A9. 实时轮询集成：seq 变化才记录、不变不记录')
set_lib([])
base_settings()
app.st['listen'] = True
clip('text', text='轮询文本1')
RT.LAST_SEQ = CLIP['seq']
app.poll_clip()                      # seq 未变 → 不记
check('seq 未变 → 不记', app.data['clip'] == [], 'n=%d' % len(app.data['clip']))
clip('text', text='轮询文本2')       # seq++
app.poll_clip()                      # seq 变 → 记
check('seq 变 → 记 1 条', len(app.data['clip']) == 1 and
      app.data['clip'][0]['text'] == '轮询文本2',
      'n=%d' % len(app.data['clip']))
app.poll_clip()                      # 再 poll 同 seq → 不重复
check('同 seq 再 poll 不重复', len(app.data['clip']) == 1)

# ============================================================
# B. 补记逻辑（核心）
# ============================================================
section('B1. 库为空 → 不补读，且 is_empty_data 仍 True（保住首启引导）')
set_lib([])
base_settings()
reset_probes()
clip('text', text='程序没运行时复制的内容')
r = app.catchup_clipboard()
check('返回 False', r is False, 'got=%r' % r)
check('clip 仍为空', app.data['clip'] == [])
check('onboard.is_empty_data 仍 True', is_empty_data(app.data) is True)

section('B2. 库非空 + 与最新一条不同 → 恰好补 1 条')
set_lib([item('已存在')])
base_settings()
reset_probes()
clip('text', text='关程序期间新复制')
r = app.catchup_clipboard()
check('返回 True', r is True, 'got=%r' % r)
check('恰好补 1 条', len(app.data['clip']) == 2, 'n=%d' % len(app.data['clip']))
check('补的在首位且内容正确', app.data['clip'][0]['text'] == '关程序期间新复制')
check('补记成功 tip 文案正确',
      len(TIPS) == 1 and '已补记程序未运行时复制的内容' in TIPS[0], 'tips=%r' % TIPS)

section('B3. 库非空 + 与最新一条相同 → 不补（去重）')
set_lib([item('同一条')])
base_settings()
reset_probes()
clip('text', text='同一条')
r = app.catchup_clipboard()
check('返回 False', r is False)
check('条数不变', len(app.data['clip']) == 1)
check('去重时不 tip', TIPS == [], 'tips=%r' % TIPS)

section('B4. 剪贴板为空 → 不补')
set_lib([item('x')])
base_settings()
reset_probes()
clip('empty')
r = app.catchup_clipboard()
check('返回 False', r is False)
check('条数不变', len(app.data['clip']) == 1)
check('空剪贴板不 tip', TIPS == [])

section('B5. listen=False → 不补')
set_lib([item('x')])
base_settings()
app.st['listen'] = False
reset_probes()
clip('text', text='监听关闭期间复制')
r = app.catchup_clipboard()
check('返回 False', r is False)
check('条数不变', len(app.data['clip']) == 1)

section('B6. 图片补记去重（相同/不同/最新非图片）')
base_settings()
# B6a 相同 → 不补
set_lib([item('[图片]', content_type='image', image_path='imgA.png')])
reset_probes()
clip('image', image=(PNG_A, 10, 10))
r = app.catchup_clipboard()
check('图片与最新一条相同 → 不补', r is False and len(app.data['clip']) == 1,
      'r=%r' % r)
# B6b 不同 → 补
set_lib([item('[图片]', content_type='image', image_path='imgA.png')])
reset_probes()
clip('image', image=(PNG_B, 10, 10))
r = app.catchup_clipboard()
check('图片不同 → 补 1 张', r is True and len(app.data['clip']) == 2 and
      app.data['clip'][0]['content_type'] == 'image', 'r=%r n=%d' % (r, len(app.data['clip'])))
check('补的图片已落盘', os.path.exists(
    os.path.join(img_dir, app.data['clip'][0]['image_path'])))
# B6c 最新一条不是图片 → 补
set_lib([item('一段文本')])
reset_probes()
clip('image', image=(PNG_B, 10, 10))
r = app.catchup_clipboard()
check('最新一条不是图片 → 补', r is True and len(app.data['clip']) == 2, 'r=%r' % r)

section('B7. 私密 / skip_sensitive → 不补')
set_lib([item('x')])
base_settings()
reset_probes()
clip('text', text='带别记录我标记', private=True)
r = app.catchup_clipboard()
check('smart_private → 不补', r is False and len(app.data['clip']) == 1, 'r=%r' % r)
app.st['skip_sensitive'] = True
set_lib([item('x')])
reset_probes()
clip('text', text='我的手机号 13800138000', private=False)
r = app.catchup_clipboard()
check('skip_sensitive → 不补', r is False and len(app.data['clip']) == 1, 'r=%r' % r)

section('B8. 重复调用不重复补')
base_settings()
set_lib([item('第一条')])
clip('text', text='第二条')
r1 = app.catchup_clipboard()
r2 = app.catchup_clipboard()
r3 = app.catchup_clipboard()
check('首次 True / 后续 False', r1 is True and r2 is False and r3 is False,
      'r=%r,%r,%r' % (r1, r2, r3))
check('只补一条', len(app.data['clip']) == 2)

section('B9. 补记不播复制音（文本 + 图片路径，探针 0 次）')
base_settings()
app.st['sound_copy'] = True
reset_probes()
set_lib([item('x')])
clip('text', text='补记文本')
app.catchup_clipboard()
set_lib([item('x')])
clip('image', image=(PNG_B, 6, 6))
app.catchup_clipboard()
check('文本+图片补记均不播复制音', PLAY['n'] == 0, 'n=%d' % PLAY['n'])
check('补记不弹 copy toast', TOASTS == [], 'toasts=%r' % TOASTS)
app.st['sound_copy'] = False

section('B10. 文件路径补记 → 记录路径文本（_t42 未覆盖）')
base_settings()
set_lib([item('旧内容')])
reset_probes()
clip('empty')
CLIP['files'] = ['D:\\work\\report.docx']
r = app.catchup_clipboard()
check('文件路径补记成功', r is True and len(app.data['clip']) == 2 and
      app.data['clip'][0]['text'] == 'D:\\work\\report.docx', 'r=%r' % r)

section('B11. 触发点②：监听由关变开 → 补一次')
base_settings()
set_lib([item('已有')])
app.st['listen'] = True
app.toggle_listen()                   # → False
check('toggle 后 listen=False', app.st['listen'] is False)
clip('text', text='关闭监听期间复制的内容')
app.toggle_listen()                   # → True，应触发补记
check('重开监听补记了关闭期间的内容',
      any(x.get('text') == '关闭监听期间复制的内容' for x in app.data['clip']))
check('重开后 listen=True', app.st['listen'] is True)

section('B12. 库为空但"常用语"非空 → 会补记（is_empty_data 只看整库）')
# 常用语有内容、clip 为空：引导卡片本来也不会显示，补记应正常发生
set_lib([], phrases=[{'id': 'p1', 'name': 'p', 'text': '常用语'}])
base_settings()
reset_probes()
clip('text', text='补进 clip')
check('is_empty_data=False（组非空）', is_empty_data(app.data) is False)
r = app.catchup_clipboard()
check('补记发生', r is True and len(app.data['clip']) == 1, 'r=%r' % r)

section('B13. catchup 只比"最新一条"，但 ingest 的全库去重兜底 → 不产生重复行')
# clip=[B, A]，剪贴板=A：A 已在库中(第2条)但不在首位。
# catchup 的 _is_dup_text 只比 clip[0]='B' → 判为"非重复" → 调 ingest；
# 而 ingest 内部对全库查重 → 命中已有的 A → 仅置顶+计数，不会新增重复行。
set_lib([item('B'), item('A')])
base_settings()
reset_probes()
clip('text', text='A')
r = app.catchup_clipboard()
texts = [x['text'] for x in app.data['clip']]
check('不产生重复行（ingest 全库去重兜底）', texts == ['A', 'B'], 'clip=%r' % texts)
check('原 A 被置顶并计数+1', app.data['clip'][0]['text'] == 'A' and
      int(app.data['clip'][0].get('copy_count') or 1) >= 2, 'clip=%r' % texts)
check('（信息项）此情形 catchup 仍返回 True（内容已在库中，仅刷新置顶）',
      r is True, 'r=%r' % r)

# ============================================================
# C. 长度过滤一致性（本轮修复重点）
# ============================================================
section('C1. quiet=True 仍应用 min_len：不补且不误报"已补记"')
base_settings()
app.st['min_len'] = 5
set_lib([item('已有')])
reset_probes()
clip('text', text='ab')               # 2 < 5
status = app._handle_clipboard_change(quiet=True, dedup=True)
r = app.catchup_clipboard()
check("_handle 返回 'skip'（非 'text'）", status == 'skip', 'got=%r' % status)
check('catchup 返回 False（不误报已补记）', r is False, 'got=%r' % r)
check('未入库', len(app.data['clip']) == 1)
check('静默：补记被过滤时不 tip', TIPS == [], 'tips=%r' % TIPS)
check('静默：不播复制音', PLAY['n'] == 0)

section('C2. quiet=True 仍应用 max_len：超长不补')
base_settings()
app.st['min_len'] = 0
app.st['max_len'] = 3
set_lib([item('已有')])
reset_probes()
clip('text', text='abcdef')           # 6 > 3
r = app.catchup_clipboard()
check('超 max_len → 不补', r is False and len(app.data['clip']) == 1, 'r=%r' % r)

section('C3. quiet=True 仍应用忽略名单（quiet 只静默默认反馈，不跳过规则）')
base_settings()
app.st['ignore_apps'] = 'notepad'
SRC['app'] = 'notepad.exe'
set_lib([item('已有')])
reset_probes()
clip('text', text='来自被忽略应用的文本')
status = app._handle_clipboard_change(quiet=True, dedup=True)
check("命中忽略名单 → 'skip'", status == 'skip', 'got=%r' % status)
check('未入库', len(app.data['clip']) == 1)
check('静默：未 tip', TIPS == [], 'tips=%r' % TIPS)
base_settings()

section('C4. manual=True 既有语义未破坏：大 min_len 仍入库、不播音')
base_settings()
app.st['sound_copy'] = True
app.st['min_len'] = 100
set_lib([item('已有')])
reset_probes()
ok = app.ingest('短内容', manual=True)
check('manual=True 跳过长度过滤 → 入库', ok is True and len(app.data['clip']) == 2,
      'ok=%r n=%d' % (ok, len(app.data['clip'])))
check('manual=True 不播复制音', PLAY['n'] == 0)
check('manual=True 不弹 toast', TOASTS == [])

section('C5. ingest() 返回值区分"被过滤/被忽略"与"成功入库"')
base_settings()
set_lib([item('已有')])
app.st['min_len'] = 5
v_filtered = app.ingest('ab')                       # 被长度过滤
app.st['min_len'] = 1
app.st['ignore_apps'] = 'notepad'
SRC['app'] = 'notepad.exe'
v_ignored = app.ingest('被忽略的内容')               # 被忽略名单拦下
base_settings()
v_ok = app.ingest('正常内容')                        # 成功入库
v_dup = app.ingest('正常内容')                       # 重复→刷新（仍算入库）
check('被长度过滤 → False', v_filtered is False, 'got=%r' % v_filtered)
check('被忽略名单拦下 → False', v_ignored is False, 'got=%r' % v_ignored)
check('成功入库 → True', v_ok is True, 'got=%r' % v_ok)
check('重复刷新也返回 True', v_dup is True, 'got=%r' % v_dup)

section('C6. catchup 返回值与"真的入库"一致（image/text=True，其余 False）')
base_settings()
cases = []
set_lib([item('x')]); clip('text', text='newtext')
cases.append(('text', app.catchup_clipboard()))
set_lib([item('x')]); clip('empty')
cases.append(('empty', app.catchup_clipboard()))
set_lib([item('x')]); clip('text', text='x')
cases.append(('dup', app.catchup_clipboard()))
set_lib([item('x')]); clip('text', text='private', private=True)
cases.append(('private', app.catchup_clipboard()))
app.st['skip_sensitive'] = True
set_lib([item('x')]); clip('text', text='手机 13800138000', private=False)
cases.append(('sensitive', app.catchup_clipboard()))
base_settings()
d = dict(cases)
check('text → True', d['text'] is True)
check('empty → False', d['empty'] is False)
check('dup → False', d['dup'] is False)
check('private → False', d['private'] is False)
check('sensitive → False', d['sensitive'] is False)

# ============================================================
# D. 已知限制独立判定：忽略名单在补记路径是否真的失效
# ============================================================
section('D1. 忽略名单(默认含 keepass/1password…)在补记路径：实证是否漏记')
base_settings()
app.st['ignore_apps'] = 'keepass,1password,bitwarden,lastpass'
# 模拟启动时的真实前台：Windows 启动 ClawBoard 时前台几乎不是密码管理器
SRC['app'] = 'explorer.exe'
SRC['title'] = 'C:\\Users\\me'
set_lib([item('旧的历史内容')])
reset_probes()
clip('text', text='从 KeePass 复制的密码 hunter2', private=False)
r = app.catchup_clipboard()
leaked = [x for x in app.data['clip'] if 'hunter2' in (x.get('text') or '')]
check('忽略名单在补记路径【未能】拦下 → 确实漏记（复现工程师说法）',
      r is True and len(leaked) == 1,
      'r=%r leaked=%d src=%r' % (r, len(leaked), SRC['app']))
check('补记条目记录的来源=补记那一刻的前台窗口(explorer.exe)，非原应用',
      bool(leaked) and leaked[0].get('source_app') == 'explorer.exe',
      'source_app=%r' % (leaked[0].get('source_app') if leaked else None))

section('D2. 对照：同一内容在实时路径（前台=keepass）会被正确拦下')
base_settings()
app.st['ignore_apps'] = 'keepass,1password,bitwarden,lastpass'
SRC['app'] = 'keepass.exe'           # 实时复制时前台正是密码管理器
set_lib([item('x')])
reset_probes()
clip('text', text='从 KeePass 复制的密码 hunter2', private=False)
status = app._handle_clipboard_change()   # 实时：quiet=False, dedup=False
check('实时路径命中忽略名单 → 不入库', status == 'skip' and
      not any('hunter2' in (x.get('text') or '') for x in app.data['clip']),
      'status=%r' % status)

section('D3. 对照：密码管理器官方「别记录我」标记在补记路径【有效】')
base_settings()
app.st['ignore_apps'] = 'keepass,1password,bitwarden,lastpass'
SRC['app'] = 'explorer.exe'          # 前台仍然不是密码管理器
set_lib([item('x')])
reset_probes()
clip('text', text='带官方标记的密码 hunter2', private=True)   # 官方 Exclude 标记
r = app.catchup_clipboard()
check('带官方标记 → 补记路径正确跳过（smart_private 有效）',
      r is False and not any('hunter2' in (x.get('text') or '') for x in app.data['clip']),
      'r=%r' % r)

section('D4. 影响面：单次补记触发最多漏记 1 条（Windows 剪贴板只留最后一条）')
base_settings()
app.st['ignore_apps'] = 'keepass'
SRC['app'] = 'explorer.exe'
set_lib([item('旧')])
clip('text', text='敏感A', private=False)
rA = app.catchup_clipboard()
n1 = len([x for x in app.data['clip'] if x['text'].startswith('敏感')])
check('第 1 次触发：漏记恰好 1 条', rA is True and n1 == 1, 'rA=%r n1=%d' % (rA, n1))
clip('text', text='敏感B', private=False)   # 剪贴板只剩 B
rB = app.catchup_clipboard()
n2 = len([x for x in app.data['clip'] if x['text'].startswith('敏感')])
check('第 2 次触发（内容不同）：再漏记 1 条', rB is True and n2 == 2,
      'rB=%r n2=%d' % (rB, n2))

# ============================================================
# P. 性能修复回归（修复轮 commit f5bff60）：email 正则「廉价预筛 + 超长上界」
#    全部为**行为断言**：直接观测 email 正则是否被调用，不绑定正则字面量
# ============================================================
section('P. 性能修复：email 预筛/上界 行为断言 + 其余正则线性复核')
import time as _t                            # noqa: E402
import clawboard.clipboard as _CL            # noqa: E402
import clawboard.tag as _TG                  # noqa: E402
import clawboard.config as _CFG              # noqa: E402


class _CountPat(object):
    """计数代理：断言 email 正则是否真的被调用（行为断言，与正则写法解耦）。"""
    def __init__(self, pat):
        self._pat = pat
        self.n = 0

    def search(self, s):
        self.n += 1
        return self._pat.search(s)

    def __getattr__(self, k):
        return getattr(self._pat, k)


def _install_email_counters():
    cnt = {}
    new_s, new_t = [], []
    for _n, _p in _CL.SENS_PATTERNS:
        if _n == '邮箱':
            c = _CountPat(_p); cnt['sens'] = c; new_s.append((_n, c))
        else:
            new_s.append((_n, _p))
    for _n, _p in _TG._TAG_PATTERNS:
        if _n == 'email':
            c = _CountPat(_p); cnt['tag'] = c; new_t.append((_n, c))
        else:
            new_t.append((_n, _p))
    _CL.SENS_PATTERNS = new_s
    _TG._TAG_PATTERNS = new_t
    return cnt


CT = _install_email_counters()

# P0. 结构：单一来源 + 仅 email 有预筛/上界
check('email 上界单一来源 config.EMAIL_SCAN_MAXLEN=10000（两处共用）',
      _CL._SENS_MAXLEN.get('邮箱') == _TG._TAG_MAXLEN.get('email') ==
      _CFG.EMAIL_SCAN_MAXLEN == 10000,
      'sens=%r tag=%r cfg=%r' % (_CL._SENS_MAXLEN.get('邮箱'),
                                 _TG._TAG_MAXLEN.get('email'), _CFG.EMAIL_SCAN_MAXLEN))
check('email 预筛字符均为 @（两处）',
      _CL._SENS_PREFILTER.get('邮箱') == _TG._TAG_PREFILTER.get('email') == '@')
check('仅 email 设了预筛/上界（其余项无 cap）',
      set(_CL._SENS_PREFILTER) == {'邮箱'} and set(_CL._SENS_MAXLEN) == {'邮箱'} and
      set(_TG._TAG_PREFILTER) == {'email'} and set(_TG._TAG_MAXLEN) == {'email'})

# P1. 无 '@' 的长文本：email 正则调用 0 次，且毫秒级完成
_big_none = 'x' * 60000
CT['sens'].n = 0; CT['tag'].n = 0
t0 = _t.time(); S.scan_sensitive(_big_none); t_scan = _t.time() - t0
t0 = _t.time(); S.detect_tags(_big_none); t_tag = _t.time() - t0
check('无 @ 长文本：email 正则(敏感) 调用 0 次', CT['sens'].n == 0, 'n=%d' % CT['sens'].n)
check('无 @ 长文本：email 正则(标签) 调用 0 次', CT['tag'].n == 0, 'n=%d' % CT['tag'].n)
check('scan_sensitive(60000 无@) 已修复为毫秒级', t_scan < 0.1, 't=%.3fs' % t_scan)
check('detect_tags(60000 无@) 已修复为毫秒级', t_tag < 0.1, 't=%.3fs' % t_tag)

# P2. 有 '@' 且 ≤10000：email 正则确实被调用（功能保留）
CT['sens'].n = 0; CT['tag'].n = 0
hs = S.scan_sensitive('a@b.com'); ht = S.detect_tags('a@b.com')
check('含 @ 且短：email 正则(敏感) 被调用', CT['sens'].n == 1, 'n=%d' % CT['sens'].n)
check('含 @ 且短：email 正则(标签) 被调用', CT['tag'].n == 1, 'n=%d' % CT['tag'].n)
check('正常邮箱仍被识别为敏感', '邮箱' in hs, 'hits=%r' % hs)
check('正常邮箱仍被识别为标签', 'email' in ht, 'tags=%r' % ht)

# P3. 有 '@' 且 >10000：email 正则被跳过（上界兜底，已声明的取舍）
_long_at = 'a@b.com' + 'x' * 10001
CT['sens'].n = 0; CT['tag'].n = 0
hs = S.scan_sensitive(_long_at); ht = S.detect_tags(_long_at)
check('含 @ 且超上界：email 正则(敏感) 被跳过', CT['sens'].n == 0, 'n=%d' % CT['sens'].n)
check('含 @ 且超上界：email 正则(标签) 被跳过', CT['tag'].n == 0, 'n=%d' % CT['tag'].n)
check('（已声明取舍）超长文本里的邮箱不再被识别',
      '邮箱' not in hs and 'email' not in ht, 'hs=%r ht=%r' % (hs, ht))

# P4. ⚠️ 上界只作用于 email：其余敏感项对超长文本仍必须检出（安全相关）
_pad = 'x' * 20000
for _name, _sample in (('手机号', ' 13800138000 '), ('身份证', ' 110101199003070013 '),
                       ('银行卡', ' 6222021234567890 '), ('Token', ' sk-abcdefghijklmnop1234 '),
                       ('密码', ' password: hunter2xyz ')):
    _hits = S.scan_sensitive(_pad + _sample)
    check('超长文本仍检出 %s' % _name, _name in _hits, 'hits=%r' % _hits)
check('超长文本 detect_tags 仍打 phone 标签',
      'phone' in S.detect_tags(_pad + ' 13800138000 '))
check('超长文本 detect_tags 仍打 token 标签',
      'token' in S.detect_tags(_pad + ' sk-abcdefghijklmnop1234 '))

# P5. 边界：长度恰 10000 含 @ → 调用；10001 含 @ → 跳过、不崩溃
_t10 = 'a@b.com' + 'x' * (10000 - 7)
_t11 = 'a@b.com' + 'x' * (10001 - 7)
check('构造边界长度正确', len(_t10) == 10000 and len(_t11) == 10001,
      'l10=%d l11=%d' % (len(_t10), len(_t11)))
CT['sens'].n = 0
h10 = S.scan_sensitive(_t10)
check('len=10000 含@ → 正则被调用且检出', CT['sens'].n == 1 and '邮箱' in h10,
      'n=%d hits=%r' % (CT['sens'].n, h10))
CT['sens'].n = 0
h11 = S.scan_sensitive(_t11)
check('len=10001 含@ → 正则跳过、不崩溃', CT['sens'].n == 0 and '邮箱' not in h11,
      'n=%d' % CT['sens'].n)

# P6. 独立复核：其余（非 email）正则在 n=60000 最坏输入上均为线性
for _name, _inp in (('身份证', '1' * 60000), ('银行卡', '1' * 60000),
                    ('手机号', '1' * 60000), ('Token', 'sk' * 30000),
                    ('密码', 'passwordxyz' * 5000)):
    _raw = dict(_CL.SENS_PATTERNS)[_name]      # 非 email → 原始编译对象
    t0 = _t.time(); _raw.search(_inp); _dt = _t.time() - t0
    check('敏感正则 %s 线性(<0.05s@60000)' % _name, _dt < 0.05, 't=%.4fs' % _dt)
for _name, _inp in (('url', 'http' * 15000), ('date', '2020' * 15000)):
    _raw = dict(_TG._TAG_PATTERNS)[_name]
    t0 = _t.time(); _raw.search(_inp); _dt = _t.time() - t0
    check('标签正则 %s 线性(<0.05s@60000)' % _name, _dt < 0.05, 't=%.4fs' % _dt)
t0 = _t.time(); S.detect_tags('1' * 60000); _dt = _t.time() - t0   # number fullmatch
check('detect_tags(纯数字 60000) 线性', _dt < 0.1, 't=%.4fs' % _dt)

# P7. 两条路径（实时 poll / 补记 catchup）在无 @ 长文本上端到端均显著下降
base_settings()
set_lib([])
reset_probes()
clip('text', text='y' * 60000)              # 实时
t0 = _t.time(); r_rt = app._handle_clipboard_change(); t_rt = _t.time() - t0
check('实时路径 60K 无@ 端到端毫秒级', r_rt == 'text' and t_rt < 0.5,
      'r=%r t=%.3fs' % (r_rt, t_rt))
set_lib([item('旧')])
reset_probes()
clip('text', text='z' * 200000)             # 补记（启动路径）
t0 = _t.time(); r_cu = app.catchup_clipboard(); t_cu = _t.time() - t0
check('补记路径 200K 无@ 端到端毫秒级', r_cu is True and t_cu < 1.0,
      'r=%r t=%.3fs' % (r_cu, t_cu))

# P8. 正常长度文本的敏感处置仍生效（skip_sensitive / mask_sensitive）
base_settings()
hits = S.scan_sensitive('联系人 a@b.com 请回信')
check('正常长度含邮箱 → 判定为敏感', '邮箱' in hits, 'hits=%r' % hits)
_masked = _CL.mask_text('联系人 a@b.com 请回信', hits)
check('mask_sensitive 仍能打码邮箱', 'a@b.com' not in _masked, 'masked=%r' % _masked)
app.st['skip_sensitive'] = True
set_lib([item('x')])
reset_probes()
clip('text', text='联系人 a@b.com 请回信')
st = app._handle_clipboard_change()          # 实时：命中敏感 → 不入库
check('正常长度含邮箱 + skip_sensitive → 仍不入库', st == 'sensitive' and
      len(app.data['clip']) == 1, 'st=%r' % st)

# ============================================================
# E. 数据不污染 + 回归
# ============================================================
section('E. 数据不污染')
check('真实数据 sha256 未变', HASH_BEFORE == file_hash(REAL_DATA) == EXPECT_HASH,
      'before=%s after=%s' % (HASH_BEFORE, file_hash(REAL_DATA)))
check('真实目录无新增 .bak / 无新文件', sidecars() == FILES_BEFORE,
      'before=%s after=%s' % (FILES_BEFORE, sidecars()))
check('临时数据文件未被写入（NO_SAVE 生效）', not os.path.exists(TMP_DATA))

# 收尾
try:
    S.sound.play_copy = _orig_play
except Exception:
    pass
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

try:
    _LOGF.write('\n' + ('全部通过\n' if OK else '有失败项\n'))
    _LOGF.flush()
    _LOGF.close()
except Exception:
    pass
print('全部通过' if OK else '有失败项')
sys.stdout.flush()
