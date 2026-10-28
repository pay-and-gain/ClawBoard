# -*- coding: utf-8 -*-
"""集中配置：DEFAULT_SETTINGS + 全部常量 + 路径 + 数据契约。

本模块是 clawboard 包内唯一「无包内依赖」的叶子，其余模块一律从这里引用魔法值；
任何模块都不得反向 import 本模块以外的 clawboard 模块。
"""
import os
import sys
from dataclasses import dataclass
from typing import List, Optional, TypedDict

APP_NAME = 'ClawBoard'
APP_VER = '4.0.0'

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, 'frozen', False):
    _EXE_DIR = os.path.dirname(sys.executable)
else:
    # 脚本运行时「exe 目录」= 本包目录的上一级（项目根，与 ClawBoard.py 同目录）
    _EXE_DIR = os.path.dirname(_PKG_DIR)


def _writable(d):
    """目录是否真的可写。Program Files 对普通用户只读，必须探测而不是猜。"""
    try:
        p = os.path.join(d, '.__wtest')
        with open(p, 'w') as f:
            f.write('1')
        os.remove(p)
        return True
    except Exception:
        return False


def _pick_data_dir():
    """数据目录：便携优先，写不进去才回退到 %APPDATA%。

    - 脚本运行：项目根（开发态，肯定可写）
    - frozen 且 exe 同目录可写（放桌面 / U 盘 / D 盘）：仍走便携模式，数据跟 exe 走
    - frozen 且 exe 同目录不可写（装到 Program Files）：回退 %APPDATA%\\ClawBoard
      否则保存会静默失败 —— 用户以为记着历史，其实一条都没落盘。
    """
    if not getattr(sys, 'frozen', False):
        return _EXE_DIR
    if _writable(_EXE_DIR):
        return _EXE_DIR
    appdata = os.environ.get('APPDATA') or os.path.expanduser('~')
    d = os.path.join(appdata, 'ClawBoard')
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


BASE_DIR = _pick_data_dir()
DATA_FILE = os.path.join(BASE_DIR, 'ClawBoard数据.json')
CRASH_LOG = os.path.join(BASE_DIR, 'crash.log')
# onefile resources live in PyInstaller's bundle; installed directories may be
# read-only, so tray setup must not generate an icon beside Program Files/exe.
ICON_FILE = os.path.join(getattr(sys, '_MEIPASS', _EXE_DIR), 'ClawBoard.ico')
UI_ASSET_DIR = (os.path.join(sys._MEIPASS, 'ui-assets') if getattr(sys, 'frozen', False)
                else os.path.join(_EXE_DIR, 'packaging', 'ui-assets'))

# 保证 query.py / transform.py 与数据文件同目录可用（frozen 模式下同样如此）。
if _EXE_DIR not in sys.path:
    sys.path.insert(0, _EXE_DIR)

FONT = ('Microsoft YaHei UI', 9)
FONT_B = ('Microsoft YaHei UI', 9, 'bold')
FONT_SM = ('Microsoft YaHei UI', 8)
FONT_TITLE = ('Microsoft YaHei UI', 10, 'bold')
FONT_MONO = ('Consolas', 9)      # 代码 / JSON 用等宽，一眼看出"这是代码不是散文"

ITEM_H = 52          # 虚拟列表固定行高（含卡片之间的空隙）
CARD_GAP = 4         # 卡片上下留出的空隙，条目之间不再糊成一片
WHEEL_LINES = 3      # 滚轮一格滚几行（Windows 惯例是 3）
BAR_H = 34            # 标题栏高度（也是折叠后露出来的高度），比原来 30 更好点
TOOL_H = 48           # 工具条高度。40 时按钮(25px)+pady(14px)=39 只剩 1px 余量，
                      # 125% DPI 下视觉上按钮紧贴上下边缘、像被切掉（用户截图反馈）。
                      # 48 - 25 - 9*2 = 5px，上下各留 2.5px 呼吸空间
RESIZE_ZONE = 6       # 窗口边缘"随意拉伸"热区宽度（px）：鼠标进入即变为拉伸光标
MIN_W, MIN_H = 280, 340   # 面板最小尺寸。再小的话：标题栏 30 + 标签 32 + 工具条 36 一扣，
                          # 留给列表的宽度会被徽章/序号列吃掉，正文只剩几十像素 —— 看起来像"没有内容"
MAX_TEXT = 200000    # 单条文本入库上限（字符）

# email 正则 [\w.+-]+@... 在「长且不含 @」的文本上是 O(n²)（每个起点都把 [\w.+-]+ 贪婪匹配
# 到底再回溯找 @）。补记把它搬到了启动主线程 → 必须兜底。超过该长度的文本跳过 email 识别。
# ⚠️ 这是**安全相关**取舍：超长文本里的邮箱将不再触发 skip_sensitive / mask_sensitive；
# 详见 clipboard.scan_sensitive 的注释。scan_sensitive 与 detect_tags 共用此值（单一来源）。
EMAIL_SCAN_MAXLEN = 10000

SCHEMA_VERSION = 3

# ---------- UI 等比缩放 ----------
# 用户可切换的整体缩放档位（等比例缩放字体 + 布局尺寸 + 最小尺寸）。
# 1.0 是默认；0.5 即"整体缩小一半"。切换后 rebuild UI 生效。
UI_SCALE_LEVELS = (0.5, 0.75, 1.0, 1.25, 1.5)
UI_SCALE = 1.0        # 当前缩放系数（档位切换时更新，rebuild 生效）
DPI_SCALE = 1.0       # 当前主面板所在屏幕；只在主线程稳定切屏时更新，不存入数据文件。


def scaled(base):
    """把 100% 基准下的布局像素尺寸按当前 UI 缩放系数等比缩放。

    布局像素 = 逻辑尺寸 × 所在屏 DPI × 用户档位；字体用相同两系数更新 tk scaling。
    最小窗口尺寸另从逻辑尺寸换算，不能对 scaled() 的结果再乘 DPI。
    """
    return max(1, int(base * UI_SCALE * DPI_SCALE))


def rotate_log_if_needed(path, max_bytes=512 * 1024, keep_bytes=256 * 1024):
    """日志文件超过上限时截断，只保留最近（尾部）一段。

    crash.log 会无限增长（每次启动/异常都 append），不设上限的话用几个月就能长到
    几十 MB。超过 max_bytes 时截断到 keep_bytes，保留最近诊断、丢掉最旧记录。
    """
    try:
        if os.path.exists(path) and os.path.getsize(path) > max_bytes:
            with open(path, 'rb') as f:
                f.seek(max(0, os.path.getsize(path) - keep_bytes))
                tail = f.read()
            with open(path, 'wb') as f:
                f.write(b'...[log truncated, keeping recent tail]...\n' + tail)
    except Exception:
        pass

# 超长内容直接降级为纯文本，别在正则上浪费时间（classify 使用）。
CLASSIFY_MAX = 128000

DEFAULT_SETTINGS = dict(theme='dark', hotkey='ctrl+shift+v', max_items=500,
                        listen=True, autopaste=True, mask_sensitive=True,
                        skip_sensitive=False, show_time=False, record_title=False,
                        show_source=False, show_size=False,
                        group_by_time=False, edge_hide=False, edge_delay=8,
                        close_action='hide')      # hide=隐藏到托盘 / quit=直接退出
# v1.4.0 补齐项（对照 Ditto / PasteBar 的同类设置）
DEFAULT_SETTINGS.update(
    ignore_apps='keepass,1password,bitwarden,lastpass',   # 通配名单，命中不记录
    ignore_titles='',                                     # 正则名单（窗口标题）
    min_len=1,          # 短于这个长度不入库（0=不限），滤掉单个字母之类的噪声
    max_len=0,          # 长于这个长度不入库（0=不限，仍受 MAX_TEXT 硬上限保护）
    smart_private=True,  # 遵守 Windows「别记录我」剪贴板标记
    keep_on_clear=True,  # 清空历史时保留收藏项
    # 从 PDF/网页/代码复制的文本常带前导缩进，而列表预览把它压平显示，
    # 粘出去却带着 → 看着像凭空多了空格。默认在粘贴时去掉首尾空白。
    trim_paste=True,
    collapsed=False,     # 上次退出时是不是折叠着的
    collapse_to_corner=True,   # 折叠时贴到屏幕右下角（留在原处太突兀）
    bg_color='',         # 自定义背景色，空=用主题默认
    ui_scale=1.0,        # UI 等比缩放档位（0.5/0.75/1.0/1.25/1.5）
    rounded=True,        # 窗口圆角（Win11 质感，老系统自动静默忽略）
    frosted=True,        # Acrylic 毛玻璃背景（观感依赖桌面壁纸，可在设置里关掉）
    show_toast=True,     # 复制后弹出提示浮窗（行数/字符数 + 预览）
    toast_ms=1800,       # 提示浮窗停留毫秒数
    show_preview=True,   # 键盘浏览（↑↓）时在角落显示选中条目的完整内容
    trigger_enabled=False,  # 触发词快速粘贴（全局键盘钩子，默认关，需手动开启）
    # P1-2 音效反馈：盲操时的听觉确认。两个开关相互独立、默认都关
    #（不想被声音打扰的用户保持静音；需要的人各取所需）。
    sound_copy=False,    # 复制音：剪贴板确实记下一条新内容时播放
    sound_paste=False,   # 粘贴音：粘贴动作成功执行后播放
    # P1-3 自动更新：只提示 + 跳下载页（不静默下载/不换自身）。字段可选、向后兼容。
    update_check=True,   # 启动时静默检查一次更新（默认开；带 1 小时频率闸）
    update_checked_at=0,  # 上次检查的毫秒时间戳（0=从未查过），用于频率闸
)
# 开机自启不存配置文件，直接读注册表真实状态，避免"设置里开着其实没开"


class ClipItemDict(TypedDict, total=False):
    """与 norm_item()/validate() 产出的 JSON 字段一一对应，字段名与老数据完全一致。

    注意：这是纯静态类型契约，运行时仍用 dict，保证 JSON 完全兼容。
    """
    id: str
    text: str
    name: str
    created_at: int
    updated_at: Optional[int]
    last_used_at: Optional[int]
    seq: int
    source_app: str
    source_title: Optional[str]
    copy_count: int
    fav: int
    meta: Optional[str]
    sens: Optional[List[str]]
    is_estimated: int
    content_type: str
    content_size: int
    time: str
    kind_auto: str          # 渲染缓存（内存态）
    mask_off: bool          # 内存态
    pinned: int
    use_count: int
    tags: List[str]
    trigger: str
    image_path: str
    image_w: int
    image_h: int


class SettingsDict(TypedDict, total=False):
    theme: str
    hotkey: str
    max_items: int
    listen: bool
    autopaste: bool
    mask_sensitive: bool
    skip_sensitive: bool
    show_time: bool
    show_source: bool
    show_size: bool
    record_title: bool
    group_by_time: bool
    edge_hide: bool
    edge_delay: int
    close_action: str
    ignore_apps: str
    ignore_titles: str
    min_len: int
    max_len: int
    smart_private: bool
    keep_on_clear: bool
    trim_paste: bool
    collapsed: bool
    collapse_to_corner: bool
    bg_color: str
    sound_copy: bool
    sound_paste: bool
    update_check: bool
    update_checked_at: int


class AppDataDict(TypedDict, total=False):
    clip: List[ClipItemDict]
    groups: List[dict]      # [{'name': str, 'items': [ClipItemDict]}]
    gi: int
    geom: Optional[str]
    settings: SettingsDict
    schema_version: int
    search_history: List[str]


@dataclass
class AppState:
    """运行时状态唯一初始化来源（R3 统一状态管理）。

    所有字段在此有默认值，ClawBoard.__init__ 构造期一次性复制到 self，
    任何方法都不得再引入"只在某分支赋值"的新实例属性。
    """
    tab: str = 'clip'
    sel_clip: Optional[str] = None
    sel_phrase: Optional[str] = None
    collapsed: bool = False
    _restore: Optional[str] = None        # 折叠前"展开后回哪"（hotfix 真崩溃点 A）
    prev_hwnd: Optional[int] = None
    save_timer: Optional[str] = None
    _need_show: bool = False
    _tray_menu: bool = False
    hidden: bool = False
    hotkey_ok: bool = False
    hotkey_fallback: bool = False
    _hk_down: bool = False
    _paste_fail: bool = False
    _anchor_idx: Optional[int] = None
    search_err: str = ''
    _told_tray: bool = False
    _edge_hidden: bool = False
    _edge_tick: int = 0
    _edge_side: Optional[str] = None
    _edge_pos: Optional[tuple] = None
    _edge_mon: Optional[tuple] = None     # 收起时所在显示器矩形（碰边滑出按它判定，多屏必需）
    _rz_dir: Optional[str] = None         # 正在进行的边缘拉伸方向（'n'/'se'/…），None=没在拉
    _hover_dir: Optional[str] = None      # 鼠标悬停的边缘方向（用于光标切换）
    _fx_supported: Optional[tuple] = None  # (圆角是否生效, 毛玻璃是否生效)，启动时探测一次
    _pv_job: Optional[str] = None          # 角落预览的防抖定时器 id
    _preview: Optional[object] = None      # 角落预览浮窗实例
    _dpi_scale: float = 1.0
    _dpi_pending: Optional[float] = None
    _dpi_ready: bool = False              # 首次恢复的 geom 已是物理像素，不再乘一次屏幕比例。
    _dpi_deferred_view: Optional[dict] = None
    # ---- 置顶状态机（全屏程序前台时面板不再置顶）----
    # 拆分三件事，互不混淆：① 用户意图（toggle_pin 改）；② 全屏抑制（只改实际属性）；
    # ③ 实际写进去的值（去重）。把它们混成一个 attributes 读写，会出现
    # "用户取消置顶 → 进游戏 → 退出游戏被强行改回置顶" 这种把用户意图吃掉的问题。
    _topmost_user: bool = True             # 用户期望的置顶意图（全屏抑制不改它）
    _user_pulled: bool = False             # 用户是否「主动呼出」了面板（热键/托盘/重置位置）；隐藏时清除
    _fg_fullscreen: bool = False           # 前台窗口当前是否全屏（poll_bg 每轮刷新）
    _topmost_yield: bool = False           # 粘贴「让位」进行中：临时关置顶，粘完由 _restore_topmost 清除
    _topmost_applied: Optional[bool] = None  # 上次真正写进 -topmost 的值（去重，避免每 120ms 空设）
