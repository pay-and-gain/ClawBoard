# CHANGELOG

## v1.4.0 · 读三个开源剪贴板工具，取其可取之处

参考对象：**CopyQ**（12.3k★，C++/Qt）、**Ditto**（Windows 原生 C++）、
**PasteBar**（Tauri + React）。下面每条都标了出处，改的是**实现方式**，不是照抄代码。

### 隐私（这次最值钱的部分）
- **遵守 Windows 官方的「别记录我」标记**：读剪贴板的
  `ExcludeClipboardContentFromMonitorProcessing` 与 `CanIncludeInClipboardHistory`（值为 0），
  命中就整条跳过。这是 KeePassXC / 1Password / Bitwarden 用来告诉监听者「别记」的标准做法，
  比任何敏感词正则都准。**出处：Ditto `src/Clip.cpp:364` 与 `:400`**
- **忽略名单**：可配置「不记录哪些程序」（通配符，`keepass`→`*keepass*`）和
  「忽略标题匹配的窗口」（正则）。**出处：Ditto `src/ClipboardViewer.cpp:345` 的
  include/exclude 通配、CopyQ `src/common/predefinedcommands.cpp:151` 的 wndre 正则**
- 默认名单已预置 keepass / 1password / bitwarden / lastpass

### 粘贴可靠性
- **发键前先抬掉所有按着的修饰键**：按着 Ctrl 唤起面板时，残留的 Ctrl 会让我们的
  Ctrl+V 变成 Ctrl+Ctrl+V，目标程序收到的是裸 V —— 这正是"有时粘贴没反应"的原因。
  **出处：Ditto `src/SendKeys.cpp:237` 的 `AllKeysUp()`**
- **用 AttachThreadInput 绕过 Windows 前台锁定**，并**轮询等目标窗口真的拿到焦点**再发键，
  替换原来的固定 `sleep(0.10)`（慢机器不够、快机器白等）。
  **出处：Ditto `src/ExternalWindowTracker.cpp:187` 与 `:119`**
- **按键改用 `SendInput` + 扫描码**（`MapVirtualKey`），替代已废弃的 `keybd_event`。
  **出处：Ditto `src/SendKeys.cpp:326`**
- 修掉一个自己埋的坑：`INPUT` 是联合体，少写 `MOUSEINPUT` 会让 `sizeof(INPUT)` 变成 32
  而不是 40，`SendInput` 会直接失败 —— 已按真实定义补齐（自测断言 40）

### 交互
- **`Ctrl+1..9` 直接粘贴第 1..9 项，`Ctrl+0` 贴第 10 项**；**按住 Ctrl 时行首显示序号**
  把这组快捷键亮出来。**出处：PasteBar `ClipboardHistoryQuickPastePage.tsx:307`
  与 `ClipboardHistoryRow.tsx:702`（第 10 项显示 0）、Ditto `src/QListCtrl.cpp:610`**
- **多词搜索现在会高亮**：原来拿整串 `hello world` 去找，多词时永远匹配不到所以不高亮；
  改成按空白拆词（CopyQ `src/gui/filterlineedit.cpp:198` 的 AND 语义），
  整串命中就整串标蓝，否则标第一个命中的词

### 存储与清理
- **裁剪与清空都跳过收藏项**。**出处：Ditto `DatabaseUtilities.cpp:844`
  （跳过 `lDontAutoDelete`）、CopyQ `src/item/itemfactory.cpp:328`（`canDropItem` 豁免置顶）**
- 新增**捕获长度上下限**（`min_len` / `max_len`，0=不限），滤掉单字符噪声与超长正文。
  **出处：PasteBar `settingsStore.ts:285` 的 `clipTextMinLength` / `clipTextMaxLength`**
- 新增「清空历史时保留收藏项」开关，**出处：PasteBar `isKeepStarredOnClearEnabled`**

### 明确没抄的
- CopyQ 的「超 1KB 正文外置成独立文件（SHA256 内容寻址）」——我们用 JSON + 原子替换，
  只有文本条目，收益不抵复杂度，先不做
- Ditto 的 `SPI_SETFOREGROUNDLOCKTIMEOUT=0`（改全局前台锁定超时）—— 会短暂影响系统里
  所有程序，风险大于收益，改用 `AttachThreadInput` 达到同样效果
- 图片 / 文件剪贴板（三者都支持）—— 本项目定位是纯文本，暂不扩边界

## v1.3.3 · 右侧细滑动条

### 新增
- **列表右侧有了看得见的细滑动条**（8px 自绘，无两端箭头）：静默中灰、悬停变亮、拖动变蓝；
  支持拖滑块 / 点轨道跳转 / 在滑动条上滚轮；内容不满一屏时只留一条淡轨道、不显示滑块
- 主列表、设置窗口、文本变换窗口三处滚动条统一成同一款

### 修复
- **原来的滚动条其实一直看不见**：`canvas.pack(side='left', fill='both', expand=True)` 写在滚动条
  之前，canvas 的请求宽度 378px 已把容器占满，后 pack 的滚动条被压成 **1px**。
  现在改为滑动条先 pack 占位，canvas 再吃掉剩余宽度
- 文本变换窗口原来用的是 Windows 原生 Listbox 滚动条，深色主题下同样几乎不可见，已换掉
- 窗口销毁瞬间仍可能收到 `<Configure>`，自绘重绘会撞上已经销毁的 canvas，已整段容错

## v1.3.2 · 滚轮滑动

### 新增
- **列表支持鼠标滚轮上下滑动**，一格滚 3 行（Windows 惯例），滚到首尾自动停住不出现空白

### 修复
- **鼠标停在记录上滚轮完全没反应**：原来只把 `<MouseWheel>` 绑在 canvas 上，而鼠标压在条目
  （Frame 里的 Label）上时事件不会冒泡到 canvas，等于滚轮失效。现在条目内每个子控件都接管滚轮
- **触控板/高精度滚轮滚不动**：旧写法 `int(-1 * (delta / 120))` 对 `delta = 40` 这类非 120 倍数
  直接截断成 0，连滚几十次也不动一格。改为**增量累积**，攒够一格再滚
- **设置窗口装不下**：选项已到 12 行，固定 430 高度会把底部按钮挤掉。现在内容放进可滚动容器
  （滚轮 + 右侧细滚动条），「关闭 / 退出程序」固定在窗口底部始终可见
- **文本变换窗口的列表滚轮无效**：Windows 上 Tk 的 Listbox 不自带任何滚轮绑定，已手动接管
- C 版同样修正 `delta / 120` 的整数截断问题（`(delta * ITEM_H * 3) / 120`），并统一为一格 3 行

## v1.3.1 · 交互健壮性修复（面板点不动 / 关不掉）

### 修复
- **窗口卡在双屏缝隙点不到**：存档位置 `340x480+1876+331` 在主屏（0-2048）与副屏（2048 起）之间，
  一半在这半边、一半在那半边。现在启动与每次唤起都强制窗口**完整落在某一个显示器内**，
  拖出屏幕也会被拉回（`fit_geometry` / `clamp_to_screen`），修正后的位置立刻写回存档
- **弹窗模态锁导致主面板失去响应**：5 处 `grab_set()` 全部改成「置顶 + 抢焦点」，
  任何一个弹窗忘了关也不会再锁死主面板；`grab_release` 走安全版本（没 grab 过不会抛异常）
- **后台循环一处异常就整体停摆**：`poll_bg` 整个循环体包 try。这条链负责把粘贴后隐藏的面板叫回来、
  消费托盘菜单、记录前台窗口，以前断一次就表现为"点了没反应、关不掉"
- **粘贴后回不来**：新增 1.5 秒兜底检查（`_ensure_visible`），只要面板不是用户主动隐藏的就强制恢复
- **热键被占用直接放弃**：改为依次尝试 Ctrl+Shift+V → Alt+V → Ctrl+Alt+V，并把真正生效的那个写回设置
- **来源采集卡 UI 线程**：50ms 延迟重试挪到后台线程（`_late_source`），主线程不再被阻塞

### 新增（都是为了让"关不掉"这件事有明确出口）
- 设置里「点标题栏 ✕ 时」可选：隐藏到托盘（默认）/ 直接退出程序
- `Ctrl+Q` 直接退出；设置面板左下角红色「退出程序」按钮
- 托盘菜单新增「⟲ 面板找不到了？重置位置」
- 首次隐藏到托盘时弹气泡，说明怎么叫回来、怎么彻底退出

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
