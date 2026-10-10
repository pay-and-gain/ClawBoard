# ClawBoard 开发规则

> 这份文件写给所有要改动本项目的人 —— 也包括 AI 助手。
> 目的是把「这个项目不能违反什么」和「改完要做什么」写成**显式契约**，而不是靠记忆。
> 每条规则都来自真实踩过的坑。

---

## 1. 硬性技术约束（不可协商）

- **零第三方依赖**：运行时只用 Python 标准库 + ctypes 直调 Win32，不得引入需要 `pip install` 才能跑的依赖。
  `tools/` 下的开发工具是例外，但**必须在文件头注明**「开发工具，不参与产品运行」。
- **数据格式向后兼容**：Python 版与 C 版（`ClawBoardC/`）**共用同一份数据文件**。
  新增字段必须是可选的（老版本读不到就忽略），**不得改变已有字段的语义**。
- **不污染真实数据**：任何构造 App 的脚本都必须 `C.NO_SAVE = True`，
  并在 import 之前把数据目录指向临时目录。改完要核对 `ClawBoard数据.json` 的 hash 未变。
- **不提交敏感内容**：竞品分析、个人材料、含身份信息的文档一律不入库（见 `.gitignore`）。

## 2. 版本号：单一来源

- 唯一来源是 `clawboard/config.py` 的 `APP_VER`；`clawboard.__version__` 从它读取。
- **不要自动递增版本号**，除非明确要求发版。
- 发版时要**一起**改这五处，漏一个就会出现版本不一致：

  | # | 位置 |
  |---|---|
  | 1 | `clawboard/config.py` → `APP_VER` |
  | 2 | `packaging/installer.iss` → `MyAppVersion` |
  | 3 | `CHANGELOG.md` → 新增条目 |
  | 4 | `release/release-notes-<版本>.md` → 新增文件 |
  | 5 | `README.md` / `README.en.md` / `docs/getting-started*.md` 里的下载文件名 |

- 自检：`python -c "import clawboard; print(clawboard.__version__)"` 应与 `APP_VER` 一致。

## 3. 图片与文档引用（踩过两次的坑）

文档里的截图**必须用 GitHub Pages 绝对地址**：

```
https://pay-and-gain.github.io/ClawBoard/images/xxx.png
```

- ❌ **相对路径**：GitHub 会 302 到 `raw.githubusercontent.com`，该域名在部分网络不可达，图片全部破图。
- ❌ **jsDelivr**：回源失败时它会 **301 重定向回 `raw.githubusercontent.com`** —— 同样破图；
  而且按分支缓存，图片更新后最长 12 小时才刷新。
- ✅ 只有 `docs/index.html` 内部可以继续用相对路径（它本来就运行在 Pages 上，`images/x.png` 解析到同一处）。

## 4. 动手之前

- 新功能、交互重做、架构调整等**存在实质取舍**的改动：先给出 2~3 个方案及优缺点，让用户拍板。
- 明确的 bug 修复、文案/样式小改、已确认方案的实施：直接动手并验证，**不要再问一轮**。

## 5. 动手之后

- 跑测试确认全绿：

  ```bash
  python tests/test_core.py        # 搜索语法 + 时间时隙
  python tests/test_refactor.py    # 架构重构回归
  python tests/_t35.py             # 文件剪贴板（CF_HDROP）
  python tests/_t37.py             # 文件剪贴板闭环
  ```

  > GUI 类用例（`_t14` / `_t22` / `_t24` 等）需要**桌面没有其它 ClawBoard 实例在运行**，
  > 否则会被单实例互斥卡住 —— 这不是代码缺陷。

- 每加一个功能，就在 `tests/` 放一个 `_tNN.py` 回归脚本。
- 提交前确认 `git status` 里没有意外文件（尤其是数据文件、日志、竞品分析）。

## 6. 代码组织

- 依赖方向（**禁止循环 import**）：
  `config`（叶子）→ 领域层 → 系统接入层 → UI 控件层 → UI 编排层 → 入口。
- **单个 `.py` 文件不超过 800 行**。超了先拆再继续，不要无限追加。
- 注释写**「为什么」**而不是「做了什么」。反直觉的决策必须留痕，
  例如 `DragQueryFileW` 为什么必须声明 `argtypes`（不声明 64 位句柄会被截断成 `c_int`）。

## 7. 已知限制

- 单实例互斥会同时锁住 GUI 用例，跑测试前先退出正在运行的 ClawBoard。
- C 版与 Python 版能力不完全对齐（C 版更精简，产物约 205 KB）。
- 拼音搜索不支持多音字展开。
- 目前没有自动更新；`%LOCALAPPDATA%` 之外的便携模式数据跟随 exe 所在目录。
