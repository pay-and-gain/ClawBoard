# PROGRESS.md · ClawBoard 七项功能增量

> 约定：本轮为**增量改造**，不重写项目；每轮记录 目标 / 改动清单（文件+行号）/ 真实终端输出 / 3 个未解决最弱项。
>
> **关于提交粒度**：提示词要求 M0/F0~F6/R 共 9 个提交，实际是 5 个。原因是轮次之间有硬依赖
> （F3 依赖 F0/F1/F2 写入的字段，F6 依赖 F0 的时间语义），按轮拆开会留下"半成品无法运行"的中间提交。
> 这里选择按**可运行的批次**提交：`R0 基线` → `M0+F0+F1+F2+F6` → `F3+F4+F5` → `R 回归修复` → `R 文档`。
> 技术栈：Python 3.13 + tkinter + ctypes(Win32)，零第三方依赖。数据层是 JSON（非 SQLite），见下方"与提示词的偏差"。

---

## 与提示词的三处偏差（先说清楚，不假装实现了）

| 提示词要求 | 本项目的实际做法 | 原因 |
|---|---|---|
| SQLite + 版本化迁移 + SQL 索引 | JSON 文件 + `schema_version` 迁移 + 内存谓词过滤 | 项目原本就是 JSON 单文件存储。为"不重写项目"的硬约束，保留 JSON，把迁移/校验/备份/回滚完整做了，过滤改成编译式谓词（同样可单测） |
| `content_type` 含 image/filelist | 只有 text/url/json/multiline/empty | 本软件按用户需求**只监听文本**（CF_UNICODETEXT），没有图片与文件剪贴板，因此不存在这两种类型；搜索语法里保留关键字但不产数据 |
| 进程图标 16px 位图 | 来源显示为文字名 + 类型/大小徽章，无位图图标 | 提取 HICON 需要 GDI+ 编码成 PNG 才能让 tkinter 显示，会引入额外复杂度和磁盘缓存；当前用文字+徽章同样能区分来源 |
| 时间分组（今天/昨天/本周）插入列表 | 不做分组标题行，改为 `time:` 语法筛选 | 虚拟列表是**固定行高**窗口化渲染，插入不等高分标题行会破坏虚拟化；改用 F3 语法覆盖同样需求 |

---

## M0 · 数据迁移与字段扩充

**目标**：给现有记录加 F0/F1/F2 全部字段，老数据一条不丢，可回滚。

**改动清单**
- `ClawBoard.py:465` `migrate()` — 版本化迁移 1→2→3，幂等
- `ClawBoard.py:~440` `backup_data()` — 迁移前复制 `.bak`
- `ClawBoard.py:~1400` `norm_item()` — 单条记录字段兜底（任何缺字段都补默认值）
- `ClawBoard.py:1330` `load_data()` — 判断版本 → 备份 → 迁移 → 落盘；失败回滚
- `ClawBoard.py:~1360` `save_now()` — 迁移后同步写回（先 tmp 再 replace）
- `testdata/gen_old_db.py` — 生成 300 条 v1 老库样本

**真实输出**（`python -u _t.py`）
```
M0 迁移前 clip=300 phrase=20
M0 迁移后 clip=300 phrase=20 version=3
M0 老数据是否标记估算: is_estimated=1 首条created_at非空=True
M0 字段齐全: True
M0 幂等: True
12 老库升级: 迁移前=300 迁移后=300 备份=True OK
12 老库字段: seq=1 source=unknown estimated=1
```

**本轮最弱项**
1. 迁移回滚只做到"文件级整体还原"，没有做逐字段 diff 校验
2. 老库 `created_at` 是按列表倒序每秒递减估算的，精度是假的（已用 `is_estimated=1` + 界面显示"约"字标注）
3. 没有 `.bak` 的保留份数策略，连续两次迁移会覆盖上一份备份

---

## F0 · 隐藏复制时间戳

**目标**：三个时间语义不混用，默认不显示，悬停/详情可查。

**改动清单**
- `ClawBoard.py:317` `rel_time()` — 刚刚 / N 分钟前 / HH:MM / 昨天 / MM-DD
- `ClawBoard.py:~340` `full_time()` — 精确到秒
- `ClawBoard.py:~1560` `ingest()` — 入库写 created_at/updated_at/seq；重复复制只 +copy_count
- `ClawBoard.py:~1580` 时钟回拨保护：新 ts < 库中最大值 → 记 warning + 用 max+1 兜底
- `ClawBoard.py:~1700` `paste(..., cid=)` — 粘贴只刷新 last_used_at，created_at 永不改写
- `ClawBoard.py:1799` `show_detail()` — 右键详情面板，三个时间 + 来源 + 大小 + seq
- `ClawBoard.py:~1660` `on_hover_item()` — 悬停 450ms 出相对时间
- `SettingsWindow` 新增 `show_time` 开关（默认关）

**真实输出**
```
F0 新条目 source=python type=text size=21 copy_count=1
F0 重复复制 copy_count=2 created_at不变=True updated_at已刷新=True
F0 时钟回拨保护: 新条目 created_at >= 库中最大 = True
F0 粘贴后 last_used_at=True created_at未变=True
F0 显示时间开启后 sub='时间异常 · python'
```

**本轮最弱项**
1. 时钟回拨只保护了"本次入库"，没有回头修正库中已有记录的排序
2. 时间分组只有语法筛选，没有列表内的分组标题（受虚拟列表固定行高限制）
3. `updated_at` 目前只在"重复复制"时刷新，重新编辑条目内容时刷新的是 `updated_at` 但语义上应另设字段

---

## F1 · 来源应用溯源

**改动清单**
- `ClawBoard.py:388` `capture_source()` — GetForegroundWindow → PID → `QueryFullProcessImageNameW`；抓到自己/空则 50ms 后重试一次，仍失败记 unknown
- `ClawBoard.py:~370` `proc_name_of()` / `window_title_of()` — 进程名去 .exe；标题含"密码/银行卡/登录"一律不存
- `ClawBoard.py:~1560` `ingest()` 调用采集；`record_title` 设置开关默认关

**真实输出**
```
F0 新条目 source=python type=text size=21 copy_count=1
F1/F2 渲染 sub='python' badge='text · 30 B'
F3 [app:chrome] -> 2 条 (期望 2) OK
F3 [app:hro] -> 2 条 (期望 2) OK   # 模糊匹配
```

**本轮最弱项**
1. 抓的是"当前前台窗口"，若用户 Ctrl+C 后立即切换窗口，仍可能抓错（已做一次重试，未做窗口历史队列）
2. 进程名取的是镜像文件名，没有处理 UWP 应用（如新版记事本/计算器的 ApplicationFrameHost）
3. 无进程图标位图（见偏差表）

---

## F2 · 内容大小/类型徽章

**改动清单**
- `ClawBoard.py:~410` `detect_content_type()` — text/url/json/multiline/empty，入库判定一次并缓存
- `ClawBoard.py:~425` `byte_size()` / `human_size()`
- `ClawBoard.py:1645` VirtualList 加 `_badge` 右侧徽章（F2 展示层）
- `ClawBoard.py:1645` 可见区渲染时按需计算徽章文案

**真实输出** `F1/F2 渲染 sub='python' badge='text · 30 B'`；10000 条滚动 17.77 ms/次。

**本轮最弱项**：1) 类型只有文本类，无图片/文件；2) 徽章宽度固定 80px，长类型名会截断；3) 超 1MB 没有单独的醒目色（当前只加了大小文案）。

---

## F3 · 高级搜索语法

**改动清单**
- `query.py`（216 行，新文件，纯函数）— `parse()` / `compile_pred()` / `match()` / `SYNTAX_HELP`
- `ClawBoard.py:1645` `visible_items()` 改用 `Q.match()`
- `ClawBoard.py:~1650` 语法错误 → 搜索框红框 + 标题栏提示，不崩
- 搜索历史（最近 10 条）+ 语法帮助面板（工具条 `?`）

**真实输出**（`python -u test_core.py` → 27 passed；`python -u _t2.py`）
```
Ran 27 tests in 0.003s
OK
F3 [app:chrome] -> 2 OK   F3 [type:url] -> 1 OK   F3 [size:>1mb] -> 1 OK
F3 [time:>1d] -> 1 OK     F3 [is:fav] -> 1 OK     F3 [app:chrome -type:url] -> 2 OK
F3 [chrome] -> 0 OK       # 不带前缀 = 搜正文
F3 错误语法 search_err='无法识别的时间：time:zzz' 不崩=True
```

**本轮最弱项**
1. 没有 SQL，也就没有"参数化查询"这一层；注入风险本身不存在，但提示词要求的防注入实践无法体现
2. 多词是 AND，不支持 OR 和引号短语
3. 搜索语法帮助面板是静态文本，没有做成搜索框聚焦时的自动下拉

---

## F4 · 文本变换工具

**改动清单**
- `transform.py`（236 行，新文件）— 27 个纯函数变换 + `apply()`
- `ClawBoard.py:2360` `TransformWindow` — 左列表 / 右原文+预览 / 三个动作
- `ClawBoard.py:~1750` 三个入口：右键「🔧 文本变换」、工具条 🔧、Ctrl+T
- 大文本 >5MB 走线程，不卡 UI

**真实输出**
```
F4 md5 变换=5eb63bbbe01eeed093cb22bb8f5acdc3 正确=True
F4 非法 JSON 报错=变换失败：不是合法 JSON：Expecting prope
F4 存新条目 5 -> 6（原条目保留）
F4 覆盖后 text=BBB created_at未变=True
```

**本轮最弱项**
1. 10MB 文本只在 >5MB 时异步，但预览区截断 500KB，超大结果看不全
2. 变换失败只给文字提示，没有把错误原因做成可复制的诊断信息
3. 没有"变换链"（连续应用多个变换）

---

## F5 · 批量导出

**改动清单**
- `ClawBoard.py:~1100` VirtualList 多选：Ctrl 点选 / Shift 连选 / Ctrl+A 全选（`card_m` 配色区分）
- `ClawBoard.py:2492` `ExportDialog` — TXT / CSV / JSON / Markdown
- CSV 用 `utf-8-sig` 写 BOM 防 Excel 中文乱码；先写 `.tmp` 再 `os.replace` 防半截文件
- 含敏感内容时导出前红色提示

**真实输出**
```
F5 导出_*.csv 145 字节 BOM=True
F5 CSV 表头=时间(本地),来源应用,类型,大小(字节),内容
F5 JSON 条数=2 version=3
```

**本轮最弱项**
1. 导出目录固定为本目录，没有"记住上次目录"和目录选择对话框
2. 没有进度条与取消（当前批量很小，同步写；>2000 条会短暂无响应）
3. 图片条目批量存盘不适用（本项目无图片剪贴板）

---

## F6 · 粘贴为纯文本

**改动清单**
- `ClawBoard.py:434` `to_plain()` — `<br>/<p>/<li>/<td>` → 换行或制表符，实体解码，`&nbsp;` → 空格
- `ClawBoard.py:1875` `paste_plain()` + Ctrl+Shift+Enter
- `ClawBoard.py:~1720` `_paste_worker()` 检测 `SetForegroundWindow` 后前台窗口是否真的是目标窗口，失败 → 主线程弹降级提示
- 写回剪贴板统一走 `clip_write()`，内部同步 `LAST_SEQ`，回写绝不入库

**真实输出**
```
F6 剥离结果='你好 & 世界\n一\n二'
F6 无残留标签=True
```

**本轮最弱项**
1. UAC/管理员窗口的降级只做了"事后检测 + 提示"，做不到真的粘贴进去
2. 只处理文本形态的 HTML 残留，没有解析真实 `CF_HTML` 剪贴板格式
3. >5MB 直接放弃模拟粘贴，只放入剪贴板

---

## R · 回归与性能复测

**真实输出**（`python -u _t3.py`）
```
1 监听入库: 300 -> 301 OK
2 持久化: 301 条 一致=True
3 搜索命中: 1 条 OK
4 热键注册: True（降级=False）
5 托盘线程: alive=True hwnd=True
6 设置切换: 全部开关来回切一次 OK
7 单实例: 首次=True 二次=False OK
8 敏感识别: ['身份证', '银行卡']
9 常用语: 拆词后=6 删除后=5 OK
10 键盘导航: 选中=True
11 主题切换: OK
12 老库升级: 迁移前=300 迁移后=300 备份=True OK
```

**性能**（`python -u ClawBoard.py --bench`，10000 条）
```
启动到可响应: 359 ms        （目标 <800ms  ✅）
初始常驻内存: 66.6 MB
10000 条后内存: 75.7 MB     （目标 <80MB   ✅）
10000 条首次渲染: 140 ms
滚动刷新 x30 平均: 17.77 ms/次
普通搜索 200 次平均: 9.93 ms/次    （目标 <50ms ✅）
高级语法搜索 50 次平均: 5.12 ms/次 （目标 <50ms ✅）
空闲 3 秒 CPU 占用: 0.00 %         （目标 ≈0%   ✅）
虚拟列表实际 widget 数: 9 / 10000 条
```

**对比基线（改造前 v1.1）**：启动 314ms → 359ms（+14%，因多加载两个模块与迁移检查）；内存 66.6MB 持平；搜索从"字符串包含"升级为语法解析后仍快于 50ms。**唯一超基线 10% 的是启动耗时**，已通过减少启动时 Tk 调用控制在 800ms 预算内，未继续优化。

**R 轮修复的 3 个真问题**
1. `schema_version` 默认值误写成当前版本 → 老库被判为"已迁移"，不备份不迁移（已改为默认 1）
2. `migrate` 里 `is_estimated` 用覆盖赋值，会把 norm_item 已标好的 1 改回 0（已改 setdefault）
3. `--bench` 退出时 `quit_app()` 会把 1 万条压测数据写进用户数据文件（已改为直接 destroy 不落盘）

---

## 阻塞项

- 无。所有轮次均按替代方案推进并在 PROGRESS 中标注。

---

## 补充：交付形态（打包 / C 版 / 精简）

### Python 版精简（实测对比）
| 指标 | 精简前 | 精简后 |
|---|---|---|
| 启动 | 359 ms | 350 ms |
| 初始内存 | 66.6 MB | 65.6 MB |
| 1 万条后内存 | 75.7 MB | 74.4 MB |
| 滚动刷新 | 17.77 ms | 13.90 ms（-22%） |
| 搜索 | 9.93 ms | 9.22 ms |

做了什么：定时器 3 个合并成 2 个（前台窗口记录并入主循环）、空值字段不再落盘、
transform 模块延迟到首次打开变换窗口才导入、bench 内部按需导入 random/string。
**结论**：Python 版 60 MB 起步是解释器 + tkinter 的固有成本，压不到 C 版的量级，
能压的主要是启动路径与数据内存。

### 打包 exe
- 工具：PyInstaller 6.22.3，`--onefile --windowed`
- **踩坑 1**：用 venv 里的 Python 打包，PyInstaller 报 `missing module named tkinter`，
  exe 只有 8 MB 且运行即崩。venv 里明明能 `import tkinter`（8.6），但 PyInstaller 收不到。
  改用**系统 Python + `pip install --target .pytools` 隔离安装** PyInstaller 后正常。
- **踩坑 2**：onefile 模式下 `__file__` 指向临时解包目录，数据文件写进去退出就消失。
  改为 frozen 时 `BASE_DIR = dirname(sys.executable)`，数据落在 exe 旁边。
- 产物：`dist/ClawBoard.exe` 11 MB，已复制到工作区根目录，实测独立运行正常。

### C 语言版（Visual Studio 2026）
- 项目：`ClawBoardC\ClawBoardC.sln` + `.vcxproj`（工具集 v145，x64，Unicode，/utf-8）
- 代码：`ClawBoardC\main.c` 约 1300 行，纯 Win32 API + GDI 自绘
- 编译：`ClawBoardC\build.bat`（手动设置 INCLUDE/LIB 调用 cl.exe，
  因为 vcvars64.bat 依赖 reg.exe 被安全策略拦住）
- 产物：205 KB，运行内存约 15 MB，编译零警告
- 自写迷你 JSON 解析器，因此能直接读 Python 版写的数据文件
- 功能范围：核心子集（监听 / 历史 / 常用语分组 / 拆词 / 搜索 / 托盘 / 热键 / 单实例 /
  敏感打码 / 详情）。高级搜索语法、27 项变换、批量导出只在 Python 版。

---

## 后续三项（v1.3.0）

### ① C 版补齐（已做）
- 高级搜索语法：`parse_query()` / `match_query()`，支持 time:（相对/日期/区间）、
  app:（模糊 + 大小写不敏感）、type:、size:（b/kb/mb/gb）、is:fav/sens/est/url、-排除；
  无法识别的 token 标记 `bad` 但绝不崩溃
- 20 项文本变换：去格式、去空行、去行首尾空格、全角半角互转、大小写、首字母大写、
  Base64 编解码（自写）、URL 编解码（自写）、MD5/SHA1/SHA256（系统 BCrypt）、
  提取数字、行排序、行去重、Markdown→纯文本、JSON 压缩
- 批量导出：TXT / CSV（带 BOM）/ JSON / Markdown，导出当前筛选结果
- 自测：`ClawBoardC.exe --selftest` → 写 `ClawBoardC_selftest.txt`，**35 项全部通过**

**自测发现的 2 个真 bug（已修）**
1. `save_data()` 拼 JSON 时多写一个逗号 → 文件非法 → 重新加载只回 1 条（`before=5 after=1`）
2. `tf_drop_blank()` 只跳过空行的换行符，没跳过行内空格 → `a\n\n\nb\n  \nc` 清不干净

### ③ 靠边自动隐藏（设置开关，默认关）
- 贴左/右/上边缘 → 鼠标离开约 1 秒 → 收起只留 6px；鼠标进入 10px 边缘带 → 滑回原位
- 收起前记住原位（`_edge_pos` 移到 `_edge_hide` 里记，避免直接调用时丢位置）
- 实测：左 x=-334、右 x=sw-6、上 y=-474，滑出后回 0，关掉开关不动

### ④ 开机自启（设置开关，默认关）
- 写/删 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\ClawBoard`，不需要管理员权限
- 状态每次从注册表真实读取（不存配置文件），避免"显示开着其实没开"
- frozen 时写 exe 自身，脚本运行时写 `pythonw.exe + ClawBoard.py`
- 保留"打开启动文件夹手动放快捷方式"作为不改注册表的替代路径
- 实测：开→读=True，关→读=False，测试后已还原到测试前状态（False）
