# ClawBoard v4 使用指南

**简体中文** | [English](getting-started.en.md) · [返回项目](../README.md)

先用一段无敏感信息的示例文字，完成“复制 → 找回 → 粘贴”。更多功能可以需要时再打开。

## 1. 下载和启动

打开 [v4.0.0 发布页](https://github.com/pay-and-gain/ClawBoard/releases/tag/v4.0.0)，任选一种方式；打包版均无需安装 Python。

- [便携包](https://github.com/pay-and-gain/ClawBoard/releases/download/v4.0.0/ClawBoard-4.0.0-portable.zip)：完整解压到可写文件夹，运行 `ClawBoard.exe`。已有资料应与 exe 同层。
- [安装包](https://github.com/pay-and-gain/ClawBoard/releases/download/v4.0.0/ClawBoard-4.0.0-setup.exe)：按安装向导操作，桌面快捷方式可选。
- [完整分享包](https://github.com/pay-and-gain/ClawBoard/releases/download/v4.0.0/ClawBoard-4.0.0-windows.zip)：便携程序、安装包、说明和校验清单，便于转发。

程序启动后通常在托盘后台运行。按 **Ctrl+Shift+V** 显示面板，再按一次隐藏；如果看不到图标，展开任务栏右侧的隐藏图标。

## 2. 完成一次粘贴

1. 在其他应用复制“ClawBoard 示例文字”。
2. 回到要输入的位置，按 **Ctrl+Shift+V**。
3. 在面板中搜索“示例”，单击记录或按 **Enter**。

如果提示已复制但目标没有接收，在目标框按 **Ctrl+V**。管理员窗口需要这一步；不必为了粘贴而让整个程序以管理员运行。

![快速面板](https://pay-and-gain.github.io/ClawBoard/images/v4-main.png)

## 3. 搜索、收藏与常用语

**历史**用于找回复制记录，**常用语**用于反复使用的内容。常用语可新建分组、添加条目并编辑名称和内容。删除、拆词等常用动作在面板可见，低频处理从“更多”或快捷键打开。

搜索框可以直接输入中文、关键词、拼音或首字母；可视筛选提供类型、时间和收藏。高级写法如 `type:url`、`is:fav`、`app:chrome`，可与普通关键词组合。拼音不展开所有多音字读法。

<p>
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-search.png" alt="搜索与筛选示例" width="420">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-phrases.png" alt="常用语分组示例" width="420">
</p>

## 4. 看清内容，再处理

- **工作台**：面板内按 **Ctrl+Shift+W**，在较宽窗口中搜索、查看完整内容，再点“在快速面板定位”。工作台不另行自动粘贴。
- **拆词**：选中文字后点“拆”，选择需要的部分；关键操作固定在顶部。
- **文本变换**：按 **Ctrl+T**，选择变换并检查结果后使用。原记录不会因预览变换而被覆盖。
- **导出**：按 **Ctrl+E**，将所选记录导出成 TXT、CSV、JSON 或 Markdown。设置的数据页还提供全部内容 JSON 导出。
- **命令面板**：按 **Ctrl+Shift+P**，搜索操作名称。它与鼠标入口共用现有能力。

来源和条目大小默认隐藏，可在“设置 → 外观”开启；详细信息也可在工作台按需展开。小窗口中主要确认/保存操作放在顶部，正文单独滚动。

![按需工作台](https://pay-and-gain.github.io/ClawBoard/images/v4-workbench.png)

<details>
<summary>查看拆词、变换、导出与命令面板截图</summary>

<p>
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-split.png" alt="拆词窗口及顶部操作" width="420">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-transform.png" alt="文本变换与结果预览" width="420">
</p>
<p>
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-export.png" alt="导出格式与顶部确认操作" width="420">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-palette.png" alt="按名称搜索操作的命令面板" width="420">
</p>

</details>

## 5. 备份、导入和误删恢复

打开 **设置 → 数据**，按目的选择：

| 目的 | 入口与操作 |
|---|---|
| 保存完整副本 | **完整备份与恢复 → 创建完整备份**。包含历史、常用语、回收站、设置与引用图片，等待完成后保存ZIP |
| 回到一份完整库 | 在同一窗口选择备份并预览，再确认恢复。会替换当前库和设置，先保留原库备份，然后重启 |
| 从旧资料挑一些加入 | **合并导入资料**：选JSON或ZIP、检查、勾选、确认。重复跳过、同名分组另建、冲突触发词停用；当前库与设置保留 |
| 找回误删记录 | **回收站**：预览、选择并恢复。手动删除保留最多30天、5000条；自动历史裁剪不进入回收站 |

导入和完整恢复会让程序正常保存退出，由辅助进程执行后重新打开；预览期间后来新增的历史也会保留在合并结果中。源文件变化、保存问题或导入容量不足时取消，不自动删除旧记录或提高容量。

**普通JSON没有图片正文**，缺图条目不能合并导入；携带图片请使用完整备份ZIP。文件记录仍只是路径，导出或备份不会复制原文件正文。永久清空回收站与清理资料库需再次确认，另存的备份可能仍含旧记录。

<p>
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-data.png" alt="数据管理入口" width="420">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-import.png" alt="合并导入预览和选择" width="420">
</p>

<details>
<summary>查看备份与回收站截图及详细说明</summary>

<p>
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-backup.png" alt="完整备份与恢复预览" width="420">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-trash.png" alt="回收站内容与恢复操作" width="420">
</p>

[完整备份说明](backup-and-restore.md) · [合并导入说明](merge-import.md) · [回收站说明](recycle-bin.md)

</details>

## 6. 资料位置与升级

在托盘“关于”核对实际资料位置：

| 情况 | 资料位置 |
|---|---|
| exe所在目录可写 | exe同层的 `ClawBoard数据.json` 与 `images/` |
| exe所在目录不可写 | `%APPDATA%\ClawBoard\` |
| 从源码运行 | 项目根目录 |

1. 有完整备份入口时先创建ZIP；旧版也可在正常退出后手动备份JSON和整个图片文件夹。
2. 用 **Ctrl+Q** 或托盘“退出”正常关闭。
3. 便携升级只替换原位置的exe，继续保留同层JSON与图片。不要把新exe单独放进子文件夹。
4. 换电脑时，在目标程序退出状态复制完整资料，再启动核对；也可用完整备份恢复。

卸载默认保留资料，静默卸载也保留。运行时仍会生成资料和日志；可选开机自启会写入当前用户的启动登记，安装版还有安装登记与快捷方式。Python与C版能力不同；切换实现前退出并备份，不同时写同一份库。

## 7. 隐私与输入限制

- JSON、图片、导出与备份**未加密**，显示遮罩只影响界面。忽略名单、私密标记和敏感识别不能保证拦截所有机密内容。
- “敏感显示打码”和“识别后不保存”是两种设置。需要停止采集时关闭监听；规则可能漏检，超长文字的邮箱识别也有长度限制。
- 采集、搜索和变换在本机进行。默认更新检查访问GitHub，可在设置关闭；只通知并打开下载页。
- 触发词只在**独立标准US键盘布局**展开。微软拼音切到“英”仍属于输入法，不自动展开；中文复制、搜索和点击常用语继续可用。
- 管理员目标或无法确认权限的窗口不自动发键，复制后手动Ctrl+V。目标应用也可能拒绝焦点或输入。
- 程序关闭或快速连续复制时，不能保证收录每一个中间状态。

## 8. 常见问题与快捷键

**热键无反应**：从托盘打开设置，改用 `Alt+V` 或 `Ctrl+Alt+V`，以实际注册结果和提示为准。

**面板找不到**：使用托盘“面板找不到了？重置位置”。来源/大小开关和用户缩放均可在设置中调整。

**首尾空白变化**：默认粘贴时裁剪首尾空白，内部缩进保留；需要完整边缘空白时关闭该设置。

只有显示/隐藏键是全局热键；以下其他按键在ClawBoard面板内使用。

| 快捷键 | 操作 |
|---|---|
| Ctrl+Shift+V | 显示/隐藏 |
| Ctrl+F | 搜索 |
| ↑ / ↓、Enter | 选择、粘贴 |
| Ctrl+1…9、Ctrl+0 | 粘贴列表第1–10项 |
| Ctrl+Shift+Enter | 纯文本粘贴 |
| Ctrl+T / Ctrl+E | 文本变换 / 导出 |
| Ctrl+Shift+P / Ctrl+Shift+W | 命令面板 / 工作台 |
| Ctrl+= / Ctrl+- | 用户缩放 |
| Esc / Ctrl+Q | 隐藏 / 正常退出 |

截图使用合成资料。具体回归、平台跳过和原生验收边界见[Windows验证记录](WINDOWS_VALIDATION.md)；不以截图代替完整交互或长期使用验证。开发接续见[维护与归档索引](maintenance/HANDOFF.md)。
