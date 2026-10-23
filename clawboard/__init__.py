# -*- coding: utf-8 -*-
"""ClawBoard：独立应用服务与 Windows / Tk 适配器。

职责地图（完整维护约定见 docs/REFACTOR.md）：
  config / runtime          版本、默认值、路径与兼容运行状态
  models / history          数据归一化、入库、编辑与派生元数据
  search / privacy          查询、惰性拼音缓存与统一显示策略
  classify / tag / timefmt  内容、标签、时间与迁移规则
  image / exports           可独立测试的图片编解码与导出格式
  application               应用控制器；不依赖 Tk 或 Win32
  dispatch / tasks          主线程结果队列与有界后台任务
  services                  剪贴板序列确认与单写入者保存
  storage / media           注入路径的 JSON、图片文件边界
  windows_* / win32_snapshot Win32 ABI、系统能力与剪贴板快照
  tk_bridge / paste_adapter 应用事件、异步粘贴与 Tk 接线
  viewmodels / thumbnails   可见行派生数据与缩略图缓存
  vlist / widgets           可复用行池和通用控件
  *_dialog                  设置、变换与导出界面
  app / app_* / system      兼容主窗口与交互适配层

领域与应用服务不反向导入 UI；组合根装配具体系统/文件接口。
ClawBoard.py、query.py、app_services.py、dialogs.py、win32.py 保留旧导出。
"""
# 版本号的唯一来源是 config.APP_VER（config.py 为包内叶子模块，不反向 import 本包，
# 故此处 from ... import 不会造成循环 import）。切勿在此再硬编码第二份版本号 —— 会再次过期。
from clawboard.config import APP_VER as __version__   # noqa: E402
