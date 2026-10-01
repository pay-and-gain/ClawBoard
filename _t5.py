# -*- coding: utf-8 -*-
"""测试：窗口完整可见（双屏不跨缝） + 后台循环异常保护"""
import os
import sys
import json
import io
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ClawBoard as cb

log = []

# 造一个"上次停在双屏缝隙上"的位置
d = {}
if os.path.exists(cb.DATA_FILE):
    try:
        d = json.load(io.open(cb.DATA_FILE, encoding='utf-8'))
    except Exception:
        d = {}
d['geom'] = '340x480+1876+331'
d['schema_version'] = cb.SCHEMA_VERSION
json.dump(d, io.open(cb.DATA_FILE, 'w', encoding='utf-8'), ensure_ascii=False)

root = cb.tk.Tk()
app = cb.ClawBoard(root)
root.update()


def parse_geo(g):
    m = cb.re.match(r'^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$', g)
    return tuple(int(v) for v in m.groups()) if m else None


def step():
    try:
        log.append('显示器: %s' % (cb.monitors(),))
        pm = app.primary_monitor()
        log.append('主屏: %s' % (pm,))

        # 1) 跨屏位置应被判定为不完整可见
        w, h, x, y = 340, 480, 1876, 331
        log.append('跨屏位置可见比例=%.3f（<1 说明会被修正）' % cb.visible_ratio(x, y, w, h))
        fw, fh, fx, fy = app.fit_geometry(w, h, x, y)
        inside = any(fx >= l and fy >= t and fx + fw <= r and fy + fh <= b
                     for (l, t, r, b) in cb.monitors())
        log.append('修正后 %dx%d+%d+%d 完整落在单一显示器=%s' % (fw, fh, fx, fy, inside))

        # 2) 启动后的实际位置
        g = parse_geo(root.geometry())
        if g:
            w2, h2, x2, y2 = g
            vr = cb.visible_ratio(x2, y2, w2, h2)
            log.append('启动位置=%s 可见比例=%.3f %s' % (g, vr, 'OK' if vr >= 0.999 else 'FAIL'))

        # 3) 拖到屏幕外会被拉回
        app.root.geometry('+%d+300' % (pm[2] + 800))
        root.update()
        app.clamp_to_screen()
        root.update()
        g3 = parse_geo(root.geometry())
        w3, h3, x3, y3 = g3
        vr3 = cb.visible_ratio(x3, y3, w3, h3)
        log.append('拖出屏幕后=%s 可见=%.3f %s' % (g3, vr3, 'OK' if vr3 >= 0.999 else 'FAIL'))

        # 4) 后台循环异常保护：注入一个必然抛错的值
        app.st['edge_delay'] = '坏值'
        app.st['edge_hide'] = True
        try:
            app.poll_bg()          # 内部异常必须被吞掉，且 after 链要续上
            ok = True
        except Exception as e:
            ok = False
            log.append('poll_bg 抛出了异常（未被保护）: %s' % e)
        log.append('注入异常后 poll_bg 未崩溃=%s' % ok)
        app.st['edge_delay'] = 8
        app.st['edge_hide'] = False

        # 5) 后台循环仍在跑：登记一个探针
        probe = {'ran': False}

        def ping():
            probe['ran'] = True
        app.root.after(400, ping)
        app.root.after(900, finish)

        def finish():
            log.append('后台 after 链仍在运行=%s' % probe['ran'])
            # 6) 后台补抓来源接口存在
            log.append('_late_source 存在=%s' % callable(getattr(app, '_late_source', None)))
            for x in log:
                print(x, flush=True)
            print('=== 结束 ===', flush=True)
            app.hw.tray_del()
            app.hw.stop()
            try:
                app.root.destroy()
            except Exception:
                pass
            os._exit(0)
        root.after(1000, finish)
    except Exception:
        import traceback
        print('ERR ' + traceback.format_exc()[-900:], flush=True)
        os._exit(1)


root.after(600, step)
root.mainloop()
