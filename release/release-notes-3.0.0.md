# ClawBoard v3.0.0

纸感界面、按需工作台，以及从完整备份到误删恢复的数据保护。

## 主要变化

- **统一界面与图标**：纸感爪印主视觉、原创应用和托盘图标、亮暗主题及可聚焦按钮；保留紧凑面板，来源与条目大小默认隐藏，可独立开启。
- **更顺手的小窗口**：短搜索、相邻的删除/拆词按钮、固定底部操作区；拆词与导出正文可滚动，避免按钮被内容挤出。粘贴反馈改为一次短亮。
- **可选只读工作台**：面板内按 `Ctrl+Shift+W`，在更大的窗口搜索、分类、查看完整预览并定位回快速面板。工作台不新增自动粘贴行为；搜索和选择仅保证同一进程内关闭重开保留。
- **完整备份与恢复**：设置 → 数据中将历史、常用语、回收站、设置和引用图片打成独立 ZIP；恢复前先预览，再保留当前库的完整安全备份。辅助进程等待原程序正常退出后恢复，失败回退和持久事务保护原数据。
- **误删回收站**：手动删除的历史、常用语及分组内容最多保留 30 天，可预览并恢复。最多 5000 条，满时拒绝新删除并保留源内容，不提前丢弃未到期内容。自动超出历史条数的裁剪不进入回收站。
- **图片与恢复边界**：回收站图片纳入完整备份；永久删除或到期清理确认保存成功后才回收图片。恢复保留未知字段，检查条目标识和触发词冲突；常用语按稳定分组标识恢复，不误并入同名分组。
- **跨屏与关闭修复**：设置、备份、回收站窗口按自身 DPI 调整；设置保留输入草稿、光标和分区。细滚动条跟随实际宽度，快速关闭设置/导出时取消延迟聚焦和布局任务。

运行时继续使用 Python 标准库、tkinter 与 ctypes/Win32，**零 pip 运行依赖**；共享 JSON **schema 仍为 3**，不改变既有字段语义。C 版功能范围更小，本次不提供新的 C 版二进制。

## 下载文件

- `ClawBoard-3.0.0-portable.zip`：便携程序与中英文说明。
- `ClawBoard-3.0.0-setup.exe`：Windows 安装向导。
- `ClawBoard-3.0.0-windows.zip`：便携程序、安装包、说明和校验清单，便于完整转发。
- `SHA256SUMS.txt`：发布附件校验值；ZIP 内另有包内文件校验清单。

## 升级与数据

1. 若当前版本已有“设置 → 数据 → 完整备份与恢复”，先创建完整 ZIP；没有此入口时，先正常退出并手动备份 `ClawBoard数据.json` 与整个 `images/`。
2. 便携升级前正常退出程序，只替换原位置的 exe，继续让 exe、数据 JSON 与 `images/` 同层。不要把新 exe 单独放进子目录。
3. 启动后核对原有历史和常用语。卸载默认保留数据，静默卸载同样保留数据。

普通 JSON 导出保留原记录格式，**不能用于整库恢复**。文件条目只保存路径，完整备份不包含这些路径指向的外部文件正文。回收站及备份均未加密；永久清理回收站不会删除另外保存的旧备份。

## 验证范围

本轮源码已有 550 项服务回归结果：536 通过、14 项按平台或权限跳过。临时数据验证覆盖保存后新进程重载、回收站恢复、包含回收站图片的完整备份、真实临时 App 接线、文件剪贴板和双屏布局；冻结候选的备份/回收站保护入口也有独立烟测。

这些结果不等于所有应用的输入兼容、完整无障碍、物理键盘前台验收、Windows C 构建或多日运行测试。正式构建与安装包复验范围以 [Windows 验证记录](https://github.com/pay-and-gain/ClawBoard/blob/v3.0.0/docs/WINDOWS_VALIDATION.md) 为准。触发词仍只支持独立标准 US 键盘布局；中文输入法和更高或未知权限目标继续安全降级。

[新手指南](https://github.com/pay-and-gain/ClawBoard/blob/v3.0.0/docs/getting-started.md) · [完整备份说明](https://github.com/pay-and-gain/ClawBoard/blob/v3.0.0/docs/backup-and-restore.md) · [回收站说明](https://github.com/pay-and-gain/ClawBoard/blob/v3.0.0/docs/recycle-bin.md)

## English

v3 adds a paper-and-paw interface, compact actions, an optional read-only workbench (`Ctrl+Shift+W`), complete library backups and a recycle bin. Manual deletions can be restored for up to 30 days; its 5,000-entry limit rejects new deletions instead of evicting unexpired records. Automatic history-limit pruning does not enter the bin.

Complete backup ZIPs include history, phrases, the recycle bin, settings and referenced images. Restore previews the package and retains a safety backup first. Ordinary JSON exports cannot restore the full library, and external files remain path references only. Storage and backups are unencrypted.

The runtime remains standard-library-only with tkinter and ctypes/Win32; shared JSON schema stays at 3. Quit and back up before upgrading, keeping the portable exe beside its existing JSON and images. Input safeguards, keyboard-layout restrictions and manual paste fallback for elevated targets remain in place.
