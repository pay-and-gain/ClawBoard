# -*- coding: utf-8 -*-
"""class ClawBoard 组合根：继承 5 个 mixin + __init__ 统一状态初始化。

这是 UI 编排层的唯一聚合点；方法实现分散在 app_services / app_ui / app_geometry /
app_interact 四个 mixin 中，本文件只负责「谁继承谁」和「状态一次性初始化到 self」。
"""
import time
import tkinter as tk
from dataclasses import fields

from clawboard.config import AppState, APP_NAME
from clawboard.theme import T, apply_theme
from clawboard.app_services import DataMixin, SystemMixin
from clawboard.app_ui import UiMixin
from clawboard.app_geometry import GeometryMixin
from clawboard.app_interact import InteractionMixin


class ClawBoard(DataMixin, SystemMixin, UiMixin, GeometryMixin, InteractionMixin):
    def __init__(self, root):
        self.root = root
        # 运行时状态唯一初始化来源：AppState 默认值一次性复制到 self，
        # 测试直读直写 app.tab / app.collapsed / app._restore 等仍然可用。
        state = AppState()
        for f in fields(AppState):
            setattr(self, f.name, getattr(state, f.name))
        # 不属于 AppState 的字段：UI 引用 / 派生状态 / 计时基准
        self.search = tk.StringVar()
        self.t0 = time.time()

        self.data = self.load_data()
        self.st = self.data['settings']
        self._seq = max([int(x.get('seq') or 0) for x in self.data['clip']] or [0])
        apply_theme(self.st)
        # 等比缩放必须在 build_ui 之前：字体走 tk scaling，布局尺寸走 scaled()
        self.apply_ui_scale_init()

        root.title(APP_NAME)
        root.overrideredirect(True)
        root.attributes('-topmost', True)
        root.attributes('-alpha', 0.97)
        root.configure(bg=T['bg'])
        root.bind('<Escape>', lambda e: self.hide())
        root.bind('<Up>', lambda e: self.move_sel(-1))
        root.bind('<Down>', lambda e: self.move_sel(1))
        root.bind('<Return>', lambda e: self.enter_sel())
        root.bind('<Control-f>', lambda e: self.focus_search())
        root.bind('<Delete>', lambda e: self.del_sel())
        root.bind('<Control-Shift-Return>', lambda e: self.paste_plain_sel())
        root.bind('<Control-t>', lambda e: self.open_transform())
        root.bind('<Control-e>', lambda e: self.open_export())
        root.bind('<Control-q>', lambda e: self.quit_app())
        root.bind('<Control-Shift-P>', lambda e: self.open_command_palette())
        # 等比缩放：Ctrl+= 放大一档 / Ctrl+- 缩小一档（Ctrl+0 已被快速粘贴占用）
        root.bind('<Control-equal>', lambda e: self.cycle_ui_scale(1))
        root.bind('<Control-minus>', lambda e: self.cycle_ui_scale(-1))
        # Ctrl+1..9 / Ctrl+0 → 直接粘贴第 1..10 项
        # （PasteBar ClipboardHistoryQuickPastePage.tsx:307，0 表示第 10 项）
        for _i in range(1, 10):
            root.bind('<Control-Key-%d>' % _i,
                      lambda e, n=_i: self.quick_paste(n))
        root.bind('<Control-Key-0>', lambda e: self.quick_paste(10))
        # 按住 Ctrl 时行首显示序号，把这组快捷键亮出来（Ditto QListCtrl.cpp:610）
        for _k in ('Control_L', 'Control_R'):
            root.bind('<KeyPress-%s>' % _k, lambda e: self.set_num_hint(True))
            root.bind('<KeyRelease-%s>' % _k, lambda e: self.set_num_hint(False))
        root.protocol('WM_DELETE_WINDOW', self.hide)

        self.build_ui()
        self.apply_geometry()
        # 窗口外观（圆角 + 毛玻璃）必须等窗口真正建立后再设：太早调用 DWM 会
        # 接受不了（读回圆角值仍是 0）。放在 geometry 之后、mainloop 之前。
        self.root.update_idletasks()
        self.apply_effects()
        self.save(True)      # 把修正后的位置立刻写回，避免下次启动又去纠正一遍
        self.setup_system()
        # P1-3：启动静默检查一次更新（带频率闸；NO_SAVE 自测模式自动跳过，见 setup_update_check）
        self.setup_update_check()
        self.render()
        self.root.after(120, self.render)
        self.poll_clip()
        self.poll_bg()          # 前台窗口记录已并入本循环，定时器从 3 个降到 2 个
