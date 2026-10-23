# ClawBoard

**简体中文** | [English](README.en.md)

> Windows 悬浮剪贴板 & 常用语面板 —— 零第三方依赖，Python（tkinter + ctypes）与纯 C（Win32）双版本。

挂在屏幕一角的轻量剪贴板历史：随手复制的文字、图片都在这里，搜得到、变得了、贴得快，隐私还握在自己手里。

<p align="center">
  <a href="../../stargazers"><img src="https://img.shields.io/github/stars/pay-and-gain/ClawBoard?style=social" alt="stars"></a>
</p>

> 💛 **如果这个工具帮到了你，点个 Star 支持一下吧** —— 你的每一个 Star 都是持续更新的动力。觉得好用也欢迎分享给同事和朋友。

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/main-window.png" alt="ClawBoard 主界面：剪贴板历史列表" width="300">
</p>

- **首次启动引导** —— 新用户空数据时给出上手卡片：3 步上手 + 快捷键 + 一键「载入示例数据」
- **剪贴板历史** —— 自动记录、去重、上限裁剪、收藏；悬停看时间，右键看详情
- **补记** —— 程序没运行时复制的内容，启动后自动补记（仅能补回你**最后一次**复制的那条，Windows 剪贴板只保留一份）
- **快速粘贴** —— `Ctrl+1..9` / `Ctrl+0` 直接粘贴第 1~10 项
- **隐私保护** —— 遵守 Windows「别记录我」标记、程序 / 标题忽略名单、敏感内容识别与打码
- **音效反馈** —— 复制 / 粘贴各一个独立开关（默认关），盲操时不用看屏幕也能确认「贴没贴上」
- **自动更新提示** —— 启动静默检查；发现新版在设置里一键「去下载」——只提示、不打扰
- **全屏不挡游戏** —— 全屏程序在前台时自动取消置顶、被游戏覆盖；热键呼出面板照常用
- **多屏自由移动** —— 面板可在多个显示器之间自由拖动、跨屏停靠；靠边收纳与「重置位置」都按面板**所在那块屏**判定（v2.6.1 修复）

👉 第一次用？看 [**新手教程**](docs/getting-started.md) —— 30 秒上手，5 分钟摸透全部核心功能。

## 📥 下载

| 方式 | 文件 | 说明 |
|---|---|---|
| **安装包**（推荐） | `ClawBoard-2.6.1-setup.exe` | 双击安装，自动建开始菜单 / 桌面快捷方式，带卸载项 |
| **绿色版** | `ClawBoard-2.6.1-portable.zip` | 解压即用，不写注册表、不留残留 |
| **源码** | `Source code (zip/tar.gz)` | Release 页由 GitHub 自动提供；也可 `git clone` |

👉 全部文件在 [**Releases 页面**](../../releases/latest)。

## ✨ 特性

### 🔍 高级搜索 · 拼音 · 自动标签

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/search-highlight.png" alt="高级搜索：ClawBoard type:url，命中词高亮" width="440">
</p>

- **高级搜索** —— `app:` 来源 / `time:` 时间 / `type:` 类型 / `size:` 大小 / `is:` 状态 / `tag:` 标签 / `-` 排除，多词 AND + 命中高亮
- **拼音搜索** —— 搜 `zhanghao` 或 `zh` 也能命中「账号」，记不清字照样找得到
- **内容自动标签** —— 自动识别邮箱 / 手机号 / 数字 / 日期 / 链接 / 代码 / JSON，`tag:` 一键筛选

### 💬 常用语与触发词

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/phrases.png" alt="常用语面板与触发词设置" width="460">
</p>

- **常用语** —— 分组管理、拆词（一段文字批量切成多条）、增删改
- **触发词快速粘贴** —— 给常用语设触发词（`dz` → 地址），任何程序输入即替换

### 🖼️ 图片剪贴板

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/image-clipboard.png" alt="图片剪贴板：白色条目 + 角落大图预览" width="560">
</p>

- **图片剪贴板** —— 截图 / 复制图片自动记录，选中即在角落弹出大图预览
- 记录 / 预览 / **粘贴** 与文本完全对称；复制图片*文件*时记录的是**路径**（CF_HDROP）

### 🧰 27 项文本变换 · 批量导出

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/transform.png" alt="文本变换窗口：推荐变换 + 原文 / 结果对照" width="520">
</p>

- **27 项文本变换** —— 编解码、大小写、行处理、哈希（MD5 / SHA1 / SHA256）、JSON 格式化…按内容智能推荐
- **批量导出** —— TXT / CSV（带 BOM）/ JSON / Markdown

### ⌨️ 命令面板

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/command-palette.png" alt="命令面板：模糊过滤命令" width="300">
</p>

- **`Ctrl+Shift+P` 呼出** —— 输入命令名模糊过滤，回车即执行

### 🎨 外观个性

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/theme-compare.png" alt="亮色 / 暗色主题对比" width="300">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/folded-edge.png" alt="展开面板与双击折叠贴边对比" width="320">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/scale-compare.png" alt="界面等比缩放 50% / 100% / 150%" width="330">
</p>

- **亮 / 暗主题**、**双击折叠贴边**、**界面等比缩放 50%~150%**（`Ctrl+=` / `Ctrl+-`）
- 还能自定义背景色、靠边自动隐藏、四边四角随意拉伸

### ⚙️ 设置一目了然

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/settings-general.png" alt="设置 - 基础" width="300">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/settings-sound.png" alt="设置 - 音效反馈" width="300">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/settings-advanced.png" alt="设置 - 进阶与更新" width="300">
</p>

- 基础 / 进阶分栏滚动：监听、打码、主题、缩放、忽略名单、长度过滤、音效反馈、检查更新、开机自启一屏可调

## 🚀 快速开始

### 方式一：装安装包
下载 `ClawBoard-2.6.1-setup.exe` 双击，按提示装完即可（Windows 10 / 11）。

### 方式二：绿色版
下载 `ClawBoard-2.6.1-portable.zip`，解压到任意目录，双击 `ClawBoard.exe`。

### 方式三：从源码运行
```bash
git clone https://github.com/pay-and-gain/ClawBoard.git
cd ClawBoard
python ClawBoard.py     # Windows，Python 3.10+，安装时包含 Tcl/Tk
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
用 `ClawBoardC/build.bat` 编译（需 MSVC）。两版**共用同一份数据文件**，可互换使用。

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
| [**新手教程**](docs/getting-started.md) · [English](docs/getting-started.en.md) | **第一次用？从这里开始**：30 秒上手 + 5 分钟教程 + 核心功能逐个上手 |
| [制作思路](docs/制作思路.md) · [English](docs/DESIGN.en.md) | **功能说明 + 使用指南 + 设计思路**：需求来源、方法顺序、技术选型、实现步骤、踩坑、实测数据、FAQ |
| [使用说明](docs/使用说明.md) | 详细操作手册 |
| [当前架构与维护约定](docs/REFACTOR.md) | 独立服务、线程边界、存储保护、兼容入口与回归方法 |
| [项目解析与优化设计](docs/PROJECT_REVIEW.md) | 性能诊断、设计取舍、问题分析与 UI / 图标建议 |
| [早期架构设计](docs/架构设计.md) | v1.5 单文件拆包的历史方案 |
| [需求与进度](docs/需求全景.md) · [PROGRESS](docs/PROGRESS.md) | 需求全景与开发过程记录 |
| [CHANGELOG](CHANGELOG.md) | 逐版本改动记录 |

## 🏗️ 项目结构

```
ClawBoard.py            入口 + re-export 聚合层
clawboard/              独立服务 + Windows / Tk 适配器
├─ application.py       应用控制器：提交采集结果、保存与关闭
├─ models.py            数据契约归一化与旧 C 枚举兼容
├─ history.py           入库、编辑与派生元数据更新
├─ search.py            查询解析、惰性拼音与有界缓存
├─ privacy.py           敏感识别和统一显示策略
├─ storage.py / media.py JSON 与图片文件存储
├─ dispatch.py / tasks.py 主线程结果队列与受限后台任务
├─ services.py          剪贴板序列确认与串行保存服务
├─ image.py             可独立测试的图片编解码
├─ windows_*.py         ABI 声明、焦点、几何、输入、系统与钩子
├─ win32_snapshot.py    一次性读取剪贴板快照
├─ tk_bridge.py         将应用结果接到 Tk 主线程
├─ viewmodels.py / vlist.py 惰性展示投影与复用行池
├─ *_dialog.py          设置、变换与导出界面
└─ app*.py              兼容的主窗口与交互适配层
query.py                搜索公共 API 兼容入口
transform.py            27 项文本变换
ClawBoardC/             C 语言版本与共享 JSON 字段保留逻辑
packaging/              打包配置（PyInstaller spec、图标、启动脚本、安装包脚本）
tests/                  纯逻辑、适配器合同与 Windows 桌面回归
└─ testdata/            测试数据生成器
docs/                   设计文档 + 截图
```

领域逻辑不依赖 Tk 或 Win32；应用控制器通过注入的存储和系统接口工作，组合根负责装配。
旧的 `query.py`、`app_services.py`、`dialogs.py` 和 `win32.py` 保留兼容导出。
这轮源码重构仍使用版本号 **2.6.1**；下载区对应已发布产物，重构本身不自动发布安装包。

## 🧪 测试

```bash
python tests/_t44.py             # 服务重构汇总入口；Windows 上同时加载原生兼容测试
python tests/test_core.py        # 搜索语法 + 时间时隙
```

`_t44.py` 汇总 `test_*.py`，包含纯服务测试以及用模拟系统/界面端口验证的装配合同。
Linux 上会跳过需要 Windows 原生导入的兼容入口；模拟通过不代表 Win32 ABI、焦点或桌面效果已验证。

Windows 桌面另跑以下回归，运行前退出其他 ClawBoard 实例，并按脚本要求使用临时数据目录与 `NO_SAVE`：

```bash
python tests/test_refactor.py    # 原生 re-export 兼容
python tests/_t14.py             # 内容自适应 + 卡片样式
python tests/_t22.py             # 工具条布局
python tests/_t24.py             # 折叠 / 重复复制
python tests/_t25.py             # 边缘拉伸
python tests/_t26.py             # UI 等比缩放
python tests/_t27.py             # 数据目录选址
python tests/_t28.py             # 粘贴不整窗闪
python tests/_t29.py             # 变换推荐 + 频率排序
python tests/_t30.py             # 命令面板
python tests/_t31.py             # 触发词引擎
python tests/_t32.py             # 拼音搜索 + 多音字词组
python tests/_t33.py             # 图片 DIB↔PNG 往返
python tests/_t34.py             # 内容自动标签
python tests/_t35.py             # 文件路径记录 CF_HDROP
python tests/_t37.py             # 文件剪贴板读写闭环
python tests/_t42.py             # 启动补记
python tests/_t43.py             # 多屏几何
```

实际通过与跳过数量以当次输出为准。双屏不同 DPI、真实剪贴板争用、浏览器/管理员窗口粘贴、
托盘和安装包仍需 Windows 真机验证；完整边界与测试方法见 [REFACTOR.md](docs/REFACTOR.md)。

## 🗺️ 迭代路线

最近五个版本按「① 快赢 → ② 战略 → ③ 可选」三个优化方向迭代，每个版本在 [Releases](../../releases) 独立保留：

| 版本 | 优化方向 | 内容 |
|---|---|---|
| v2.1.0 | ③ 可选 | 内容自动标签 |
| v2.0.0 | ② 战略 | 图片剪贴板 |
| v1.9.0 | ② 战略 | 拼音搜索 |
| v1.8.0 | ① 快赢 | 触发词快速粘贴 |
| v1.7.0 | ① 快赢 | 命令面板 |

更早版本（UI 焕新、粘贴体验、安装版修复等）见 [CHANGELOG](CHANGELOG.md)。

## 🎯 设计取舍

- **零第三方依赖**：界面用自带的 tkinter，系统能力全用 ctypes 直调 Win32 —— 不用联网、不会被库版本坑、复制即跑
- **文本为主、图片为辅**：文本剪贴板是核心，图片同样支持记录、预览与**粘贴**（v2.2.0 起，零依赖手写 PNG 编解码，DIB↔PNG 双向转换）
- **数据用 JSON 而非 SQLite**：单文件、易备份、可手改；配版本化迁移与原子写保证安全
- **双语言实现**：Python 版验证复杂逻辑，C 版验证脱离解释器能压到多小

## 📄 许可

[MIT](LICENSE)
