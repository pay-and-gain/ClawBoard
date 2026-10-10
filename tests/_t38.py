# -*- coding: utf-8 -*-
"""P1-1 首次启动引导回归自测。

覆盖：
1. 空数据判定 is_empty_data：全空 → True；有剪贴板记录 / 仅有常用语 → False。
2. 显示闸门 should_show：仅「剪贴板 Tab + 无搜索词 + 整库为空」才显示。
3. 示例数据字段合法：能通过 norm_item / validate，且 id 唯一、文本非空、条数 5~6。
4. GUI 闭环：「载入示例」后列表可见、条目数正确、引导卡片自动隐藏；
   常用语 Tab 空状态用的是针对性文案。
5. 多缩放档（0.5~1.5）× 最小窗口下卡片不裁切、主按钮完整可见可点击；
   空间极端不足时按优先级收起次要行、保留三步与主按钮。
6. 数据文件未被污染：真实 ClawBoard数据.json 的 sha256 前后一致、无新增 .bak。

不污染真实数据的做法：import 业务模块之前，把 app_services.DATA_FILE 与 timefmt.DATA_FILE
都重定向到临时目录，并置 runtime.NO_SAVE=True（本脚本另设 C.NO_SAVE=True 双保险）。
因此即使代码里调用了 save()，真实存档也一个字节都不会变。
"""
import ctypes
import hashlib
import os
import sys
import tempfile

# DPI 感知必须在建 Tk 前打开，否则量出来的最小尺寸/像素全不对
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ---- 重定向落盘目标（必须在 import 业务模块之前）----
TMP_DIR = tempfile.mkdtemp(prefix='cb_t38_')
TMP_DATA = os.path.join(TMP_DIR, 'ClawBoard数据.json')

import clawboard.app_services as S          # noqa: E402
S.DATA_FILE = TMP_DATA                      # 关键：把落盘重定向到临时文件
S.CRASH_LOG = os.path.join(TMP_DIR, 'crash.log')

# backup_data() 用的是 timefmt 自己命名空间里的 DATA_FILE（from config import 的副本），
# 不重定向它的话，load_data 的迁移分支会把真实存档复制成 .bak.1/.bak.2，污染工作区。
import clawboard.timefmt as TF              # noqa: E402
TF.DATA_FILE = TMP_DATA

from clawboard import runtime               # noqa: E402
runtime.NO_SAVE = True                      # 绝不写盘

from clawboard import onboard               # noqa: E402
from clawboard.app_services import DataMixin  # noqa: E402

OK = True
LOG = []


def check(name, cond, extra=''):
    global OK
    if not cond:
        OK = False
    LOG.append('%s  %s%s' % ('OK  ' if cond else 'FAIL', name,
                             ('  ' + extra) if extra else ''))


# 真实数据文件的指纹（最后要核对未变）
REAL_DATA = os.path.join(ROOT, 'ClawBoard数据.json')


def file_hash(p):
    try:
        with open(p, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return None


HASH_BEFORE = file_hash(REAL_DATA)


def data_sidecar_files():
    """真实数据文件及其 .bak 副本的清单（迁移逻辑若误伤真实存档，这里会多出文件）。"""
    import glob
    return sorted(os.path.basename(p) for p in glob.glob(REAL_DATA + '*'))


FILES_BEFORE = data_sidecar_files()

# ---------- 1. 空数据判定 ----------
empty = {'clip': [], 'groups': [{'name': '默认', 'items': []}]}
check('全空 → 空数据', onboard.is_empty_data(empty) is True)
check('缺字段也算空', onboard.is_empty_data({}) is True)
check('None 也算空', onboard.is_empty_data(None) is True)
check('有剪贴板记录 → 非空',
      onboard.is_empty_data({'clip': [{'text': 'x'}],
                             'groups': [{'name': '默认', 'items': []}]}) is False)
check('仅有常用语 → 非空',
      onboard.is_empty_data({'clip': [],
                             'groups': [{'name': '默认', 'items': [{'text': 'y'}]}]}) is False)
check('有剪贴板且有常用语 → 非空',
      onboard.is_empty_data({'clip': [{'text': 'x'}],
                             'groups': [{'name': '默认', 'items': [{'text': 'y'}]}]}) is False)

# ---------- 2. 显示闸门 should_show ----------
check('空数据 + 剪贴板 Tab + 无搜索 → 显示',
      onboard.should_show('clip', '', empty) is True)
check('空数据 + 有搜索词 → 不显示',
      onboard.should_show('clip', 'hello', empty) is False)
check('空数据 + 常用语 Tab → 不显示',
      onboard.should_show('phrase', '', empty) is False)
check('非空数据 → 不显示',
      onboard.should_show('clip', '',
                          {'clip': [{'text': 'x'}], 'groups': []}) is False)

# ---------- 3. 示例数据字段合法 ----------
samples = onboard.sample_items(base_ts=1700000000000)
check('示例条数在 5~6 之间', 5 <= len(samples) <= 6, '实际 %d' % len(samples))
check('示例 id 唯一', len({it['id'] for it in samples}) == len(samples))
check('示例文本均非空且为 str',
      all(isinstance(it.get('text'), str) and it['text'].strip() for it in samples))

normed = [DataMixin.norm_item(dict(it), i + 1) for i, it in enumerate(samples)]
check('示例全部通过 norm_item（不为 None）', all(x is not None for x in normed))
need = ('id', 'text', 'created_at', 'updated_at', 'last_used_at', 'source_app',
        'copy_count', 'fav', 'content_type', 'content_size', 'seq', 'is_estimated')
check('示例字段齐全',
      all(all(k in x for k in need) for x in normed),
      '缺字段的条目示例：%r' % [sorted(set(need) - set(x)) for x in normed if not all(k in x for k in need)])
check('示例 created_at 为真实时间戳（非估算）',
      all(int(x['created_at']) == int(it['created_at']) and x['is_estimated'] == 0
          for x, it in zip(normed, samples)))

# 走一遍完整的 validate（真实加载路径），条数不减、不崩
vdata = DataMixin.validate({'clip': [dict(it) for it in samples],
                            'groups': [{'name': '默认', 'items': []}], 'gi': 0,
                            'settings': {}, 'schema_version': 3})
check('validate 后剪贴板条数不变',
      len(vdata['clip']) == len(samples), '实际 %d' % len(vdata['clip']))
check('validate 后每条的 kind/content_type 正常',
      all(x.get('kind_auto') and x.get('content_type') for x in vdata['clip']))

# ---------- 4. GUI 闭环 ----------
import tkinter as tk          # noqa: E402
import ClawBoard as C         # noqa: E402

C.NO_SAVE = True              # 模块属性桥接到 runtime.NO_SAVE（双保险）

root = tk.Tk()
root.geometry('420x560+80+80')
app = C.ClawBoard(root)
if app.collapsed:             # 折叠态下 body 被收起，引导没机会摆放 → 先展开
    app.collapsed = False
    app.st['collapsed'] = False
    app.body.pack(fill='both', expand=True)
    app.root.minsize(*app.min_size())
root.update()
app.render()
root.update()

# 空数据：列表为空 + 引导卡片可见
check('空数据：列表为空', app.vlist.items == [])
check('空数据：引导卡片已显示', bool(app.onboard.winfo_ismapped()),
      'ismapped=%s' % app.onboard.winfo_ismapped())

# ---- 多缩放档 × 最小窗口：卡片不得裁切、主按钮必须完整可见可点击 ----
for lvl in C.UI_SCALE_LEVELS:
    app.set_ui_scale(lvl)
    root.update()
    mw, mh = app.min_size()
    root.geometry('%dx%d+60+60' % (mw, mh))
    root.update()
    app.render()
    root.update()
    ob = app.onboard
    need, avail = ob._wrap.winfo_reqheight(), ob.winfo_height()
    check('scale %.2f 最小窗口卡片不裁切' % lvl, need <= avail,
          'need=%d avail=%d' % (need, avail))
    btn_bottom = ob._btn.winfo_rooty() + ob._btn.winfo_height()
    card_bottom = ob.winfo_rooty() + ob.winfo_height()
    check('scale %.2f 主按钮完整可见可点击' % lvl,
          bool(ob._btn.winfo_ismapped()) and btn_bottom <= card_bottom + 1,
          'ismapped=%s btn_bottom=%d card_bottom=%d' % (
              ob._btn.winfo_ismapped(), btn_bottom, card_bottom))

# ---- 极端空间不足：按优先级收起次要行（hint → link → lead），三步与主按钮保留 ----
# 走真实路径：把卡片高度真的压小（place_configure），由 <Configure> 驱动自适应降级。
ob = app.onboard
ob.place_configure(relheight=0, height=60)
root.update()
check('空间不足：收起次要行但保留 title/steps/btn',
      ob.visible_rows() == ['title', 'steps', 'btn'],
      'visible=%s' % ob.visible_rows())
# 恢复铺满列表区 → 全部内容重新显示
ob.place(in_=app.vlist, relx=0, rely=0, relwidth=1, relheight=1)
root.update()
check('空间恢复：全部内容重新显示',
      ob.visible_rows() == ['title', 'lead', 'steps', 'hint', 'link', 'btn'],
      'visible=%s' % ob.visible_rows())

# 载入示例
app.load_samples()
root.update()
check('载入示例：剪贴板条目数正确',
      len(app.data['clip']) == len(samples),
      '实际 %d' % len(app.data['clip']))
check('载入示例：列表可见条目数正确',
      len(app.vlist.items) == len(samples),
      '实际 %d' % len(app.vlist.items))
check('载入示例：引导卡片自动隐藏', not app.onboard.winfo_ismapped(),
      'ismapped=%s' % app.onboard.winfo_ismapped())
check('载入示例：_seq 已跟上最大 seq',
      app._seq >= max(int(x.get('seq') or 0) for x in app.data['clip']))

# 常用语 Tab 空状态文案
app.tab = 'phrase'
app.render()
root.update()
check('常用语 Tab 空状态：使用针对性文案',
      app.vlist.empty_msg == '还没有常用语，点 ＋ 新建',
      'empty_msg=%r' % (app.vlist.empty_msg,))

# 删一条示例应正常（字段合法 → 可删除）
app.tab = 'clip'
app.render()
first = app.data['clip'][0]['id']
app.del_item(first, 'clip')
root.update()
check('示例可正常删除（少一条）',
      len(app.data['clip']) == len(samples) - 1,
      '实际 %d' % len(app.data['clip']))

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

# ---------- 5. 真实数据文件未被污染 ----------
HASH_AFTER = file_hash(REAL_DATA)
check('真实数据文件 hash 未变', HASH_BEFORE == HASH_AFTER,
      'before=%s after=%s' % (HASH_BEFORE, HASH_AFTER))
check('真实数据目录无新增 .bak 副本',
      data_sidecar_files() == FILES_BEFORE,
      'before=%s after=%s' % (FILES_BEFORE, data_sidecar_files()))
check('临时数据文件未被写入（NO_SAVE 生效）', not os.path.exists(TMP_DATA),
      '存在=%s' % os.path.exists(TMP_DATA))

# 清理临时目录
try:
    os.rmdir(TMP_DIR)
except Exception:
    pass

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_t38.out')
with open(out, 'w', encoding='utf-8') as f:
    f.write('\n'.join(LOG) + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))
print('\n'.join(LOG), flush=True)
print('全部通过' if OK else '有失败项', flush=True)
os._exit(0)
