# ClawBoard

一个 Windows 悬浮剪贴板 & 常用语面板工具。零第三方依赖，Python 标准库 `tkinter` + `ctypes` 直调 Win32 实现，同时提供纯 C（Win32 API）版本。

> 挂在屏幕一角的轻量剪贴板历史 + 常用语，支持搜索、文本变换、批量导出、快速粘贴，以及一套面向隐私的剪贴板处理机制。

## 特性

- **剪贴板历史**：自动记录、去重、上限裁剪、收藏、悬停显示时间
- **常用语分组**：分组管理、拆词、命名、编辑
- **高级搜索语法**：`time:` / `app:` / `type:` / `size:` / `is:` / `-排除`，多词 AND + 高亮
- **27 项文本变换**：编解码、大小写、行处理、哈希（MD5/SHA1/SHA256）、JSON 格式化
- **批量导出**：TXT / CSV（带 BOM）/ JSON / Markdown
- **快速粘贴**：`Ctrl+1..9` / `Ctrl+0` 直接粘贴第 1~10 项
- **隐私保护**：遵守 Windows「别记录我」剪贴板标记、程序/标题忽略名单、敏感内容识别与打码
- **交互**：靠边自动隐藏、双击折叠贴右下角、窗口四边四角随意拉伸、UI 等比缩放（50%~150%）、自定义背景色、亮/暗主题

## 运行

### Python 版（需 tkinter）

```bash
python ClawBoard.py
```

依赖：仅标准库（`tkinter` / `ctypes` / `winreg` 等），无任何 pip 依赖。Windows 10 / 11。

### 打包为 exe

```bash
pip install pyinstaller
pyinstaller ClawBoard.spec
# 产物在 dist/ClawBoard.exe，数据文件落在 exe 旁边
```

### C 版（可选）

`ClawBoardC/` 目录下是一个纯 Win32 + GDI 自绘的 C 语言实现（约 2500 行），
零第三方库、产物约 200KB。用 `ClawBoardC/build.bat`（需 Visual Studio MSVC）编译。
两版读写**同一份数据文件**（`ClawBoard数据.json`），可互换使用。

## 快捷键

| 按键 | 功能 |
|---|---|
| `Ctrl+Shift+V`（默认） | 唤起/隐藏面板 |
| `Ctrl+1..9` / `Ctrl+0` | 直接粘贴第 1~10 项 |
| `Ctrl+T` | 文本变换 |
| `Ctrl+E` | 批量导出 |
| `Ctrl+F` | 聚焦搜索 |
| `Ctrl+=` / `Ctrl+-` | UI 等比缩放 |
| `Esc` | 隐藏 |

## 项目结构

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
```

架构遵循四层依赖方向（禁止循环 import）：`config`（叶子）→ 领域层 → 系统接入层 → UI 控件层 → UI 编排层 → 入口。

## 测试

```bash
python test_core.py       # 搜索语法单测（27 项）
python test_refactor.py   # 重构单测（12 项）
python _t14.py            # 内容自适应（38 项）
python _t22.py            # 工具条布局（26 项）
python _t24.py            # 折叠/重复复制（24 项）
python _t25.py            # 边缘拉伸（25 项）
python _t26.py            # UI 等比缩放（25 项）
```

共 177 项回归测试，覆盖布局、几何、数据、交互等核心路径。

## 许可

[MIT](./LICENSE)
