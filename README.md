# ClawBoard

**简体中文** | [English](README.en.md)

> Windows 悬浮剪贴板 & 常用语面板 —— 零第三方依赖，Python（tkinter + ctypes）与纯 C（Win32）双版本。

挂在屏幕一角的轻量剪贴板历史 + 常用语面板：搜索、文本变换、批量导出、快速粘贴，以及一整套面向隐私的剪贴板处理机制。

<p align="center">
  <img src="docs/images/main-window.png" alt="ClawBoard 主界面" width="260">
</p>

<p align="center">
  <img src="docs/images/settings-general.png" alt="设置 - 基础" width="290">
  <img src="docs/images/settings-advanced.png" alt="设置 - 进阶" width="290">
</p>

## 📥 下载

| 方式 | 文件 | 说明 |
|---|---|---|
| **安装包**（推荐） | `ClawBoard-1.6.4-setup.exe` | 双击安装，自动创建开始菜单与桌面快捷方式，带卸载项 |
| **绿色版** | `ClawBoard-1.6.4-portable.zip` | 解压即用，不写注册表、不留残留 |
| **源码** | `Source code (zip/tar.gz)` | GitHub 在 Release 页自动提供；也可 `git clone` |

👉 全部文件在 [**Releases 页面**](../../releases/latest)。

## ✨ 特性

- **剪贴板历史** —— 自动记录、去重、上限裁剪、收藏；悬停看时间，右键看详情
- **常用语** —— 分组管理、拆词（一段文字批量切成多条）、增删改
- **高级搜索** —— `app:` 来源 / `time:` 时间 / `type:` 类型 / `size:` 大小 / `is:` 状态 / `-` 排除，多词 AND + 高亮
- **27 项文本变换** —— 编解码、大小写、行处理、哈希（MD5/SHA1/SHA256）、JSON 格式化…
- **批量导出** —— TXT / CSV（带 BOM）/ JSON / Markdown
- **快速粘贴** —— `Ctrl+1..9` / `Ctrl+0` 直接粘贴第 1~10 项
- **隐私保护** —— 遵守 Windows「别记录我」标记、程序/标题忽略名单、敏感内容识别与打码
- **好用** —— 靠边隐藏、双击折叠贴右下角、四边四角随意拉伸、界面等比缩放（50%~150%）、自定义背景色、亮/暗主题

## 🚀 快速开始

### 方式一：装安装包
下载 `ClawBoard-1.6.4-setup.exe` 双击，按提示装完即可（Windows 10 / 11）。

### 方式二：绿色版
下载 `ClawBoard-1.6.4-portable.zip`，解压到任意目录，双击 `ClawBoard.exe`。

### 方式三：从源码运行
```bash
git clone https://github.com/pay-and-gain/ClawBoard.git
cd ClawBoard
python ClawBoard.py     # 需要 Python 3 + tkinter（Windows 自带）
```
零 pip 依赖。

### 自己打包
```bash
pip install pyinstaller
pyinstaller packaging/ClawBoard.spec --noconfirm
# 产物在 dist/ClawBoard.exe，数据文件落在 exe 旁边
```
安装包（Inno Setup）与绿色版（zip）的脚本见 [`packaging/`](packaging/)。

### C 版（可选）
[`ClawBoardC/`](ClawBoardC/) 是纯 Win32 + GDI 自绘的 C 实现（约 2500 行，产物 205 KB，内存约 15 MB），
用 `packaging/启动ClawBoard.bat` 同类方式编译（需 MSVC，见 `ClawBoardC/build.bat`）。
两版**共用同一份数据文件**，可互换使用。

## ⌨️ 快捷键

| 按键 | 功能 |
|---|---|
| `Ctrl+Shift+V` | 唤起 / 隐藏面板 |
| `Ctrl+1..9` / `Ctrl+0` | 直接粘贴第 1~10 项 |
| `Ctrl+T` / `Ctrl+E` | 文本变换 / 批量导出 |
| `Ctrl+F` | 聚焦搜索 |
| `Ctrl+=` / `Ctrl+-` | 界面等比缩放 |
| `↑` `↓` / `Enter` | 移动 / 粘贴 |
| `Delete` | 删除选中 |
| `Esc` / `Ctrl+Q` | 隐藏 / 退出 |

## 📖 文档

🌐 **[在线文档](https://pay-and-gain.github.io/ClawBoard/)** —— 网页版，可切换中 / 英文

| 文档 | 内容 |
|---|---|
| [制作思路](docs/制作思路.md) · [English](docs/DESIGN.en.md) | **功能说明 + 使用指南 + 设计思路**：需求来源、方法顺序、技术选型、实现步骤、踩坑、实测数据、FAQ |
| [使用说明](docs/使用说明.md) | 详细操作手册 |
| [架构设计](docs/架构设计.md) | 分层结构、模块划分、依赖方向、调用流程 |
| [需求与进度](docs/需求全景.md) · [PROGRESS](docs/PROGRESS.md) | 需求全景与开发过程记录 |
| [CHANGELOG](CHANGELOG.md) | 逐版本改动记录 |

## 🏗️ 项目结构

```
ClawBoard.py            入口 + re-export 聚合层
clawboard/              Python 包（16 个职责模块，四层架构）
├─ config.py            集中配置 + 数据契约 + AppState
├─ runtime.py           运行时可变全局（NO_SAVE 等）
├─ theme.py             主题配色
├─ classify.py          内容自适应分类
├─ timefmt.py           时间格式化 + 数据迁移
├─ win32.py             Win32 声明 + DPI + 单实例
├─ clipboard.py         剪贴板读写 + 敏感识别
├─ hotkey.py            热键 + 托盘（隐藏消息窗口）
├─ widgets.py           通用控件 + 布局/事件 helper
├─ vlist.py             虚拟滚动列表
├─ dialogs.py           设置/变换/导出弹窗
└─ app*.py              主类（继承 6 个 mixin）
query.py                搜索语法解析器
transform.py            27 项文本变换
ClawBoardC/             C 语言版本
packaging/              打包配置（PyInstaller spec、图标、启动脚本、安装包脚本）
tests/                  回归测试（177 项）
└─ testdata/            测试数据生成器
docs/                   设计文档 + 截图
```

依赖方向（禁止循环 import）：`config`（叶子）→ 领域层 → 系统接入层 → UI 控件层 → UI 编排层 → 入口。

## 🧪 测试

```bash
python tests/test_core.py        # 搜索语法单测（27 项）
python tests/test_refactor.py    # 重构单测（12 项）
python tests/_t14.py             # 内容自适应（38 项）
python tests/_t22.py             # 工具条布局（26 项）
python tests/_t24.py             # 折叠 / 重复复制（24 项）
python tests/_t25.py             # 边缘拉伸（25 项）
python tests/_t26.py             # UI 等比缩放（25 项）
```

共 **177 项**回归测试，覆盖布局、几何、数据、交互等核心路径。

## 🎯 设计取舍

- **零第三方依赖**：界面用自带的 tkinter，系统能力全用 ctypes 直调 Win32 —— 不用联网、不会被库版本坑、复制即跑
- **纯文本定位**：只处理文本剪贴板，不扩图片/文件（保持简洁）
- **数据用 JSON 而非 SQLite**：单文件、易备份、可手改；配版本化迁移与原子写保证安全
- **双语言实现**：Python 版验证复杂逻辑，C 版验证脱离解释器能压到多小

## 📄 许可

[MIT](LICENSE)
