# ClawBoard v4.0.0

更清楚的操作入口，以及从旧资料中挑选内容加入当前库的合并导入。

## 主要变化

- **关键操作固定在顶部**：保存、确定、取消等主要动作与滚动正文分开，改善小窗口、长内容和高缩放下的可达性；按钮继续支持键盘聚焦。
- **保留功能，精简入口**：日常面板保留常用动作，低频工具集中到“更多”，已有快捷键继续可用；按需工作台沿用同一套纸感爪印界面。
- **内容合并导入**：从ClawBoard JSON导出或完整备份ZIP预览并挑选历史、常用语。重复跳过，同名分组另建，冲突触发词停用；保留当前设置、回收站及已有资料。
- **导入先保护原库**：正常保存退出后，辅助进程重新读取最终当前库，先完整备份，再执行合并；保留预览期间新增的历史。容量不足取消，不自动裁剪或提高容量。
- **图片与隐私边界**：ZIP图片经校验并换新名称，避免覆盖已有图片；JSON缺图项不可导入。新增条目遵循当前敏感遮罩，不沿用来源的明文显示标记。
- **说明与截图重写**：新的中英文首页、快速指南、合成资料界面截图和维护归档索引；明确区分完整恢复、合并导入与误删恢复。

## 下载

- `ClawBoard-4.0.0-portable.zip`：便携程序、中英文说明、构建信息和包内校验。
- `ClawBoard-4.0.0-setup.exe`：Windows安装向导。
- `ClawBoard-4.0.0-windows.zip`：便携程序、安装包、说明和校验清单。
- `ClawBoard-4.0.0-project-archive.zip`：脱敏源码、项目文档和最终验收记录归档，不含真实资料、私有日志或个人备份。
- `SHA256SUMS.txt`：发布附件摘要。

## 升级与使用

升级前正常退出并创建完整备份；便携升级只替换原位置的exe，保留同层 `ClawBoard数据.json` 与 `images/`。数据schema保持3，Python标准库、tkinter与ctypes/Win32运行边界不变。

合并导入从“设置 → 数据”打开。普通JSON不含图片正文；携带图片请使用完整备份ZIP。外部文件仍只保存路径。导入与恢复会正常保存退出，完成后重新打开程序。

资料和备份未加密。管理员或未知权限目标需要手动Ctrl+V；触发词仅支持独立标准US布局，中文输入法包括其英文模式仍暂停自动展开。采集、搜索与变换在本机进行；更新检查可关闭，只提示并打开下载页。

## 验证范围

程序构建源码为 `e05621b`，exe SHA256为 `8238e35141de5d471260c5160d02464a1774ab22d544c48d00ac83f730d2d3bc`。652项服务回归638通过、14平台或权限跳过，Windows/Ubuntu云端CI通过；本机文件剪贴板专项及输出文件核对、顶部动作18组、工具栏60组、三个正式冻结NO_SAVE窗口检查均通过。

正式原安装器已在独立目录完成安装、合成资料两次保存重载、NO_SAVE启动和保留资料的静默卸载。安装后程序检查总耗时7.51秒、exit0，合成资料、真实资料、自启动和快捷方式基线保持；不将该耗时当作冷启动指标。

便携原位更新另经完整备份后验证，替换阶段原JSON与图片字节及元数据保持，日常程序已恢复运行。

完整过程见[Windows验证记录](https://github.com/pay-and-gain/ClawBoard/blob/main/docs/WINDOWS_VALIDATION.md)和[交付索引](https://github.com/pay-and-gain/ClawBoard/blob/main/docs/maintenance/V4_DELIVERY.md)。源码归档中的程序文件与构建源码一致，并补齐后续验收文档；程序附件没有因文档更新而重建。尚未覆盖物理键盘前台完整交互、完整无障碍、多日运行、Windows C构建、安装向导逐页交互或明确删除资料的卸载流程；不以截图或单项检查代替这些结果。正式公开状态以[Release页面](https://github.com/pay-and-gain/ClawBoard/releases/tag/v4.0.0)为准。

[使用指南](https://github.com/pay-and-gain/ClawBoard/blob/v4.0.0/docs/getting-started.md) · [合并导入说明](https://github.com/pay-and-gain/ClawBoard/blob/v4.0.0/docs/merge-import.md) · [维护与归档](https://github.com/pay-and-gain/ClawBoard/blob/main/docs/maintenance/HANDOFF.md)

## English

v4 keeps primary dialog actions at the top, groups less frequent tools under More, and adds previewed merge import from ClawBoard JSON exports or complete backup ZIPs. Duplicates are skipped, conflicting group names become separate groups, and occupied triggers are disabled. Current content, settings and the recycle bin stay intact.

The helper waits for the original process to save and exit, re-reads the final library, makes a complete safety backup and applies the merge with rollback protection. Missing image bodies or insufficient capacity do not silently discard existing content. Imported items follow the current masking preferences.

Quit and back up before upgrading. Keep the portable exe beside the existing JSON and images. Stored data is unencrypted. Keyboard-layout restrictions and manual paste fallback for elevated targets remain. The English guide explains the current Chinese application labels.

The formal build passed Windows and Ubuntu CI, the isolated file-clipboard checks, native layout checks, and the three NO_SAVE frozen-window checks. The original installer completed an isolated-directory install and uninstall cycle, preserving synthetic data and the existing user environment. The project archive preserves the verified program sources and includes the final documentation and validation records; executable assets were not rebuilt for documentation updates. Physical foreground-keyboard coverage, full accessibility, multi-day use and the Windows C build remain outside this validation scope.

[English guide](https://github.com/pay-and-gain/ClawBoard/blob/v4.0.0/docs/getting-started.en.md)
