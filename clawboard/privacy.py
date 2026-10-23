"""Pure sensitive-content policy, shared by every display surface."""
import re
from clawboard.config import EMAIL_SCAN_MAXLEN

SENS_PATTERNS = [
    ('身份证', re.compile(r'(?<!\d)\d{17}[\dXx](?!\d)')),
    ('银行卡', re.compile(r'(?<!\d)\d{16,19}(?!\d)')),
    ('手机号', re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)')),
    ('邮箱', re.compile(r'[\w.+-]+@[\w-]+\.[\w.]{2,}')),
    ('Token', re.compile(r'(?:sk-|ghp_|xox[baprs]-|Bearer\s+)[A-Za-z0-9_\-]{8,}')),
    ('密码', re.compile(r'(?i)(password|passwd|pwd|密码|口令)\s*[:：=]\s*\S{4,}')),
]


# 每条敏感规则可带一个「廉价前置判据」：跑正则前先做 O(n) 的 `in` 预判，命中才跑正则。
# 为什么必须：email 正则 [\w.+-]+@... 在「长且**不含 @**」的文本上是 O(n²) —— 每个起点都把
# [\w.+-]+ 贪婪匹配到底、再逐字回溯找 @（实测 60K 字符≈6.6s、200K≈130s）。补记把它搬到了
# 启动主线程 → 会假死；实时复制同样中招。'@' 缺失时正则必不可能命中，预筛**零功能损失**。
# 逐条实测：身份证/银行卡/手机号是定长数字+边界（线性），Token/密码是字面前缀（线性），
# 均无需预筛（见 tests/_t42.py 的耗时回归）。
_SENS_PREFILTER = {'邮箱': '@'}
# 含 '@' 的**超长**文本仍是 O(n²)（'@' 只是缩小平方路径的范围、没消除）。超过该长度即跳过
# email 正则，为最坏耗时兜底。代价见 config.EMAIL_SCAN_MAXLEN 注释（安全相关、非静默）。
_SENS_MAXLEN = {'邮箱': EMAIL_SCAN_MAXLEN}


def scan_sensitive(text):
    try:
        text = text or ''
        out = []
        for name, pat in SENS_PATTERNS:
            need = _SENS_PREFILTER.get(name)
            if need and need not in text:
                continue
            cap = _SENS_MAXLEN.get(name, 0)
            if cap and len(text) > cap:
                continue
            if pat.search(text):
                out.append(name)
        return out
    except Exception:
        return []


def mask_text(text, hits):
    def rep(m):
        s = m.group(0)
        return s[:3] + '*' * max(3, len(s) - 5) + s[-2:]
    out = text
    for name, pat in SENS_PATTERNS:
        if name in hits:
            out = pat.sub(rep, out)
    return out


def display_text(text, hits=None, *, masked=True, reveal=False):
    """Keep raw text for paste/export; every passive preview uses this boundary."""
    if not masked or reveal:
        return text or ""
    hits = scan_sensitive(text) if hits is None else hits
    return mask_text(text or "", hits) if hits else (text or "")
