# -*- coding: utf-8 -*-
"""M0/F0/F1/F2/F6 冒烟测试"""
import sys
import os
import json
import time
import shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ClawBoard as cb

log = []


def p(x):
    log.append(x)


# ---------- 纯函数层（不需要 GUI） ----------
p('detect_content_type: url=%s json=%s multiline=%s text=%s' % (
    cb.detect_content_type('https://a.com/x'),
    cb.detect_content_type('{"a": 1}'),
    cb.detect_content_type('a\nb'),
    cb.detect_content_type('hello')))
p('human_size: %s %s %s' % (cb.human_size(512), cb.human_size(2048),
                            cb.human_size(3 * 1024 * 1024)))
p('rel_time: 刚刚=%s 5分钟前=%s' % (
    cb.rel_time(cb.now_ms() - 1000), cb.rel_time(cb.now_ms() - 300000)))
html_in = '<p>你好&nbsp;&amp; 世界</p><ul><li>一</li><li>二</li></ul>'
p('to_plain: %r' % cb.to_plain(html_in))

# ---------- M0 迁移：用老库实跑 ----------
old = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'testdata', 'old_v1.json')
if not os.path.exists(old):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'testdata'))
    import gen_old_db  # noqa
raw = json.load(open(old, 'r', encoding='utf-8'))
n_before = len(raw['clip'])
n_phr_before = len(raw['groups'][0]['items'])
shutil.copy(old, cb.DATA_FILE)
migrated = cb.migrate(json.loads(json.dumps(raw)))
migrated = cb.ClawBoard.validate(migrated)
p('M0 迁移前 clip=%d phrase=%d' % (n_before, n_phr_before))
p('M0 迁移后 clip=%d phrase=%d version=%s' % (
    len(migrated['clip']), len(migrated['groups'][0]['items']),
    migrated['schema_version']))
p('M0 老数据是否标记估算: is_estimated=%s 首条created_at非空=%s' % (
    migrated['clip'][0].get('is_estimated'), bool(migrated['clip'][0].get('created_at'))))
p('M0 字段齐全: %s' % all(k in migrated['clip'][0] for k in
                          ('created_at', 'updated_at', 'last_used_at', 'seq',
                           'source_app', 'content_type', 'content_size', 'copy_count')))
# 幂等：再跑一次不应改变条数
m2 = cb.migrate(json.loads(json.dumps(migrated)))
p('M0 幂等: %s' % (len(m2['clip']) == len(migrated['clip']) and
                   m2['schema_version'] == cb.SCHEMA_VERSION))
# 备份存在
p('M0 备份文件: %s' % os.path.exists(cb.DATA_FILE + '.bak'))

# ---------- GUI 层 ----------
root = cb.tk.Tk()
app = cb.ClawBoard(root)
p('迁移后启动 clip=%d（应与迁移前一致或已迁移）' % len(app.data['clip']))


def step():
    try:
        # F0 入库：新条目带完整字段
        app.data['clip'] = []
        app.ingest('第一条测试内容')
        p('F0 新条目 source=%s type=%s size=%s copy_count=%s' % (
            app.data['clip'][0]['source_app'], app.data['clip'][0]['content_type'],
            app.data['clip'][0]['content_size'], app.data['clip'][0]['copy_count']))
        c1 = app.data['clip'][0]['created_at']
        # 重复复制：copy_count+1，created_at 不变
        time.sleep(0.05)
        app.ingest('第一条测试内容')
        same = app.data['clip'][0]
        p('F0 重复复制 copy_count=%d created_at不变=%s updated_at已刷新=%s' % (
            same['copy_count'], same['created_at'] == c1, same['updated_at'] >= c1))
        # 时钟回拨保护
        app.data['clip'][0]['created_at'] = cb.now_ms() + 7200 * 1000
        app.ingest('时钟回拨后复制的内容')
        p('F0 时钟回拨保护: 新条目 created_at >= 库中最大 = %s' % (
            app.data['clip'][0]['created_at'] >= app.data['clip'][1]['created_at']))
        # F0 粘贴只刷新 last_used_at
        tgt = app.data['clip'][0]
        before_created = tgt['created_at']
        app.paste(tgt['text'], cid=tgt['id'])
        p('F0 粘贴后 last_used_at=%s created_at未变=%s' % (
            bool(tgt.get('last_used_at')), tgt['created_at'] == before_created))
        # 渲染：badge / 来源
        app.render()
        root.update()
        it0 = app.vlist.items[0] if app.vlist.items else {}
        p('F1/F2 渲染 sub=%r badge=%r' % (it0.get('sub'), it0.get('badge')))
        # 设置：显示时间开关
        app.st['show_time'] = True
        app.render()
        p('F0 显示时间开启后 sub=%r' % (app.vlist.items[0].get('sub') if app.vlist.items else None))
        app.st['show_time'] = False
        # 收藏 + 详情
        cid = app.data['clip'][0]['id']
        app.toggle_fav(cid)
        p('is:fav 收藏生效=%s' % (app.data['clip'][0]['fav'] == 1))
        # F6 纯文本
        app.data['clip'][0]['text'] = html_in
        got = cb.to_plain(app.data['clip'][0]['text'])
        p('F6 剥离结果=%r' % got)
        p('F6 无残留标签=%s' % ('<' not in got and '&nbsp;' not in got))
        # 热键状态
        p('热键 注册=%s 降级=%s' % (app.hotkey_ok, app.hotkey_fallback))
        app.save()
        p('保存 ok=%s' % os.path.exists(cb.DATA_FILE))
    except Exception:
        import traceback
        p('ERR ' + traceback.format_exc()[-800:])
    for x in log:
        print(x)
    app.quit_app()


root.after(700, step)
root.mainloop()
