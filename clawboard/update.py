# -*- coding: utf-8 -*-
"""自动更新检查（P1-3）：**只提示 + 跳下载页**，不做静默下载/校验/换自身。

设计取舍（用户已拍板）
----------------------
- 自动化程度 = 「只提示，跳下载页」：查到新版只提示一次 + 用浏览器打开 Release 页，
  用户自己去下载安装。**不下载安装包、不校验 SHA256、不写 helper 换自身** ——
  风险最低，也无需处理签名 / 回滚 / 杀软误报。
- 检查时机 = ① 启动静默查一次（带 1 小时频率闸）；② 设置页手动「检查更新」按钮。

为什么单独成文件
----------------
联网属于「系统接入层」，塞进 app_services / app_ui 只会让它们更臃肿；而且本模块的
纯逻辑（parse_ver / is_newer / should_check）与取数（fetch_latest）都能**脱离 Tk 单测**。
本模块只依赖标准库（urllib / json / re / threading），是 clawboard 包里的叶子之一。

线程 / Tk 交互（关键，为什么这么写）
------------------------------------
Tk 不是线程安全的：**既不能在子线程里碰控件，也不能从子线程调 `root.after`**
（在没有 mainloop 的场景会直接抛 RuntimeError）。所以 `check_async()` 这样分工：
后台线程只做那个会阻塞的网络请求（`urlopen` 默认无超时是个坑，强制 timeout），
把结果写进一个普通 dict；**主线程**用 `root.after` 起一个短轮询把结果取回并回调 ——
回调 100% 跑在主线程上，调用方可以放心写 settings / 弹 tip / 改控件。
"""

import json
import re
import threading

try:
    import urllib.request as _url
except Exception:                    # pragma: no cover - 理论上有标准库就一定能 import
    _url = None

LATEST_API = 'https://api.github.com/repos/pay-and-gain/ClawBoard/releases/latest'

# GitHub API 对**不带 User-Agent** 的请求直接回 403，必须显式带 UA。
_UA = 'ClawBoard-Updater'
_ACCEPT = 'application/vnd.github+json'

# 启动检查的最小间隔：1 小时。用户频繁开关程序时，别把 GitHub 未认证的
# 60 次/小时配额打满（打满后连手动检查都会失败）。
CHECK_INTERVAL_MS = 60 * 60 * 1000

# 最近一次「查到的最新版本字符串」与「是否比本地新」的内存缓存。
# 设置对话框打开时直接读它 → 用户在启动那次检查后仍能找回入口（常驻显示）。
LATEST = None
LATEST_NEW = False

_NUM_RE = re.compile(r'(\d+)')


def parse_ver(s):
    """把 'v2.4.0' / '2.4.0' / 'release-2.4.0' 解析成可比较的整数元组。

    用正则在字符串里抽取**所有**数字段，就能同时兼容带 'v' 前缀、带额外文案的 tag，
    且逐段按整数比较，天然满足 2.10.0 > 2.9.9（字符串比会误判成 2.10.0 < 2.9.9）。
    非法 / 空 / 非 str 输入返回 None（调用方据此判定"不可比较"，不抛异常）。
    """
    if not isinstance(s, str):
        return None
    nums = _NUM_RE.findall(s)
    if not nums:
        return None
    return tuple(int(n) for n in nums)


def is_newer(remote, local):
    """远程版本是否**严格新于**本地。相同不算新；任一无法解析 → False（不抛）。

    比较前把两段补齐到等长（短的一端补 0），这样 '2.4' 与 '2.4.0' 视为相同版本，
    不会因为写法差异误报"有新版本"。
    """
    r = parse_ver(remote)
    l = parse_ver(local)
    if r is None or l is None:
        return False
    n = max(len(r), len(l))
    r = r + (0,) * (n - len(r))
    l = l + (0,) * (n - len(l))
    return r > l


def should_check(settings, now_ms, interval_ms=CHECK_INTERVAL_MS):
    """启动检查的频率闸（纯函数，便于单测）。

    返回 True 当且仅当：开关 `update_check` 为真，且距上次检查 `update_checked_at`
    已 ≥ interval_ms。手动检查**不走**这里（不受闸限制）。
    """
    if not settings.get('update_check', True):
        return False
    try:
        last = int(settings.get('update_checked_at') or 0)
    except Exception:
        last = 0
    try:
        return (int(now_ms) - last) >= int(interval_ms)
    except Exception:
        return True


def fetch_latest(timeout=5):
    """查询最新 release 的版本字符串（tag_name）。**任何失败都返回 None，绝不抛**。

    失败覆盖：无 urllib / DNS 失败 / 连接超时 / 非 200 / JSON 非法 / 缺 tag_name /
    tag 为空 —— 全部收敛成 None，让调用方（启动流程）无脑忽略即可。
    """
    if _url is None:
        return None
    resp = None
    try:
        req = _url.Request(LATEST_API, headers={'User-Agent': _UA, 'Accept': _ACCEPT})
        resp = _url.urlopen(req, timeout=timeout)
        status = getattr(resp, 'status', 200)
        if status != 200:
            return None
        raw = resp.read()
        data = json.loads(raw.decode('utf-8'))
        if not isinstance(data, dict):
            return None
        tag = data.get('tag_name')
        if not isinstance(tag, str) or not tag.strip():
            return None
        return tag.strip()
    except Exception:
        return None
    finally:
        try:
            if resp is not None:
                resp.close()
        except Exception:
            pass


def check_async(root, on_result, timeout=5):
    """后台线程查最新版；结果回**主线程**后回调 on_result。

    ⚠️ 必须在**主线程**调用本函数（启动流程、设置页按钮都在主线程）。

    线程 / Tk 交互（为什么这么绕）：Tk 不是线程安全的，既不能在子线程里碰控件，
    也**不能从子线程调 root.after** —— 在没有 mainloop 的场景（自测 / 某些启动早期）
    那样会直接抛 RuntimeError，回调永远送不到。所以反过来做：子线程只把结果写进一个
    普通 dict（写+读在 GIL 下是原子的），**主线程**用 root.after 起一个短轮询把结果取回，
    轮询命中后就地回调 —— 回调 100% 跑在主线程上。

    立即返回（不等网络）；返回后台线程对象（daemon，不阻止进程退出）。
    """
    box = {}

    def work():
        box['ver'] = fetch_latest(timeout=timeout)
        box['done'] = True

    t = threading.Thread(target=work, daemon=True)
    t.start()

    def poll():
        if box.get('done'):
            try:
                on_result(box.get('ver'))
            except Exception:
                pass
            return
        try:
            root.after(50, poll)
        except Exception:
            pass          # 窗口已销毁 / root 不可用：静默放弃，绝不影响主流程

    try:
        root.after(50, poll)
    except Exception:
        pass
    return t
