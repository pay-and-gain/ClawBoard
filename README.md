# ClawBoard

**简体中文** | [English](README.en.md)

Windows 剪贴板历史与常用语面板。找回复制过的文字、截图和文件路径，搜索后粘贴到正在编辑的位置，也能把重复使用的内容存成常用语。

[下载 v3.0.0](https://github.com/pay-and-gain/ClawBoard/releases/tag/v3.0.0) · [新手指南](docs/getting-started.md) · [更新记录](CHANGELOG.md) · [Windows 验证记录](docs/WINDOWS_VALIDATION.md)

> **v3.0.0 带来纸感爪印界面、可选工作台、完整备份恢复和误删回收站。** 保留 tkinter、零 pip 运行依赖及共享 JSON schema 3。升级前完整备份数据；旧 v2.6.1 缺少后续输入保护，仍使用旧版时请关闭触发词。

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/main-window.png" alt="ClawBoard 剪贴板历史，使用合成示例内容" width="420">
</p>

## 下载与开始使用

运行打包好的程序无需安装 Python。推荐便携包，也可选择安装向导或完整分享包：

| 交付 | 入口 | 说明 |
|---|---|---|
| 便携包 | [ClawBoard-3.0.0-portable.zip](https://github.com/pay-and-gain/ClawBoard/releases/download/v3.0.0/ClawBoard-3.0.0-portable.zip) | 解压后运行 `ClawBoard.exe`，数据与 exe 同层 |
| 安装包 | [ClawBoard-3.0.0-setup.exe](https://github.com/pay-and-gain/ClawBoard/releases/download/v3.0.0/ClawBoard-3.0.0-setup.exe) | 安装向导、开始菜单快捷方式和卸载入口 |
| 完整分享包 | [ClawBoard-3.0.0-windows.zip](https://github.com/pay-and-gain/ClawBoard/releases/download/v3.0.0/ClawBoard-3.0.0-windows.zip) | 便携程序、安装包、中英文说明与校验清单，一份文件便于转发 |

1. 启动程序，在其他应用复制一段测试文字。
2. 回到要输入的位置，按 **Ctrl+Shift+V** 唤起面板。
3. 选择历史条目，按 **Enter** 或单击条目。若提示已复制但无法自动粘贴，在目标输入框手动按 **Ctrl+V**。

关闭按钮默认隐藏到托盘；退出请用 **Ctrl+Q** 或托盘菜单的“退出”。更多操作见[新手指南](docs/getting-started.md)。

## 可以做什么

- **找回与整理**：记录文字、图片、文件路径，去重、收藏，按关键词、来源、类型或时间筛选；支持中文拼音搜索。
- **重复使用**：常用语分组，键盘选择和前十项快捷粘贴；可选的触发词展开有下述布局限制。
- **处理内容**：文本编码、JSON、大小写和行处理等变换；选中内容可导出为 TXT、CSV、JSON 或 Markdown。
- **紧凑而清楚**：纸感爪印视觉与原创图标、亮暗主题、短搜索和单次反馈；来源、条目大小默认隐藏，可在设置开启。窄窗先保留操作按钮。
- **按需工作台**：面板内按 `Ctrl+Shift+W`，在更宽的只读界面搜索、分类和查看完整预览，再定位回快速面板；不会另行自动粘贴。
- **完整备份与恢复**：设置 → 数据中将历史、常用语、回收站、设置和图片打成 ZIP，恢复前预览并保留原库。普通 JSON 导出不能替代完整备份。
- **误删恢复**：手动删除内容最多保留 30 天，容量 5000 条；满时拒绝新的删除，保留源内容。自动超出历史条数的裁剪不进回收站。
- **适应桌面**：保留用户缩放、折叠和靠边隐藏；主面板及设置、备份、回收站等窗口按各自屏幕 DPI 调整。

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/search-highlight.png" alt="搜索筛选合成剪贴板条目" width="420">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/phrases.png" alt="按分组管理常用语的界面" width="420">
</p>

截图使用示例数据，部分展示较早版本布局。搜索写法包括 `app:chrome`、`type:url`、`is:fav`、`tag:email`；可组合关键词或用 `-关键词` 排除。拼音搜索不展开所有多音字读法。

## 数据、备份与升级

数据位置取决于程序所在目录是否可写：

| 运行位置 | 默认数据位置 |
|---|---|
| 可写目录中的便携 exe | **exe 同层**的 `ClawBoard数据.json`，图片在同层 `images/` |
| exe 所在目录不可写，例如普通权限下的 Program Files | `%APPDATA%\ClawBoard\` |
| 从源码运行 | 源码根目录 |

**在托盘菜单“关于”中确认实际数据文件路径。** v3 可先在 **设置 → 数据 → 完整备份与恢复** 创建 ZIP；详见[完整备份说明](docs/backup-and-restore.md)与[回收站说明](docs/recycle-bin.md)。手动复制或替换程序前先退出，备份 `ClawBoard数据.json` 和整个 `images/`，已有 `.bak` 文件也可一起保留。便携升级只替换 exe，数据与 exe 继续同层；不要把新 exe 单独放进子目录。详细步骤见[备份与升级](docs/getting-started.md#备份升级与迁移)。

便携运行仍会生成数据和日志。可选的“开机自启”会写入当前用户的注册表 Run 项；安装版还会创建安装登记及快捷方式，因此不承诺“零注册表写入”或“无残留”。

## 隐私与使用边界

- **数据未加密**：历史与设置存为 JSON，图片存为 PNG。显示打码不等于磁盘加密，备份也应妥善保护。
- **过滤有边界**：支持剪贴板私密标记、应用/标题忽略名单、敏感显示遮罩和可选的敏感内容跳过；识别规则无法保证拦截所有机密内容。
- **联网范围**：采集、搜索和变换在本机处理；默认更新检查会访问 GitHub 发布信息，可在设置关闭。更新功能只提示并打开下载页，不自动下载安装或替换程序。
- **触发词仅支持独立标准 US 键盘布局**：微软拼音的“中”和“英”模式、US International、Dvorak 及未知布局都暂停展开。空格或支持的标点可触发；Enter、Tab、点击、滚轮和继续输入会取消排队替换。中文输入时仍可正常复制、搜索和点击常用语粘贴。
- **管理员目标需要手动粘贴**：普通权限进程不会向更高权限窗口自动发键；权限无法确认时也停止自动发键。看到“已复制”后，在目标窗口按 Ctrl+V。自动输入不能保证任意应用都接受内容。
- **记录不是完整审计**：程序关闭或连续快速复制时，无法保证保留每一个中间状态；启动补记只读取当时可取得的当前剪贴板。

本轮源码验收包含 550 项服务回归（536 通过、14 项平台或权限跳过）、临时库新进程重载、真实临时 App、双屏布局及冻结包保护入口。既有输入、托盘与安装验收按各自构建记录保留；回收站默认布局测试不等于物理键盘或完整无障碍验收，Windows C 构建与多日运行未覆盖，详见 [Windows 验证记录](docs/WINDOWS_VALIDATION.md)。

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
| `Ctrl+Shift+W` | 打开只读工作台 |
| `Ctrl+=` / `Ctrl+-` | 调整用户缩放档位 |
| `Esc` / `Ctrl+Q` | 隐藏 / 退出 |

## 从源码运行

```powershell
git clone --branch v3.0.0 https://github.com/pay-and-gain/ClawBoard.git
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
