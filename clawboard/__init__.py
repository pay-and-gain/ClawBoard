# -*- coding: utf-8 -*-
"""ClawBoard 分层重构包。

职责地图（自上而下的依赖方向，禁止向上 import）：
  config.py       集中配置 / 常量 / 数据契约（唯一无包内依赖的叶子）
  runtime.py      运行时可变全局（NO_SAVE / LAST_SEQ / TX / uid 计数器）
  theme.py        主题配色推导
  classify.py     内容分类 + 文本 / 尺寸 / 长度工具
  timefmt.py      时间格式化 + 来源忽略 + 数据迁移
  win32.py        Win32 ctypes 声明 + 系统原语 + 单实例 + 开机自启
  clipboard.py    剪贴板读写 + 隐私标记 + 敏感识别
  hotkey.py       隐藏消息窗口（热键 + 托盘）+ 图标生成
  widgets.py      通用控件 + 弹窗 + 布局 / 事件 helper
  vlist.py        虚拟滚动列表
  dialogs.py      设置 / 变换 / 导出三个业务弹窗
  app_*.py        主类 97 方法按生命周期拆成的 5 个 mixin
  app.py          class ClawBoard 组合根 + 统一状态初始化
入口 ClawBoard.py 保留为 re-export 聚合层，对外符号与老版本完全一致。
"""
# 版本号的唯一来源是 config.APP_VER（config.py 为包内叶子模块，不反向 import 本包，
# 故此处 from ... import 不会造成循环 import）。切勿在此再硬编码第二份版本号 —— 会再次过期。
from clawboard.config import APP_VER as __version__   # noqa: E402
