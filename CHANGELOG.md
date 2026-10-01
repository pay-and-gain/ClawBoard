# CHANGELOG

## v1.3.0 · 后续三项（C 版补齐 + 两个独立开关）

### 新增
- **C 版补齐三项**：高级搜索语法（`time:`/`app:`/`type:`/`size:`/`is:`/`-排除`，含模糊匹配与大小写不敏感）、
  20 项文本变换（含 MD5/SHA1/SHA256，调用系统 BCrypt 接口，不引入第三方库）、
  批量导出 TXT / CSV（带 BOM）/ JSON / Markdown
- **C 版自测模式**：`ClawBoardC.exe --selftest`，35 项断言（语法 14 + 变换 18 + 持久化 3），全部通过
- **靠边自动隐藏**（设置开关，默认关）：贴左/右/上边缘后鼠标离开约 1 秒自动收起只留 6px，碰边缘自动滑出
- **开机自启**（设置开关，默认关）：写/删当前用户注册表 Run 项，不需要管理员权限，状态从注册表真实读取

### 修复
- C 版 `save_data()` 输出 JSON 时多出一个逗号，导致文件非法、重新加载只能读回 1 条
- C 版 `tf_drop_blank()`（去空行）只跳过换行符没跳过行内空格，空行里的空格被留下
- C 版 64 位下 `(HMENU)id` 类型转换警告（改为 `(HMENU)(INT_PTR)id`）

## v1.2.0 · 七项功能增量（M0 / F0~F6 / R）

### 新增
- **M0 数据迁移**：schema_version 1→2→3，幂等；迁移前自动备份 `.bak`，失败自动回滚；老数据按倒序估算 `created_at` 并标记 `is_estimated=1`（界面显示"约"）
- **F0 隐藏时间戳**：created_at / updated_at / last_used_at 三语义分离；默认不在列表显示，悬停出相对时间，右键「查看详情」看完整三个时间 + 来源 + 大小 + seq；时钟回拨时用 seq 兜底并记日志；重复复制只 +copy_count，created_at 永不改写
- **F1 来源应用溯源**：前台窗口 → PID → 进程名；抓到自己或空则 50ms 重试一次，仍失败记 unknown；支持 `app:` 搜索（中文/模糊）
- **F2 类型与大小徽章**：text/url/json/multiline/empty 入库判定一次并缓存，列表右侧显示 `类型 · 大小`
- **F3 高级搜索语法**：`time:` / `app:` / `type:` / `size:` / `is:` / `-排除`；独立模块 `query.py`，27 个单测；语法错误红框提示不崩溃；搜索历史 10 条
- **F4 文本变换**：27 个纯函数（`transform.py`），左选右预览，三个动作（复制 / 存为新条目 / 覆盖原条目，覆盖时保留 created_at）；>5MB 异步
- **F5 批量导出**：Ctrl/Shift/Ctrl+A 多选，导出 TXT / CSV(带 BOM) / JSON / Markdown；先写 `.tmp` 再改名
- **F6 粘贴为纯文本**：Ctrl+Shift+Enter，剥 HTML 标签与实体、`<br>/<p>/<li>/<td>` → 换行/制表符；UAC 窗口失败自动降级提示

### 修复
- `schema_version` 默认值误写成当前版本，导致老库被判为已迁移、不备份（改为默认 1）
- `migrate` 覆盖写 `is_estimated`，会把已标记的估算值改回 0（改为 setdefault）
- `--bench` 退出时把 1 万条压测数据写进用户数据文件（改为直接销毁不落盘）
- 全局热键 `RegisterHotKey` 跨线程句柄无效（错误 1408）：改为在消息线程内用 NULL 句柄注册
- 托盘 `Shell_NotifyIconW` 与 `CreateMutexW` 挂错 DLL（分别在 shell32 / kernel32）
- `to_plain` 把 `&nbsp;` 解码成 `\xa0`（改为普通空格）
- `self._w` 与 tkinter 内部属性冲突（改名 `_vw`）

### 性能
- 虚拟列表改为固定行高窗口化渲染：10000 条只创建 9 个 widget
- 减少滚动时的重复 Tk 调用（宽度变化才 itemconfig）
- 搜索 9.93 ms/次，高级语法 5.12 ms/次，空闲 CPU 0.00%

## v1.1.0
- 系统托盘、全局热键、单实例互斥、虚拟滚动、敏感内容识别与打码、崩溃日志、亮/暗双主题、配置 schema 校验

## v1.0.0
- 悬浮面板：剪贴板历史 + 常用语分组，拆词、编辑、命名、删除、搜索
