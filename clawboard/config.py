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
APP_VER = '1.6.0'

# frozen 时数据文件必须落在 exe 旁边（onefile 的临时目录退出即销毁）；
# 脚本运行时 BASE_DIR 是本包目录的上一级（即项目根，与 ClawBoard.py 同目录）。
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(_PKG_DIR)
DATA_FILE = os.path.join(BASE_DIR, 'ClawBoard数据.json')
ICON_FILE = os.path.join(BASE_DIR, 'ClawBoard.ico')
CRASH_LOG = os.path.join(BASE_DIR, 'crash.log')

# 保证 query.py / transform.py 与数据文件同目录可用（frozen 模式下同样如此）。
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

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

SCHEMA_VERSION = 3

# ---------- UI 等比缩放 ----------
# 用户可切换的整体缩放档位（等比例缩放字体 + 布局尺寸 + 最小尺寸）。
# 1.0 是默认；0.5 即"整体缩小一半"。切换后 rebuild UI 生效。
UI_SCALE_LEVELS = (0.5, 0.75, 1.0, 1.25, 1.5)
UI_SCALE = 1.0        # 当前缩放系数（档位切换时更新，rebuild 生效）


def scaled(base):
    """把 100% 基准下的布局像素尺寸按当前 UI 缩放系数等比缩放。

    只作用于「逻辑布局尺寸」（ITEM_H/TOOL_H/BAR_H/CARD_GAP/RESIZE_ZONE 等）；
    字体走 tk scaling（见 runtime.BASE_SCALING），DPI 由 dpi_scale 单独处理。
    两者独立相乘，保证整体等比缩放。
    """
    return max(1, int(base * UI_SCALE))


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


class SettingsDict(TypedDict, total=False):
    theme: str
    hotkey: str
    max_items: int
    listen: bool
    autopaste: bool
    mask_sensitive: bool
    skip_sensitive: bool
    show_time: bool
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
    _rz_dir: Optional[str] = None         # 正在进行的边缘拉伸方向（'n'/'se'/…），None=没在拉
    _hover_dir: Optional[str] = None      # 鼠标悬停的边缘方向（用于光标切换）
    _fx_supported: Optional[tuple] = None  # (圆角是否生效, 毛玻璃是否生效)，启动时探测一次
    _pv_job: Optional[str] = None          # 角落预览的防抖定时器 id
    _preview: Optional[object] = None      # 角落预览浮窗实例
