# ClawBoard v2.7.0

服务重构与 Windows 输入保护。保留 Python 标准库、tkinter、ctypes/Win32 和共享 JSON schema 3；不需要安装 Python 即可使用打包程序。

## 下载 / Downloads

- **ClawBoard-2.7.0-portable.zip**：便携版，解压后运行 `ClawBoard.exe`。
- **ClawBoard-2.7.0-setup.exe**：安装向导与卸载入口。
- **ClawBoard-2.7.0-windows.zip**：完整分享包，包含便携程序、安装包、中英文说明、构建信息和校验清单；不含用户数据。
- **SHA256SUMS.txt**：发布文件校验值。

## 本次改进

- 查询、保存、后台任务和 Windows 接入拆为独立服务，按需拼音查询、可见行复用、后台图片处理和串行保存减少主线程工作。
- 剪贴板事务/自写序列核对；普通粘贴与触发词共用有界串行队列，并复核目标、焦点、序列和取消状态。
- 触发词仅允许独立标准 US 布局，中文输入法和未知布局不退格、不替换，避免输入法候选提交后误删正文。
- 普通权限向更高或未知权限目标自动输入时，保留已复制内容并提示手动 Ctrl+V。
- 主面板跨屏后同步字体、布局及最小尺寸，保留用户缩放档位、搜索和列表状态。
- 托盘资源与恢复广播修复；卸载默认保留数据，仅清除属于本安装的自启动项，支持 `/NOICONS`。
- 中英文说明、项目首页和真实界面截图更新；Windows exe 的文件属性版本由 `APP_VER` 自动生成。

## 升级与边界

先退出程序，备份 `ClawBoard数据.json` 和整个 `images/`。便携升级替换 exe 即可，数据与 exe 继续同层。不要把自己的历史、图片或私密备份放进分享包。

触发词不支持微软拼音的“中”或“英”模式、US International、Dvorak 及未知布局；普通复制、搜索和常用语点击粘贴仍可使用。管理员目标需要手动 Ctrl+V。磁盘数据未加密，显示遮罩不能代替文件保护。

原生剪贴板、浏览器粘贴、中文候选保护、独立 US 触发、多屏主面板、管理员降级及静默安装/保留数据卸载已验证。完整证据、持续运行样本和剩余限制见 [Windows 验证记录](https://github.com/pay-and-gain/ClawBoard/blob/main/docs/WINDOWS_VALIDATION.md)。短时负载不代表多日运行保证，独立弹窗不能套用主面板的跨屏结论；本次未发布新的 C 版二进制。

## English

v2.7.0 refactors query, storage, background tasks and Windows integration while retaining the standard-library runtime and schema 3 compatibility. It adds conservative IME trigger protection, safe manual-paste fallback for elevated targets, mixed-DPI main-panel refresh and tray recovery. Uninstall keeps data by default and preserves startup entries belonging to other portable copies.

Exit and back up the JSON file and entire image folder before upgrading. Keep portable data beside the exe. Triggers require a separate standard US keyboard; Microsoft Pinyin in either mode and unknown layouts are skipped. Data is stored unencrypted. The complete sharing ZIP contains no user history or backups. See the validation record for measured scope and remaining limitations.
