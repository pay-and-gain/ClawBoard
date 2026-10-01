# -*- coding: utf-8 -*-
"""F3 高级搜索 / F4 变换窗口 / F5 批量导出 集成测试"""
import os
import sys
import time
import glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ClawBoard as cb

log = []
root = cb.tk.Tk()
app = cb.ClawBoard(root)

NOW = cb.now_ms()


def mk(text, app_name='chrome', ctype='text', size=None, fav=0, ts=None):
    return {'id': cb.uid(), 'text': text, 'name': '', 'time': cb.now_str(),
            'created_at': ts if ts is not None else NOW,
            'updated_at': ts if ts is not None else NOW, 'last_used_at': None,
            'seq': 1, 'source_app': app_name, 'source_title': None,
            'content_type': ctype, 'content_size': size or cb.byte_size(text),
            'copy_count': 1, 'fav': fav, 'sens': None, 'meta': None,
            'is_estimated': 0}


def step():
    try:
        app.data['clip'] = [
            mk('hello world 中文', app_name='chrome', ctype='text'),
            mk('https://example.com/a', app_name='EXCEL', ctype='url'),
            mk('{"a":1}', app_name='WeChat', ctype='json', fav=1),
            mk('big data', app_name='notepad', ctype='text', size=3 * 1024 * 1024),
            mk('old news', app_name='chrome', ctype='text', ts=NOW - 3 * 86400 * 1000),
        ]
        app.tab = 'clip'
        app.search.set('')
        app.render()
        root.update()
        log.append('基线 5 条，渲染 %d 条' % len(app.vlist.items))

        # F3 各语法
        for q, expect in (('app:chrome', 2), ('app:excel', 1), ('app:hro', 2),
                          ('type:url', 1), ('type:json', 1),
                          ('size:>1mb', 1), ('size:<100', 4),
                          ('is:fav', 1), ('time:>1d', 1), ('time:<1h', 4),
                          ('中文', 1), ('hello -world', 0),
                          ('app:chrome -type:url', 2),   # chrome 两条都是 text，排除 url 不影响
                          ('chrome', 0)):   # 不带前缀 = 搜正文，不搜来源
            app.search.set(q)
            app.render()
            root.update()
            ok = len(app.vlist.items) == expect
            log.append('F3 [%s] -> %d 条 (期望 %d) %s' %
                       (q, len(app.vlist.items), expect, 'OK' if ok else 'FAIL'))

        # F3 语法错误：不崩溃 + 有提示
        app.search.set('time:zzz type:qqq')
        app.render()
        root.update()
        log.append('F3 错误语法 search_err=%r 不崩=True' % app.search_err)
        app.search.set('')
        app.render()

        # F3 历史
        app.search.set('app:chrome')
        app.on_search_return()
        log.append('F3 搜索历史=%s' % (app.data.get('search_history') or [])[:3])
        app.search.set('')
        app.render()

        # F4 变换窗口
        tw = cb.TransformWindow(app, 'hello world', app.data['clip'][0])
        tw.lb.selection_set(19)          # md5
        tw.run()
        root.update()
        got = tw.out.get('1.0', 'end-1c')
        import hashlib
        want = hashlib.md5('hello world'.encode()).hexdigest()
        log.append('F4 md5 变换=%s 正确=%s' % (got.strip(), got.strip() == want))
        # JSON 格式化失败要报错
        tw.lb.selection_clear(0, 'end')
        tw.lb.selection_set(13)          # jsonfmt
        tw.src.delete('1.0', 'end')
        tw.src.insert('1.0', '{bad json}')
        tw.run()
        root.update()
        log.append('F4 非法 JSON 报错=%s' % tw.out.get('1.0', 'end-1c')[:30])
        # 存为新条目（非破坏性）
        tw.lb.selection_clear(0, 'end')
        tw.lb.selection_set(0)           # deformat
        tw.src.delete('1.0', 'end')
        tw.src.insert('1.0', '<p>新内容</p>')
        tw.run()
        root.update()
        n_before = len(app.data['clip'])
        tw.save_new()
        log.append('F4 存新条目 %d -> %d（原条目保留）' % (n_before, len(app.data['clip'])))
        # 覆盖原条目：created_at 不变
        tgt = app.data['clip'][1]
        old_created = tgt['created_at']
        tw2 = cb.TransformWindow(app, 'x', tgt)
        tw2.src.delete('1.0', 'end')
        tw2.src.insert('1.0', 'AAA')
        tw2.out.delete('1.0', 'end')
        tw2.out.insert('1.0', 'BBB')
        tw2.overwrite()
        log.append('F4 覆盖后 text=%s created_at未变=%s' %
                   (tgt['text'], tgt['created_at'] == old_created))
        tw.win.destroy()
        tw2.win.destroy()

        # F5 多选 + 导出
        app.search.set('')
        app.render()
        app.vlist.multi = {app.vlist.items[0]['id'], app.vlist.items[1]['id']}
        ed = cb.ExportDialog(app)
        for fmt in ('txt', 'csv', 'json', 'md'):
            ed.fmt.set(fmt)
            ed.do_export()
        files = sorted(glob.glob(os.path.join(cb.BASE_DIR, '导出_*')))
        log.append('F5 导出文件数=%d' % len(files))
        for f in files:
            with open(f, 'rb') as fh:
                head = fh.read(3)
            size = os.path.getsize(f)
            log.append('F5 %s %d 字节 BOM=%s' % (os.path.basename(f), size,
                                                 head[:3] == b'\xef\xbb\xbf'))
        csvs = [f for f in files if f.endswith('.csv')]
        if csvs:
            with open(csvs[0], 'r', encoding='utf-8-sig') as fh:
                first = fh.readline().strip()
            log.append('F5 CSV 表头=%s' % first)
        js = [f for f in files if f.endswith('.json')]
        if js:
            import json
            d = json.load(open(js[0], 'r', encoding='utf-8'))
            log.append('F5 JSON 条数=%d version=%s' % (len(d['items']), d['version']))
    except Exception:
        import traceback
        log.append('ERR ' + traceback.format_exc()[-900:])
    for x in log:
        print(x, flush=True)
    print('=== 测试结束 ===', flush=True)
    app.quit_app()
    root.after(500, root.destroy)


root.after(600, step)
root.mainloop()
