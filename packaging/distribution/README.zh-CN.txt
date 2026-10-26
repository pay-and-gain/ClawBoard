ClawBoard {version} — Windows 剪贴板历史与常用语

快速开始
1. 将便携包完整解压到一个可写文件夹，双击 ClawBoard.exe。无需安装 Python。
2. 默认 Ctrl+Shift+V 显示或隐藏面板，选择条目后按 Enter 粘贴。
3. Ctrl+Q 或托盘菜单“退出”正常关闭程序。

v3 新增
纸感爪印界面、紧凑工具栏；来源和大小默认隐藏。面板内 Ctrl+Shift+W 打开只读工作台，查看预览后可定位回快速面板，不自动粘贴。
设置 → 数据提供完整备份与恢复，以及误删回收站。回收站保留手动删除内容最多30天、最多5000条；满额拒绝新删除，自动历史裁剪不进入回收站。

数据与升级
便携模式的 ClawBoard数据.json 和 images 文件夹与 exe 同层。升级前先退出并备份这两部分；替换 exe 后继续保留原文件。目录不可写时，数据回退到 %APPDATA%\ClawBoard，请在托盘“关于”核对路径。

完整备份包含历史、常用语、回收站、设置和引用图片，恢复前先预览并保留原库。普通 JSON 导出不能整库恢复；外部文件仍只保留路径。

触发词只支持独立标准 US 键盘布局；微软拼音的“中”“英”模式及其它/未知布局不自动展开。中文复制、搜索和常用语点击仍可使用。管理员目标请在确认复制成功后手动 Ctrl+V。

可选安装包
完整分享包另含 ClawBoard-{version}-setup.exe。安装版会创建安装登记及快捷方式；桌面快捷方式默认不选。卸载默认保留数据，静默卸载也保留数据；只清除属于本安装的自启动项。

隐私与校验
本包不含用户历史、图片、测试库或个人备份。程序数据为未加密 JSON/PNG，显示遮罩不等于加密。默认更新检查访问 GitHub，只提示并跳转下载页，可在设置关闭。
BUILD-INFO.txt 记录源码与构建信息，SHA256SUMS.txt 用于核对包内文件；MIT 许可见 LICENSE.txt。

项目：https://github.com/pay-and-gain/ClawBoard
指南：https://github.com/pay-and-gain/ClawBoard/blob/v{version}/docs/getting-started.md
