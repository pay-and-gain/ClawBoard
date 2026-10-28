# ClawBoard

**简体中文** | [English](README.en.md)

让复制过的内容，随时找得到、用得上。ClawBoard 是 Windows 上的剪贴板历史与常用语面板：热键唤起，搜索，选择后粘贴。

[下载 v4.0.0](https://github.com/pay-and-gain/ClawBoard/releases/tag/v4.0.0) · [三分钟上手](docs/getting-started.md) · [界面与功能](https://pay-and-gain.github.io/ClawBoard/) · [更新记录](CHANGELOG.md)

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-main.png" alt="ClawBoard v4 快速面板，使用合成示例资料" width="420">
</p>

## 下载与开始

打包版无需安装 Python。推荐便携包：完整解压到可写文件夹，运行 `ClawBoard.exe`。

| 下载 | 适合什么情况 |
|---|---|
| [ClawBoard-4.0.0-portable.zip](https://github.com/pay-and-gain/ClawBoard/releases/download/v4.0.0/ClawBoard-4.0.0-portable.zip) | 解压即用，资料与程序同层 |
| [ClawBoard-4.0.0-setup.exe](https://github.com/pay-and-gain/ClawBoard/releases/download/v4.0.0/ClawBoard-4.0.0-setup.exe) | 使用安装向导、开始菜单和卸载入口 |
| [ClawBoard-4.0.0-windows.zip](https://github.com/pay-and-gain/ClawBoard/releases/download/v4.0.0/ClawBoard-4.0.0-windows.zip) | 便携版、安装包、说明与校验清单，便于转发 |

[发布附件 SHA256 清单](https://github.com/pay-and-gain/ClawBoard/releases/download/v4.0.0/SHA256SUMS.txt)

1. 在其他应用复制一段文字。
2. 回到输入位置，按 **Ctrl+Shift+V** 唤起面板。
3. 搜索并选择记录，按 **Enter** 或单击粘贴。若目标拒绝自动输入，在目标框手动按 **Ctrl+V**。

关闭按钮默认隐藏到托盘；**Ctrl+Q** 或托盘“退出”才是正常退出。

## 日常轻用，需要时再展开

- **找回内容**：文字、图片和文件路径历史；关键词、拼音、类型、来源、时间及收藏筛选。
- **重复使用**：常用语分组、前十项快捷粘贴；可选触发词有下述输入法限制。
- **看清再处理**：按需工作台、完整预览、拆词、文本变换与 TXT/CSV/JSON/Markdown 导出。低频工具收在“更多”中，快捷键继续可用。
- **操作始终可达**：纸感爪印界面、亮暗主题；小窗口的保存、确定等主要动作放在顶部，内容单独滚动。来源和大小默认隐藏，可在设置开启。
- **资料有去有回**：完整备份与恢复、挑选内容合并导入、误删回收站，统一从“设置 → 数据”进入。

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-search.png" alt="用搜索与筛选找回合成记录" width="420">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-phrases.png" alt="分组管理常用语的实际界面" width="420">
</p>

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-workbench.png" alt="按需工作台的列表与完整预览" width="740">
</p>

截图均使用合成资料。工作台按 **Ctrl+Shift+W** 打开，用于搜索、查看和定位回快速面板，不另行自动粘贴。

## 三种资料操作，各有用途

| 想做什么 | 使用哪个入口 | 结果 |
|---|---|---|
| 留一份完整副本，或回到某份库 | 完整备份与恢复 | 包含历史、常用语、回收站、设置和引用图片；恢复先预览、先备份当前库 |
| 从旧资料中挑一些加入当前库 | 合并导入资料 | 先选择和预览；重复跳过，同名分组另建，冲突触发词停用；保留当前设置与资料 |
| 找回刚刚误删的内容 | 回收站 | 手动删除最多保留30天、5000条；满时拒绝新删除，自动历史裁剪不进入回收站 |

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-data.png" alt="设置中的资料管理入口" width="420">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-import.png" alt="合并导入前查看候选记录、重复与冲突" width="420">
</p>

普通 JSON 导出不含图片正文。导入时缺图条目不可选，历史容量不足则取消本次导入；程序不会为此删除旧记录或修改容量设置。外部文件记录只保存路径，不复制原文件正文。详见[合并导入](docs/merge-import.md)、[完整备份](docs/backup-and-restore.md)与[回收站](docs/recycle-bin.md)。

## 数据与使用边界

**便携资料跟着 exe 走。** 可写目录中，`ClawBoard数据.json` 和 `images/` 与 `ClawBoard.exe` 同层；目录不可写时回退到 `%APPDATA%\ClawBoard`。在托盘“关于”查看实际位置。升级前正常退出并完整备份，只替换 exe，保留现有资料目录。

**资料未加密。** JSON、图片、导出和备份保存原文，显示遮罩不等于加密。私密标记、忽略名单和敏感识别都有边界。采集、搜索与变换在本机进行；默认更新检查访问 GitHub，可关闭，只提示并打开下载页。

**自动输入有边界。** 管理员或无法确认权限的目标需要手动 Ctrl+V。触发词仅在独立标准 US 键盘布局展开；微软拼音的“中”“英”模式及其他/未知布局暂停展开，中文复制、搜索和点击常用语仍可使用。程序关闭或快速连续复制时，不保证留住每一个中间状态。

更多操作、快捷键和故障处理见[新手指南](docs/getting-started.md)。本程序不要求账号；可选开机自启和安装向导会写入对应系统登记。

## 从源码运行与开发

Windows 10/11，Python 3.10+，安装 Python 时包含 Tcl/Tk。运行时仅使用 Python 标准库、tkinter 与 ctypes/Win32，无需 pip 依赖；Python 与较精简的 [C 版](ClawBoardC/)共用兼容 JSON 格式。

```powershell
git clone --branch v4.0.0 https://github.com/pay-and-gain/ClawBoard.git
cd ClawBoard
python ClawBoard.py
python tests/_t44.py
```

构建工具与安装脚本见 [packaging/](packaging/)。真实桌面测试单独运行；构造 App 前须指定临时资料路径并启用 `NO_SAVE`，真实历史不能用作测试库。

[维护接续与归档索引](docs/maintenance/HANDOFF.md) · [当前架构](docs/REFACTOR.md) · [Windows 验证范围](docs/WINDOWS_VALIDATION.md) · [MIT 许可](LICENSE)
