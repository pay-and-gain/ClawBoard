# -*- coding: utf-8 -*-
"""测试：靠边自动隐藏 + 开机自启开关"""
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ClawBoard as cb

log = []
root = cb.tk.Tk()
app = cb.ClawBoard(root)
root.geometry('340x480+600+300')
root.update()


def step():
    try:
        # ---------- 靠边自动隐藏 ----------
        log.append('默认 edge_hide=%s（应为 False）' % app.st['edge_hide'])
        app.st['edge_hide'] = True
        app.root.geometry('+0+300')       # 贴左边缘
        root.update()
        # 手动驱动：模拟鼠标远离窗口（直接调内部方法验证位移正确性）
        app._edge_tick = 0
        app._edge_hide('left')
        root.update()
        x1 = app.root.winfo_x()
        log.append('贴左边缘收起后 x=%d（期望 %d）%s' %
                   (x1, -(340 - 6), 'OK' if x1 == -(340 - 6) else 'FAIL'))
        app._edge_show()
        root.update()
        log.append('滑出后 x=%d（期望 0）%s' % (app.root.winfo_x(),
                                               'OK' if app.root.winfo_x() == 0 else 'FAIL'))
        # 右边缘
        sw = root.winfo_screenwidth()
        app.root.geometry('+%d+300' % (sw - 340))
        root.update()
        app._edge_hide('right')
        root.update()
        log.append('贴右边缘收起后 x=%d（期望 %d）%s' %
                   (app.root.winfo_x(), sw - 6,
                    'OK' if app.root.winfo_x() == sw - 6 else 'FAIL'))
        app._edge_show()
        # 上边缘
        app.root.geometry('+600+0')
        root.update()
        app._edge_hide('top')
        root.update()
        log.append('贴上边缘收起后 y=%d（期望 %d）%s' %
                   (app.root.winfo_y(), -(480 - 6),
                    'OK' if app.root.winfo_y() == -(480 - 6) else 'FAIL'))
        app._edge_show()
        # 关闭开关后不应再收起
        app.st['edge_hide'] = False
        app.root.geometry('+0+300')
        root.update()
        for _ in range(20):
            app.edge_update()
        log.append('关闭开关后 x=%d（应仍为 0）%s' %
                   (app.root.winfo_x(), 'OK' if app.root.winfo_x() == 0 else 'FAIL'))
        # 开关本身能持久化
        app.st['edge_hide'] = True
        app.save()
        d = app.load_data()
        log.append('开关持久化=%s' % d['settings'].get('edge_hide'))

        # ---------- 开机自启（真实读写注册表，测试后必定还原） ----------
        before, _ = cb.get_autostart()
        log.append('测试前注册表状态=%s' % before)
        try:
            ok1 = cb.set_autostart(True)
            on, val = cb.get_autostart()
            log.append('开启: 返回=%s 读取=%s 命令=%s' % (ok1, on, val[:70]))
            ok2 = cb.set_autostart(False)
            off, _ = cb.get_autostart()
            log.append('关闭: 返回=%s 读取=%s' % (ok2, off))
            log.append('往返正确=%s' % (ok1 and on and ok2 and not off))
        finally:
            # 无论如何还原到测试前的状态
            cb.set_autostart(before)
            after, _ = cb.get_autostart()
            log.append('已还原到测试前状态: %s（测试前 %s）%s' %
                       (after, before, 'OK' if after == before else 'FAIL'))
        log.append('autostart_cmd=%s' % cb.autostart_cmd()[:90])
    except Exception:
        import traceback
        log.append('ERR ' + traceback.format_exc()[-900:])
    for x in log:
        print(x, flush=True)
    print('=== 结束 ===', flush=True)
    app.hw.tray_del()
    app.hw.stop()
    root.destroy()


root.after(600, step)
root.mainloop()
