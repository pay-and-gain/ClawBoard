# -*- coding: utf-8 -*-
"""QA 独立验证：ClawBoard P1-1 首次启动引导（OnboardCard）。

与工程师自测 tests/_t38.py 的差别（本脚本刻意换角度、覆盖边界与错误路径）：
  A. 数据不污染：用「沙箱实验」直接证明 backup_data() 读的是 timefmt.DATA_FILE；
     再在「受控 + 可还原」的前提下只重定向 app_services.DATA_FILE，观察真实工作区
     是否真的会被写出 .bak（验证工程师「必须双重重定向」的说法是否成立）。
     另用 save/save_now 探针证明「只显示引导卡片、不点按钮」不触发任何写盘。
  B. 显示闸门 should_show / is_empty_data 的缺键 / 空列表 / None 等边界（不抛异常）。
  C. 示例数据合法性：精确校验 created_at 递减值、非估算、validate 不减条、渲染可消费。
  D. 真实 GUI 闭环：空→卡片显示；load_samples→隐藏；逐条删除→删光后卡片“重新出现”。
  E. 最小窗口尺寸下卡片不被裁切（含 ui_scale 0.5/1.0/1.5 三档）。
  F. 回归：test_core / test_refactor / _t35 / _t36 / _t37 / _t38。

安全约束：
  - 绝不修改产品源码（clawboard/*.py）。
  - 临时数据放 %TEMP%；真实数据侧车文件在做就地实验前全量快照、实验后原样还原。
  - 不使用 os._exit(0)（会丢 stdout）：需要时 flush 后 sys.exit。
"""
import glob
import hashlib
import json
import os
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

REAL_DATA = os.path.join(ROOT, 'ClawBoard数据.json')
TMP = tempfile.mkdtemp(prefix='cb_qa5_')
PY = sys.executable

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
    LOG.append('==== %s ====' % t)


def sha(path):
    try:
        with open(path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return None


def sidecars(prefix=REAL_DATA):
    return sorted(glob.glob(prefix + '*'))


# ---- 重定向落盘目标（必须在 import 业务模块之前）----
import clawboard.app_services as S          # noqa: E402
import clawboard.timefmt as TF              # noqa: E402
from clawboard import runtime               # noqa: E402
from clawboard import onboard               # noqa: E402
from clawboard.app_services import DataMixin  # noqa: E402

runtime.NO_SAVE = True
S.CRASH_LOG = os.path.join(TMP, 'crash.log')


class _SilentData(DataMixin):
    """只用来跑 load_data 的最小宿主（note 静默、无 GUI）。"""

    def note(self, msg):
        pass


# =========================================================================
section('A. 数据不污染（最高优先级）')
# =========================================================================
REAL_HASH_BEFORE = sha(REAL_DATA)
REAL_FILES_BEFORE = sidecars()
check('基线：真实数据文件存在', os.path.exists(REAL_DATA))
check('基线：真实数据 hash 记录', REAL_HASH_BEFORE is not None, REAL_HASH_BEFORE)
check('基线：真实侧车文件清单', True, str([os.path.basename(p) for p in REAL_FILES_BEFORE]))

# ---- A1. 沙箱实验：证明 backup_data() 的落盘目标是 timefmt.DATA_FILE ----
# 造两个「低版本」数据文件，只重定向 app_services.DATA_FILE，把 timefmt.DATA_FILE
# 指到另一个文件；若 backup_data 走 timefmt，则备份会落在 timefmt 指向的那个文件旁。
real2 = os.path.join(TMP, 'real2.json')
low2 = os.path.join(TMP, 'low2.json')
for p in (real2, low2):
    with open(p, 'w', encoding='utf-8') as f:
        json.dump({'clip': [{'text': 'seed'}], 'schema_version': 1}, f, ensure_ascii=False)

S.DATA_FILE = low2          # app_services 命名空间 → low2
TF.DATA_FILE = real2        # timefmt 命名空间   → real2（模拟“两个不是同一个文件”）
try:
    _SilentData().load_data()
except Exception as e:
    check('沙箱实验 load_data 不抛异常', False, repr(e))
check('沙箱实验：备份落在 timefmt 指向的文件旁', os.path.exists(real2 + '.bak'),
      'real2.bak=%s' % os.path.exists(real2 + '.bak'))
check('沙箱实验：app_services 指向的文件未被备份', not os.path.exists(low2 + '.bak'),
      'low2.bak=%s' % os.path.exists(low2 + '.bak'))
check('沙箱实验：real2.bak 内容 == real2（说明来源是 timefmt 的 DATA_FILE）',
      sha(real2 + '.bak') == sha(real2))

# ---- A2. 就地实验（受控 + 可还原）：只重定向 app_services.DATA_FILE 是否污染工作区 ----
snap = {p: open(p, 'rb').read() for p in REAL_FILES_BEFORE}
low3 = os.path.join(TMP, 'low3.json')
with open(low3, 'w', encoding='utf-8') as f:
    json.dump({'clip': [{'text': 'pollute-probe'}], 'schema_version': 1},
              f, ensure_ascii=False)
S.DATA_FILE = low3          # 只重定向 app_services
TF.DATA_FILE = REAL_DATA    # timefmt 保持指向真实文件（模拟“只重定向一个”）
polluted = False
pollution_desc = ''
try:
    _SilentData().load_data()
    after = sidecars()
    new_files = [p for p in after if p not in REAL_FILES_BEFORE]
    if new_files:
        polluted = True
        pollution_desc = str([os.path.basename(p) for p in new_files])
finally:
    # 还原真实侧车文件：先删全部，再按快照写回
    for p in sidecars():
        try:
            os.remove(p)
        except Exception:
            pass
    for p, b in snap.items():
        with open(p, 'wb') as f:
            f.write(b)

check('就地实验：只重定向 app_services 会污染工作区（证明双重重定向是必要的）',
      polluted, '新增侧车文件=%s' % (pollution_desc or '无'))
check('就地实验后已还原：侧车清单与基线一致',
      sidecars() == REAL_FILES_BEFORE,
      'after=%s' % [os.path.basename(p) for p in sidecars()])
check('就地实验后已还原：真实数据 hash 与基线一致',
      sha(REAL_DATA) == REAL_HASH_BEFORE)

# 后续流程统一把两个命名空间都指向临时文件
GUI_DATA = os.path.join(TMP, 'gui.json')
S.DATA_FILE = GUI_DATA
TF.DATA_FILE = GUI_DATA

# =========================================================================
section('B. 显示闸门逻辑与边界')
# =========================================================================
empty = {'clip': [], 'groups': [{'name': '默认', 'items': []}]}
nonempty = {'clip': [{'text': 'x'}], 'groups': [{'name': '默认', 'items': []}]}

check('空 + clip + 无搜索 → 显示', onboard.should_show('clip', '', empty) is True)
check('空 + clip + 空白搜索词 → 显示',
      onboard.should_show('clip', '   ', empty) is True)
check('空 + clip + query=None → 显示（不抛异常）',
      onboard.should_show('clip', None, empty) is True)
check('空 + 有搜索词 → 不显示', onboard.should_show('clip', 'hello', empty) is False)
check('空 + 常用语 Tab → 不显示', onboard.should_show('phrase', '', empty) is False)
check('非空数据 → 不显示', onboard.should_show('clip', '', nonempty) is False)

edge_cases = {
    'data 缺 clip 键': {'groups': [{'name': '默认', 'items': []}]},
    'data 缺 groups 键': {'clip': []},
    'groups 为空列表': {'clip': [], 'groups': []},
    'groups[].items 为 None': {'clip': [], 'groups': [{'name': '默认', 'items': None}]},
    'data 为 None': None,
    'data 为 list（非 dict）': [],
    'clip 键存在但为 None': {'clip': None, 'groups': []},
}
for label, d in edge_cases.items():
    try:
        v_empty = onboard.is_empty_data(d)
        v_show = onboard.should_show('clip', '', d)
        check('边界「%s」不抛异常且判定合理' % label,
              v_empty is True and v_show is True,
              'is_empty=%s should_show=%s' % (v_empty, v_show))
    except Exception as e:
        check('边界「%s」不抛异常且判定合理' % label, False, repr(e))

# groups 非 list（如 dict / str）也要安全
for label, d in {'groups 为 dict': {'clip': [], 'groups': {'a': 1}}}.items():
    try:
        check('边界「%s」不抛异常' % label, onboard.is_empty_data(d) is True)
    except Exception as e:
        check('边界「%s」不抛异常' % label, False, repr(e))

# 仅有常用语 → 非空
check('仅有常用语 → 非空',
      onboard.is_empty_data({'clip': [],
                             'groups': [{'name': '默认', 'items': [{'text': 'y'}]}]}) is False)

# =========================================================================
section('C. 示例数据合法性')
# =========================================================================
BASE_TS = 1700000000123
samples = onboard.sample_items(base_ts=BASE_TS)
n = len(samples)
check('示例条数为 6', n == 6, '实际 %d' % n)
check('示例 id 唯一', len({it['id'] for it in samples}) == n)
check('示例 id 均为非空 str',
      all(isinstance(it.get('id'), str) and it['id'] for it in samples))
check('示例 text 均非空 str',
      all(isinstance(it.get('text'), str) and it['text'].strip() for it in samples))

# created_at 应为显式值：base - (n-i)*60000，逐条精确
expected_ts = [BASE_TS - (n - i) * 60000 for i in range(n)]
check('示例 created_at 为显式递减时间戳（精确匹配）',
      [it['created_at'] for it in samples] == expected_ts,
      'got=%s' % [it['created_at'] for it in samples])
check('示例 is_estimated 显式为 0',
      all(it.get('is_estimated') == 0 for it in samples))
check('示例每条的 kind_auto / content_type 均已预置',
      all(it.get('kind_auto') and it.get('content_type') for it in samples))

normed = [DataMixin.norm_item(dict(it), i + 1) for i, it in enumerate(samples)]
check('全部通过 norm_item（不为 None）', all(x is not None for x in normed))
need = ('id', 'text', 'created_at', 'updated_at', 'last_used_at', 'source_app',
        'copy_count', 'fav', 'content_type', 'content_size', 'seq', 'is_estimated')
check('norm_item 后字段齐全', all(all(k in x for k in need) for x in normed),
      str([sorted(set(need) - set(x)) for x in normed if not all(k in x for k in need)]))
check('norm_item 后仍为真实时间戳（未被标估算）',
      all(int(x['created_at']) == int(it['created_at']) and x['is_estimated'] == 0
          for x, it in zip(normed, samples)))

vdata = DataMixin.validate({'clip': [dict(it) for it in samples],
                            'groups': [{'name': '默认', 'items': []}], 'gi': 0,
                            'settings': {}, 'schema_version': 3})
check('validate 后剪贴板条数不减少', len(vdata['clip']) == n,
      '实际 %d' % len(vdata['clip']))
check('validate 后 kind_auto/content_type 正常',
      all(x.get('kind_auto') and x.get('content_type') for x in vdata['clip']))

# =========================================================================
section('D. 真实 GUI 闭环 + E. 最小尺寸布局')
# =========================================================================
from clawboard.win32 import init_dpi_awareness  # noqa: E402
init_dpi_awareness()

import tkinter as tk          # noqa: E402
import ClawBoard as C         # noqa: E402
C.NO_SAVE = True

root = tk.Tk()
app = C.ClawBoard(root)
if app.collapsed:                       # 折叠态污染：body 被 pack_forget，量出来全是 1px
    app.collapsed = False
    app.st['collapsed'] = False
    app.body.pack(fill='both', expand=True)
    app.root.minsize(*app.min_size())
root.update()
app.render()
root.update()

check('D1 空数据：列表为空', app.vlist.items == [])
check('D2 空数据：引导卡片已显示', bool(app.onboard.winfo_ismapped()),
      'ismapped=%s' % app.onboard.winfo_ismapped())

# --- A3. 卡片本身不写盘（不点按钮）---
save_calls = []
save_now_calls = []
_orig_save = app.save
_orig_save_now = app.save_now
app.save = lambda *a, **k: save_calls.append((a, k))
app.save_now = lambda *a, **k: save_now_calls.append((a, k))

app.set_tab('phrase')
app.set_tab('clip')
app.search.set('probe')
app.render()
app.search.set('')
app.render()
root.update()
check('A3 只显示引导卡片 / 切 Tab / 开关搜索 → 不触发 save',
      len(save_calls) == 0, 'save 调用 %d 次' % len(save_calls))
check('A3 只显示引导卡片 / 切 Tab / 开关搜索 → 不触发 save_now',
      len(save_now_calls) == 0, 'save_now 调用 %d 次' % len(save_now_calls))
app.save = _orig_save
app.save_now = _orig_save_now

# --- D3. load_samples 闭环 ---
app.load_samples()
root.update()
check('D3 载入示例：剪贴板 6 条', len(app.data['clip']) == 6,
      '实际 %d' % len(app.data['clip']))
check('D4 载入示例：列表可见 6 条', len(app.vlist.items) == 6,
      '实际 %d' % len(app.vlist.items))
check('D5 载入示例：卡片自动隐藏', not app.onboard.winfo_ismapped(),
      'ismapped=%s' % app.onboard.winfo_ismapped())
check('D6 载入示例：_seq 跟上最大 seq',
      app._seq >= max(int(x.get('seq') or 0) for x in app.data['clip']))

# --- C2. 渲染层能消费示例（真实 visible_items 路径）---
items, sel, kw = app.visible_items()
check('C2 visible_items 消费示例不抛异常且 6 条',
      len(items) == 6, '实际 %d' % len(items))
check('C2 渲染结果无 None 关键字段',
      all(x.get('disp') and x.get('sub') is not None and x.get('badge') is not None
          and x.get('id') for x in items))

# --- D7. 逐条删光 → 卡片应重新出现（工程师未覆盖的语义）---
ids = [x['id'] for x in list(app.data['clip'])]
for cid in ids:
    app.del_item(cid, 'clip')
root.update()
check('D7 删光示例后 clip 为空', app.data['clip'] == [],
      '实际 %d' % len(app.data['clip']))
check('D7 删光后引导卡片重新出现（数据又空了）',
      bool(app.onboard.winfo_ismapped()),
      'ismapped=%s' % app.onboard.winfo_ismapped())

# --- D8. 常用语 Tab 空状态文案 ---
app.tab = 'phrase'
app.render()
root.update()
check('D8 常用语 Tab 空状态文案正确',
      app.vlist.empty_msg == '还没有常用语，点 ＋ 新建',
      'empty_msg=%r' % (app.vlist.empty_msg,))
check('D8 常用语 Tab 不显示引导卡片', not app.onboard.winfo_ismapped())
app.tab = 'clip'
app.render()
root.update()

# =========================================================================
section('E. 最小窗口尺寸布局不裁切（严格量法，5 档 × 各自 min_size）')
# =========================================================================


def set_min_window(lvl):
    """切到 lvl 档并强制窗口 = 该档 min_size()，排除折叠态污染。"""
    app.set_ui_scale(lvl)
    if app.collapsed:
        app.collapsed = False
        app.st['collapsed'] = False
        app.body.pack(fill='both', expand=True)
    mw, mh = app.min_size()
    app.root.minsize(1, 1)
    app.root.geometry('%dx%d+60+60' % (mw, mh))
    app.root.minsize(mw, mh)
    root.update()
    app.render()
    for _ in range(5):
        root.update()
    return mw, mh


def card_metrics():
    """严格量法：
    available = wrap 的**实际分配高度**（已扣除卡片内边距，= 真正能装内容的高度）；
    needed    = wrap 的**自然需求高度**；
    另测主按钮 ismapped 与其相对卡片的底边像素。"""
    ob = app.onboard
    root.update_idletasks()
    for _ in range(4):
        root.update()
    wrap = ob._wrap
    btn = ob._btn
    btn_top = btn.winfo_rooty() - ob.winfo_rooty()
    return dict(available=wrap.winfo_height(), needed=wrap.winfo_reqheight(),
                btn_mapped=bool(btn.winfo_ismapped()), btn_top=btn_top,
                btn_bottom=btn_top + btn.winfo_height(), card_h=ob.winfo_height(),
                wrap_w=wrap.winfo_width())


# 对照（修复前）：0.75 溢出 +20；0.5 溢出 +35，按钮被压成 1px 不可见
for lvl in (1.0, 1.25, 1.5, 0.75, 0.5):
    try:
        mw, mh = set_min_window(lvl)
    except Exception as e:
        check('E ui_scale=%.2f 切换不抛异常' % lvl, False, repr(e))
        continue
    ob = app.onboard
    check('E ui_scale=%.2f 空数据卡片显示' % lvl, bool(ob.winfo_ismapped()),
          'ismapped=%s min=%dx%d' % (ob.winfo_ismapped(), mw, mh))
    m = card_metrics()
    check('E ui_scale=%.2f needed<=available（严格，含内边距/gbar）' % lvl,
          m['needed'] <= m['available'],
          'needed=%s available=%s overflow=%+d min=%dx%d wrap_w=%d'
          % (m['needed'], m['available'], m['needed'] - m['available'], mw, mh, m['wrap_w']))
    check('E ui_scale=%.2f 主按钮 ismapped=1' % lvl, m['btn_mapped'],
          'btn_mapped=%s' % m['btn_mapped'])
    check('E ui_scale=%.2f 主按钮底边像素<=卡片可视底边' % lvl,
          m['btn_mapped'] and 0 <= m['btn_top'] and m['btn_bottom'] <= m['card_h'],
          'btn_top=%s btn_bottom=%s card_h=%s' % (m['btn_top'], m['btn_bottom'], m['card_h']))
    rows = ob.visible_rows()
    check('E ui_scale=%.2f title/steps/btn 永不收起' % lvl,
          all(r in rows for r in ('title', 'steps', 'btn')), 'rows=%s' % rows)
    check('E ui_scale=%.2f 仅允许隐藏 hint/link/lead' % lvl,
          set(ob._hidden) <= {'hint', 'link', 'lead'}, 'hidden=%s' % list(ob._hidden))

# =========================================================================
section('G. 自适应降级不误伤 / 行序不乱 / 主题切换 / Tab 往返')
# =========================================================================
ALL_ROWS = ['title', 'lead', 'steps', 'hint', 'link', 'btn']


def pack_order():
    return [getattr(c, '_onboard_name', None) for c in app.onboard._wrap.pack_slaves()]


# G1 正常/较大窗口：应显示全部行（不误收）
app.set_ui_scale(1.0)
if app.collapsed:
    app.collapsed = False
    app.st['collapsed'] = False
    app.body.pack(fill='both', expand=True)
app.root.minsize(1, 1)
app.root.geometry('520x660+60+60')
app.root.minsize(*app.min_size())
root.update()
app.render()
for _ in range(5):
    root.update()
check('G1 正常尺寸下 visible_rows=全部 6 行',
      app.onboard.visible_rows() == ALL_ROWS,
      'rows=%s' % app.onboard.visible_rows())
check('G1 正常尺寸下 pack 顺序正确', pack_order() == ALL_ROWS,
      'order=%s' % pack_order())

# G2 极端小空间：只收 hint/link/lead，核心行保留
mw, mh = set_min_window(0.5)
rows_small = app.onboard.visible_rows()
check('G2 极小空间含 title/steps/btn',
      all(r in rows_small for r in ('title', 'steps', 'btn')), 'rows=%s' % rows_small)
check('G2 极小空间隐藏项 ⊆ {hint,link,lead}',
      set(app.onboard._hidden) <= {'hint', 'link', 'lead'},
      'hidden=%s' % list(app.onboard._hidden))

# G2b 真实 Configure 驱动的降级顺序（强制压小卡片高度，逐档观察）：
# 因为各档 min_size 下内容已能装下，自适应并不触发，必须主动压小才验证得到机制。
app.set_ui_scale(1.0)
app.root.minsize(1, 1)
app.root.geometry('520x660+60+60')
app.root.minsize(*app.min_size())
root.update()
app.render()
for _ in range(4):
    root.update()
HIDE_ORDER = ('hint', 'link', 'lead')
sweep = []
for H in (400, 280, 240, 210, 180, 60):
    app.onboard.place_configure(relheight=0, height=H)
    root.update()
    for _ in range(2):
        root.update()
    sweep.append((H, tuple(app.onboard._hidden), tuple(app.onboard.visible_rows())))
# 恢复铺满
app.onboard.place(in_=app.vlist, relx=0, rely=0, relwidth=1, relheight=1)
root.update()
for _ in range(3):
    root.update()

check('G2b 压小卡片后确实触发隐藏（机制生效）',
      any(len(h) > 0 for _, h, _ in sweep),
      'sweep=%s' % [(H, list(h)) for H, h, _ in sweep])
check('G2b 隐藏项始终是 hint→link→lead 的前缀（顺序正确）',
      all(list(h) == [x for x in HIDE_ORDER if x in set(h)] for _, h, _ in sweep),
      'sweep=%s' % [(H, list(h)) for H, h, _ in sweep])
check('G2b title/steps/btn 在任何空间下都在',
      all({'title', 'steps', 'btn'} <= set(vis) for _, _, vis in sweep),
      'sweep=%s' % [(H, list(vis)) for H, _, vis in sweep])
hidden_sizes = [len(h) for _, h, _ in sweep]
check('G2b 空间越小隐藏越多（单调不减）',
      all(hidden_sizes[i] <= hidden_sizes[i + 1] for i in range(len(hidden_sizes) - 1)),
      'sizes=%s' % hidden_sizes)
check('G2b 恢复铺满后全部行回来且行序正确',
      app.onboard.visible_rows() == ALL_ROWS and pack_order() == ALL_ROWS,
      'rows=%s order=%s' % (app.onboard.visible_rows(), pack_order()))

# G3 空间恢复：行重新显示，且顺序与初始一致（pack_forget→pack 老坑）
app.set_ui_scale(1.5)
app.root.minsize(1, 1)
app.root.geometry('560x700+60+60')
app.root.minsize(*app.min_size())
root.update()
app.render()
for _ in range(5):
    root.update()
check('G3 空间恢复后 visible_rows 恢复全部行',
      app.onboard.visible_rows() == ALL_ROWS, 'rows=%s' % app.onboard.visible_rows())
check('G3 恢复后 pack 行序与初始一致（不乱）',
      pack_order() == ALL_ROWS, 'order=%s' % pack_order())

# G3b 反复「小→大→小→大」后顺序仍稳定
set_min_window(0.5)
set_min_window(1.5)
check('G3b 反复缩放任后行序稳定', pack_order() == ALL_ROWS, 'order=%s' % pack_order())

# G4 主题切换（rebuild UI）后卡片仍正常
app.st['theme'] = 'light'
try:
    app.rebuild()
    root.update()
    app.render()
    for _ in range(5):
        root.update()
    check('G4 换浅色主题后卡片仍显示', bool(app.onboard.winfo_ismapped()),
          'ismapped=%s' % app.onboard.winfo_ismapped())
    check('G4 换浅色主题后行序正确', pack_order() == ALL_ROWS, 'order=%s' % pack_order())
except Exception as e:
    check('G4 换浅色主题后卡片仍正常', False, repr(e))
app.st['theme'] = 'dark'
try:
    app.rebuild()
    root.update()
    app.render()
    for _ in range(4):
        root.update()
except Exception:
    pass
check('G4 切回深色主题后卡片仍显示', bool(app.onboard.winfo_ismapped()))

# G5 Tab 往返
app.tab = 'phrase'
app.render()
root.update()
check('G5 常用语 Tab 卡片隐藏', not app.onboard.winfo_ismapped())
app.tab = 'clip'
app.render()
root.update()
check('G5 切回剪贴板 Tab 卡片显示', bool(app.onboard.winfo_ismapped()))

# G6 「载入示例 → 隐藏 → 删光 → 重现」闭环（确认修复未破坏）
app.load_samples()
root.update()
check('G6 载入示例后卡片隐藏', not app.onboard.winfo_ismapped(),
      'ismapped=%s' % app.onboard.winfo_ismapped())
for cid in [x['id'] for x in list(app.data['clip'])]:
    app.del_item(cid, 'clip')
root.update()
check('G6 删光后卡片重新出现', bool(app.onboard.winfo_ismapped()),
      'ismapped=%s' % app.onboard.winfo_ismapped())

# 还原默认缩放
try:
    app.set_ui_scale(1.0)
except Exception:
    pass

# 清理 GUI 实例
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

# =========================================================================
section('F. 回归测试')
# =========================================================================
REG = ['tests/test_core.py', 'tests/test_refactor.py', 'tests/_t35.py',
       'tests/_t36.py', 'tests/_t37.py', 'tests/_t38.py']


def run_reg(rel):
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        return None, '', 'missing'
    try:
        r = subprocess.run([PY, p], cwd=ROOT, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=180)
        return r.returncode, (r.stdout or '') + (r.stderr or ''), ''
    except Exception as e:
        return None, '', repr(e)


for rel in REG:
    rc, out, err = run_reg(rel)
    if rc is None:
        check('F 回归 %s' % rel, False, err)
        continue
    low = out
    bad = ('FAIL' in low) or ('Traceback' in low) or ('有失败项' in low)
    check('F 回归 %s（rc=%s）' % (rel, rc), rc == 0 and not bad,
          '' if not bad else (low.strip().splitlines()[-1] if low.strip() else ''))
    if rel.endswith('_t38.py'):
        n_ok = sum(1 for ln in low.splitlines() if ln.startswith('OK'))
        # 注：_t38 有 33 个 check 调用点，其中 2 个在 UI_SCALE_LEVELS(5 档) 循环里 → 实际 41 项
        check('F _t38 用例数 >= 40', n_ok >= 40, '实际 OK 行数=%d' % n_ok)

# =========================================================================
# 收尾：确认工作区未被污染
# =========================================================================
section('总收尾：工作区无污染')
check('真实数据 hash 仍与基线一致', sha(REAL_DATA) == REAL_HASH_BEFORE,
      'before=%s after=%s' % (REAL_HASH_BEFORE, sha(REAL_DATA)))
check('真实侧车文件清单仍与基线一致', sidecars() == REAL_FILES_BEFORE,
      'after=%s' % [os.path.basename(p) for p in sidecars()])
check('临时 GUI 数据文件未被写入（NO_SAVE 生效）', not os.path.exists(GUI_DATA))

# 输出写进 %TEMP%（不污染仓库：tests/ 下 _qa*.out 是已入库产物，不能再新增）
out_path = os.path.join(TMP, '_qa5_onboard.out')
with open(out_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(LOG) + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))
print('（完整日志已写入 %s）' % out_path, flush=True)
print('\n'.join(LOG), flush=True)
print('\n全部通过' if OK else '\n有失败项', flush=True)

sys.stdout.flush()
sys.exit(0 if OK else 1)
