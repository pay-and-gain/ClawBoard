# -*- coding: utf-8 -*-
"""R 轮：7 项核心功能回归 + 老库兼容 + 常用语功能回归"""
import os
import sys
import json
import shutil
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ClawBoard as cb

log = []
DATA = cb.DATA_FILE


def step():
    try:
        root = cb.tk.Tk()
        app = cb.ClawBoard(root)
        root.update()
        out = []

        # 1 监听：写剪贴板 + 重置序号 → 下一次 poll 必须入库
        n0 = len(app.data['clip'])
        cb.clip_write('回归测试_监听内容_%d' % int(time.time()))
        cb.LAST_SEQ = 0                      # 强制让监听器认为有变化
        app.poll_clip()
        root.update()
        out.append('1 监听入库: %d -> %d %s' % (n0, len(app.data['clip']),
                                               'OK' if len(app.data['clip']) > n0 else 'FAIL'))

        # 2 持久化：保存后重新加载，条数内容一致
        app.save()
        d2 = app.load_data()
        out.append('2 持久化: %d 条 一致=%s' % (len(d2['clip']),
                                               len(d2['clip']) == len(app.data['clip'])))

        # 3 搜索
        app.search.set('回归测试')
        app.render()
        root.update()
        hit = len(app.vlist.items)
        app.search.set('')
        app.render()
        out.append('3 搜索命中: %d 条 %s' % (hit, 'OK' if hit >= 1 else 'FAIL'))

        # 4 全局热键
        out.append('4 热键注册: %s（降级=%s）' % (app.hotkey_ok, app.hotkey_fallback))

        # 5 托盘
        out.append('5 托盘线程: alive=%s hwnd=%s' % (app.hw.is_alive(), bool(app.hw.hwnd)))

        # 6 设置项切换不崩
        for k in ('listen', 'autopaste', 'mask_sensitive', 'skip_sensitive',
                  'show_time', 'record_title'):
            app.st[k] = not app.st[k]
        app.rebuild()
        for k in ('listen', 'autopaste', 'mask_sensitive', 'skip_sensitive',
                  'show_time', 'record_title'):
            app.st[k] = not app.st[k]
        app.rebuild()
        out.append('6 设置切换: 全部开关来回切一次 OK')

        # 7 单实例互斥
        first = cb.single_instance()
        second = cb.single_instance()
        out.append('7 单实例: 首次=%s 二次=%s %s' % (first, second,
                                                    'OK' if (first and not second) else 'FAIL'))

        # 8 敏感识别仍在生效
        h = cb.scan_sensitive('身份证 41022120080718031X')
        out.append('8 敏感识别: %s' % (h or 'FAIL'))

        # 9 常用语：分组 + 拆词 + 编辑 + 命名 + 删除
        app.tab = 'phrase'
        app.data['groups'] = [{'name': '默认', 'items': []}]
        app.data['gi'] = 0
        app.render()
        app.push_phrase('问候', '你好世界')
        sd = cb.SplitDialog(app, 'A,B;C D\nE')
        sd.ok()
        n_items = len(app.cur_group()['items'])
        cid = app.cur_group()['items'][0]['id']
        app.rename_phrase(cid)
        app.del_item(cid, 'phrase')
        out.append('9 常用语: 拆词后=%d 删除后=%d %s' %
                   (n_items, len(app.cur_group()['items']),
                    'OK' if len(app.cur_group()['items']) == n_items - 1 else 'FAIL'))

        # 10 键盘导航
        app.tab = 'clip'
        app.render()
        root.update()
        app.move_sel(1)
        app.move_sel(1)
        app.move_sel(-1)
        out.append('10 键盘导航: 选中=%s' % bool(app.sel_clip))

        # 11 主题切换两次
        for name in ('light', 'dark'):
            cb.set_theme(name)
            app.rebuild()
            root.update()
        out.append('11 主题切换: OK')

        app.hw.tray_del()
        app.hw.stop()
        root.destroy()

        # 12 老库兼容：v1 老文件启动后条数一致 + 生成 .bak
        old = os.path.join(cb.BASE_DIR, 'testdata', 'old_v1.json')
        raw = json.load(open(old, 'r', encoding='utf-8'))
        n_before = len(raw['clip'])
        shutil.copy(old, DATA)
        root2 = cb.tk.Tk()
        app2 = cb.ClawBoard(root2)
        root2.update()
        out.append('12 老库升级: 迁移前=%d 迁移后=%d 备份=%s %s' % (
            n_before, len(app2.data['clip']), os.path.exists(DATA + '.bak'),
            'OK' if len(app2.data['clip']) == n_before else 'FAIL'))
        out.append('12 老库字段: seq=%s source=%s estimated=%s' % (
            app2.data['clip'][0].get('seq'), app2.data['clip'][0].get('source_app'),
            app2.data['clip'][0].get('is_estimated')))
        app2.hw.tray_del()
        app2.hw.stop()
        root2.destroy()
    except Exception:
        import traceback
        out = ['ERR ' + traceback.format_exc()[-1200:]]
    for x in out:
        print(x, flush=True)
    print('=== 回归结束 ===', flush=True)


step()
