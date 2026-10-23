# ClawBoard

**简体中文** | [English](README.en.md)

Windows 剪贴板历史与常用语面板。找回复制过的文字、截图和文件路径，搜索后粘贴到正在编辑的位置，也能把重复使用的内容存成常用语。

[下载 v2.7.0](https://github.com/pay-and-gain/ClawBoard/releases/tag/v2.7.0) · [新手指南](docs/getting-started.md) · [本次改动 PR #1](https://github.com/pay-and-gain/ClawBoard/pull/1) · [Windows 验证记录](docs/WINDOWS_VALIDATION.md)

> **v2.7.0 包含服务重构、输入法防误删、管理员窗口安全降级和主面板跨屏缩放。** 升级前备份数据文件和图片目录。旧 v2.6.1 不包含本轮输入保护，仍使用旧版时请关闭触发词。

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/main-window.png" alt="ClawBoard 剪贴板历史，使用合成示例内容" width="420">
</p>

## 下载与开始使用

运行打包好的程序无需安装 Python。推荐便携包，也可选择安装向导或完整分享包：

| 交付 | 入口 | 说明 |
|---|---|---|
| 便携包 | [ClawBoard-2.7.0-portable.zip](https://github.com/pay-and-gain/ClawBoard/releases/download/v2.7.0/ClawBoard-2.7.0-portable.zip) | 解压后运行 `ClawBoard.exe`，数据与 exe 同层 |
| 安装包 | [ClawBoard-2.7.0-setup.exe](https://github.com/pay-and-gain/ClawBoard/releases/download/v2.7.0/ClawBoard-2.7.0-setup.exe) | 安装向导、开始菜单快捷方式和卸载入口 |
| 完整分享包 | [ClawBoard-2.7.0-windows.zip](https://github.com/pay-and-gain/ClawBoard/releases/download/v2.7.0/ClawBoard-2.7.0-windows.zip) | 便携程序、安装包、中英文说明与校验清单，一份文件便于转发 |

1. 启动程序，在其他应用复制一段测试文字。
2. 回到要输入的位置，按 **Ctrl+Shift+V** 唤起面板。
3. 选择历史条目，按 **Enter** 或单击条目。若提示已复制但无法自动粘贴，在目标输入框手动按 **Ctrl+V**。

关闭按钮默认隐藏到托盘；退出请用 **Ctrl+Q** 或托盘菜单的“退出”。更多操作见[新手指南](docs/getting-started.md)。

## 可以做什么

- **找回与整理**：记录文字、图片、文件路径，去重、收藏，按关键词、来源、类型或时间筛选；支持中文拼音搜索。
- **重复使用**：常用语分组，键盘选择和前十项快捷粘贴；可选的触发词展开有下述布局限制。
- **处理内容**：文本编码、JSON、大小写和行处理等变换；选中内容可导出为 TXT、CSV、JSON 或 Markdown。
- **适应桌面**：亮暗主题、用户缩放、折叠和靠边隐藏。主面板会在跨屏稳定落位后适应屏幕 DPI。

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/search-highlight.png" alt="搜索筛选合成剪贴板条目" width="420">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/phrases.png" alt="按分组管理常用语的界面" width="420">
</p>

截图使用示例数据。搜索写法包括 `app:chrome`、`type:url`、`is:fav`、`tag:email`；可组合关键词或用 `-关键词` 排除。拼音搜索不展开所有多音字读法。

## 数据、备份与升级

数据位置取决于程序所在目录是否可写：

| 运行位置 | 默认数据位置 |
|---|---|
| 可写目录中的便携 exe | **exe 同层**的 `ClawBoard数据.json`，图片在同层 `images/` |
| exe 所在目录不可写，例如普通权限下的 Program Files | `%APPDATA%\ClawBoard\` |
| 从源码运行 | 源码根目录 |

**在托盘菜单“关于”中确认实际数据文件路径。** 升级或搬迁前先退出程序，备份 `ClawBoard数据.json` 和整个 `images/`，已有 `.bak` 文件也可一起保留。便携升级只替换 exe，数据与 exe 继续同层；不要把新 exe 单独放进子目录。详细步骤见[备份与升级](docs/getting-started.md#备份升级与迁移)。

便携运行仍会生成数据和日志。可选的“开机自启”会写入当前用户的注册表 Run 项；安装版还会创建安装登记及快捷方式，因此不承诺“零注册表写入”或“无残留”。

## 隐私与使用边界

- **数据未加密**：历史与设置存为 JSON，图片存为 PNG。显示打码不等于磁盘加密，备份也应妥善保护。
- **过滤有边界**：支持剪贴板私密标记、应用/标题忽略名单、敏感显示遮罩和可选的敏感内容跳过；识别规则无法保证拦截所有机密内容。
- **联网范围**：采集、搜索和变换在本机处理；默认更新检查会访问 GitHub 发布信息，可在设置关闭。更新功能只提示并打开下载页，不自动下载安装或替换程序。
- **触发词仅支持独立标准 US 键盘布局**：微软拼音的“中”和“英”模式、US International、Dvorak 及未知布局都暂停展开。空格或支持的标点可触发；Enter、Tab、点击、滚轮和继续输入会取消排队替换。中文输入时仍可正常复制、搜索和点击常用语粘贴。
- **管理员目标需要手动粘贴**：普通权限进程不会向更高权限窗口自动发键；权限无法确认时也停止自动发键。看到“已复制”后，在目标窗口按 Ctrl+V。自动输入不能保证任意应用都接受内容。
- **记录不是完整审计**：程序关闭或连续快速复制时，无法保证保留每一个中间状态；启动补记只读取当时可取得的当前剪贴板。

已实测浏览器粘贴、中文候选保护、独立 US 触发、管理员手动粘贴、混合 DPI 主面板、真实托盘打开和 Explorer 重启恢复；独立测试目录的静默安装/保留数据卸载、GUI 保存后新进程重载也已通过。5,000 条合成记录完成 15 分钟搜索/滚动负载；交互式安装向导及多日运行未测，完整范围见 [Windows 验证记录](docs/WINDOWS_VALIDATION.md)。

## 常用快捷键

除全局唤起键外，下列按键在 ClawBoard 面板内使用：

| 按键 | 操作 |
|---|---|
| `Ctrl+Shift+V` | 全局显示/隐藏；设置中可改为 `Alt+V` 或 `Ctrl+Alt+V` |
| `Ctrl+F` | 搜索 |
| `↑` / `↓`、`Enter` | 选择、粘贴 |
| `Ctrl+1`…`Ctrl+9`、`Ctrl+0` | 粘贴当前列表第 1–10 项 |
| `Ctrl+Shift+Enter` | 纯文本粘贴 |
| `Ctrl+T` / `Ctrl+E` | 文本变换 / 导出 |
| `Ctrl+Shift+P` | 命令面板 |
| `Ctrl+=` / `Ctrl+-` | 调整用户缩放档位 |
| `Esc` / `Ctrl+Q` | 隐藏 / 退出 |

## 从源码运行

```powershell
git clone https://github.com/pay-and-gain/ClawBoard.git
cd ClawBoard
python ClawBoard.py
```

需要 Windows 10/11、Python 3.10+，安装 Python 时包含 Tcl/Tk。**产品运行时只用标准库，无需 pip 安装依赖。** 若只是使用正式版，请使用上方打包下载。

开发构建使用额外工具 PyInstaller，它不属于产品运行依赖：

```powershell
python -m pip install pyinstaller
python -m PyInstaller packaging/ClawBoard.spec --noconfirm
```

输出为 `dist/ClawBoard.exe`；安装包脚本见 [`packaging/`](packaging/)。另有 [C/Win32 实现](ClawBoardC/)，功能范围更小，兼容共享 JSON 格式；请勿让两个实例同时写同一份数据。

## 开发与文档

```powershell
python tests/_t44.py
python tests/test_core.py
```

真实桌面测试会改动系统剪贴板或激活测试窗口，应按验证文档独立执行。构造 App 的测试必须先指定临时数据/日志路径，再启用 `NO_SAVE`，不能拿真实历史作为测试数据。

- [新手指南](docs/getting-started.md) · [English guide](docs/getting-started.en.md)
- [当前架构与维护约定](docs/REFACTOR.md)
- [Windows 验证与尚未完成的场景](docs/WINDOWS_VALIDATION.md)
- [项目审阅与性能对照](docs/PROJECT_REVIEW.md)
- [重构前后对照](docs/PREVIEW_COMPARISON.md)
- [更新记录](CHANGELOG.md) · [MIT 许可](LICENSE)
