# -*- coding: utf-8 -*-
"""运行时可变全局状态：NO_SAVE / LAST_SEQ / TX / uid 计数器。

约定（跨文件）：
- NO_SAVE 是「是否写盘」的唯一布尔源，业务代码一律通过 `runtime.NO_SAVE` 属性访问，
  禁止 `from clawboard.runtime import NO_SAVE` 再重绑定。
- LAST_SEQ 是剪贴板序列号缓存，同样只能原地重绑定（`runtime.LAST_SEQ = ...`）。
- TX 是 F4 变换模块的懒加载缓存，请始终通过 `tx()` 获取，不要直接读 TX。
"""
import time

NO_SAVE = False      # --bench/--shot/自测置 True：绝不把任何东西写回存档
LAST_SEQ = 0         # 剪贴板序列号，由 clipboard.py 在导入时初始化为当前值

BASE_SCALING = 1.3333333   # 真实 DPI 的 tk scaling（启动时记录，UI 缩放前）。
                           # 字体缩放 = tk scaling = BASE_SCALING * config.UI_SCALE；
                           # dpi_scale() 用它算 DPI 系数，绝不读被 UI 缩放改过的实时值
                           # （否则会双重缩放）。

TX = None            # F4 变换模块延迟到首次打开变换窗口时再导入
_seq = [0]


def tx():
    """延迟导入 transform：启动时不必拉起 hashlib/base64/urllib"""
    global TX
    if TX is None:
        import transform
        TX = transform
    return TX


def uid():
    _seq[0] += 1
    return '%d_%d' % (int(time.time() * 1000), _seq[0])


def now_str():
    return time.strftime('%m-%d %H:%M')
