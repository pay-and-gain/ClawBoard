# -*- coding: utf-8 -*-
"""
ClawBoard - Windows 悬浮剪切板 & 常用语面板
零第三方依赖：Python 标准库 tkinter + ctypes(Win32)
适配 Windows 10 / 11

增量重构后：本文件只保留「入口 + re-export 聚合层」；
领域函数已按 数据/领域层 → 系统接入层 → UI 控件层 → UI 编排层 四层拆入 clawboard/ 包，
详见 clawboard/__init__.py 的职责地图。
"""
import os
import re
import sys
import json
import time
import ctypes
import threading
import traceback
import subprocess
import tkinter as tk
import tkinter.font as tkfont
from ctypes import wintypes

from clawboard import runtime
from clawboard.config import (
    APP_NAME, APP_VER, BASE_DIR, DATA_FILE, ICON_FILE, CRASH_LOG,
    FONT, FONT_B, FONT_SM, FONT_TITLE, FONT_MONO,
    ITEM_H, CARD_GAP, WHEEL_LINES, BAR_H, TOOL_H, MIN_W, MIN_H, MAX_TEXT,
    RESIZE_ZONE, SCHEMA_VERSION, CLASSIFY_MAX, DEFAULT_SETTINGS,
    UI_SCALE, UI_SCALE_LEVELS, scaled, rotate_log_if_needed,
)
from clawboard.runtime import NO_SAVE, LAST_SEQ, TX, tx, uid, now_str

import query as Q          # F3 查询解析器（独立模块，可单测）

# ---- re-export：领域函数层（对外符号与老版本一致） ----
from clawboard.theme import (DARK, LIGHT, T, set_theme, _rgb, shade, is_dark, apply_theme)
from clawboard.classify import (
    classify, looks_like_code, guess_lang, detect_content_type, byte_size,
    human_size, kind_icon, type_icon, to_plain, length_filtered, crop_items,
    preview, KIND_LABEL, KIND_ICON, TYPE_ICON,
)
from clawboard.timefmt import (
    now_ms, rel_time, full_time, parse_ignore_list, match_ignore, backup_data, migrate,
)

# ---- re-export：系统接入层（对外符号与老版本一致） ----
from clawboard.win32 import (
    u32, k32, psapi, sh32,
    mem_mb, cpu_ms, monitors, visible_ratio, dpi_scale, system_dpi,
    proc_name_of, window_title_of, capture_source,
    force_foreground, all_keys_up, send_ctrl_v, send_key,
    single_instance, init_dpi_awareness,
    autostart_cmd, get_autostart, set_autostart,
    MOD_CONTROL, MOD_SHIFT, MOD_ALT, VK_V, VK_CONTROL,
)
from clawboard.clipboard import (
    clip_seq, clip_read, clip_write, clip_is_private, scan_sensitive, mask_text,
    SENS_PATTERNS,
)
from clawboard.hotkey import HiddenWindow, make_ico

# ---- re-export：UI 控件层 + 主类（对外符号与老版本一致） ----
from clawboard.widgets import (
    pack_static_then_fill, bind_recursive,
    dark_top, center_on, safe_release,
    Dialog, SplitDialog, Tip, ThinBar, ScrollFrame,
)
from clawboard.vlist import VirtualList
from clawboard.dialogs import SettingsWindow, TransformWindow, ExportDialog
from clawboard.app import ClawBoard


# ---------------- 崩溃兜底 ----------------
def install_excepthook():
    def hook(etype, val, tb):
        try:
            rotate_log_if_needed(CRASH_LOG)
            with open(CRASH_LOG, 'a', encoding='utf-8') as f:
                f.write('\n==== 未捕获异常 %s ====\n' % time.strftime('%F %T'))
                f.write(''.join(traceback.format_exception(etype, val, tb)))
        except Exception:
            pass
        sys.__excepthook__(etype, val, tb)
    sys.excepthook = hook


def tk_error(root):
    def cb(exc, val, tb):
        text = ''.join(traceback.format_exception(exc, val, tb))
        if runtime.NO_SAVE:
            # 自测实例：打到 stderr 而不是写进真实 crash.log。
            # 写日志的话异常会被静默吞掉，自测只看得到一句 FAIL 却不知道原因
            sys.stderr.write('\n[Tk 回调异常] %s\n' % text)
            sys.stderr.flush()
            return
        try:
            rotate_log_if_needed(CRASH_LOG)
            with open(CRASH_LOG, 'a', encoding='utf-8') as f:
                f.write('\n==== Tk 回调异常 %s ====\n' % time.strftime('%F %T'))
                f.write(text)
        except Exception:
            pass
    root.report_callback_exception = cb


# ---------------- 9. 入口 ----------------


def bench():
    """性能实测：跑完输出真实数字后退出（压测数据绝不落盘）"""
    import random
    import string
    runtime.NO_SAVE = True   # 必须在建实例之前：__init__ 里就会 save 一次（曾经漏了这条，热键被改掉）
    root = tk.Tk()
    app = ClawBoard(root)
    root.geometry('340x480+-2000+-2000')   # 移出屏幕但保持 mapped，保证布局真实
    root.update()
    print('启动到可响应: %.0f ms' % ((time.time() - app.t0) * 1000))
    print('初始常驻内存: %.1f MB' % mem_mb())

    base = ''.join(random.choice(string.ascii_letters + '测试中文') for _ in range(60))
    n = 10000
    t0 = time.time()
    for i in range(n):
        app.data['clip'].append({'id': uid(), 'text': base + str(i), 'time': now_str()})
    print('灌入 %d 条耗时: %.0f ms' % (n, (time.time() - t0) * 1000))

    t0 = time.time()
    app.render()
    root.update()
    print('%d 条首次渲染: %.0f ms' % (n, (time.time() - t0) * 1000))

    t0 = time.time()
    for _ in range(30):
        app.vlist.yview_step(60)
        app.vlist.update_view()
        root.update()
    print('滚动刷新 x30 平均: %.2f ms/次' % ((time.time() - t0) / 30 * 1000))

    t0 = time.time()
    for i in range(200):
        app.search.set(str(random.randint(0, n)))
        app.render()
    print('普通搜索 200 次平均: %.2f ms/次' % ((time.time() - t0) / 200 * 1000))

    t0 = time.time()
    for i in range(50):
        app.search.set('app:chrome size:>10 time:<1d')
        app.render()
    print('高级语法搜索 50 次平均: %.2f ms/次' % ((time.time() - t0) / 50 * 1000))
    app.search.set('')
    app.render()

    c0 = cpu_ms()
    w0 = time.time()
    time.sleep(3)
    print('空闲 3 秒 CPU 占用: %.2f %%' % ((cpu_ms() - c0) / ((time.time() - w0) * 10.0)))
    print('%d 条后内存: %.1f MB' % (n, mem_mb()))
    print('虚拟列表实际 widget 数: %d / %d 条' % (len(app.vlist.pool), n))
    # 压测数据绝不落盘：直接销毁，不走 save()
    try:
        app.hw.unreg_hotkey()
        app.hw.tray_del()
        app.hw.stop()
    except Exception:
        pass
    app.root.destroy()


def main():
    init_dpi_awareness()
    install_excepthook()
    if '--bench' in sys.argv:
        bench()
        return
    if '--shot' in sys.argv:
        # 截图/量布局用：起一个不写盘、不抢单实例的实例，宽度由 --shot 后面的数字决定。
        # 直接复用真实设置会把折叠态带进来（body 被 pack_forget，量出来全是 1px）
        runtime.NO_SAVE = True
        DEFAULT_SETTINGS['collapsed'] = False
        i = sys.argv.index('--shot')
        sw = int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 349
        root = tk.Tk()
        app = ClawBoard(root)
        if app.collapsed:
            app.collapsed = False
            app.body.pack(fill='both', expand=True)
            app.root.minsize(*app.min_size())
        root.geometry('%dx460+60+60' % sw)
        root.update()
        app._last_tw = 0
        app._layout_tool()
        root.update()
        print('W=%d tool=%d entry=%d vis=%s' % (
            sw, app.tool.winfo_width(), app.search_entry.winfo_width(),
            [b.cget('text') for _, b in app._tool_btns if b.winfo_ismapped()]),
            flush=True)
        root.mainloop()
        return
    if not single_instance():
        sys.exit(0)
    root = tk.Tk()
    tk_error(root)
    app = ClawBoard(root)
    app.note('%s v%s 启动（热键 %s，pid %d，窗口 %s，最小 %s，tk scaling %s）'
             % (APP_NAME, APP_VER, app.st['hotkey'], os.getpid(),
                root.geometry(), root.minsize(), root.tk.call('tk', 'scaling')))
    root.mainloop()


if __name__ == '__main__':
    main()


# ---------------------------------------------------------------------------
# NO_SAVE 模块属性桥接（坑④固化点之一）
# 测试脚本写 `C.NO_SAVE = True` 是对模块属性的**重绑定**，普通 re-export 只能共享
# 导入那一刻的旧值。这里把 ClawBoard 模块的 __setattr__ 替换掉，把对 NO_SAVE 的
# 赋值转发到真正的唯一布尔源 `runtime.NO_SAVE`，让 save()/note()/tk_error() 读到 True。
# 必须放在文件末尾（所有 `from ... import ...` 完成后），避免干扰 import 期绑定。
# ---------------------------------------------------------------------------
import types as _types


class _CompatModule(_types.ModuleType):
    _FORWARD = {'NO_SAVE': 'NO_SAVE'}   # 模块属性名 → runtime 属性名

    def __setattr__(self, name, value):
        if name in self._FORWARD:
            setattr(runtime, self._FORWARD[name], value)
            return
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _CompatModule
