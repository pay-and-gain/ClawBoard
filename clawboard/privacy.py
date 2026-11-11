"""Pure sensitive-content policy, shared by every display surface."""
import re
from clawboard.email_match import EMAIL_PATTERN, replace_emails, search_email

SENS_PATTERNS = [
    ('身份证', re.compile(r'(?<!\d)\d{17}[\dXx](?!\d)')),
    ('银行卡', re.compile(r'(?<!\d)\d{16,19}(?!\d)')),
    ('手机号', re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)')),
    ('邮箱', EMAIL_PATTERN),
    ('Token', re.compile(r'(?:sk-|ghp_|xox[baprs]-|Bearer\s+)[A-Za-z0-9_\-]{8,}')),
    ('密码', re.compile(r'(?i)(password|passwd|pwd|密码|口令)\s*[:：=]\s*\S{4,}')),
]


def scan_sensitive(text):
    try:
        text = text or ''
        out = []
        for name, pat in SENS_PATTERNS:
            match = search_email(text) if name == '邮箱' else pat.search(text)
            if match:
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
            out = replace_emails(out, rep) if name == '邮箱' else pat.sub(rep, out)
    return out


def display_text(text, hits=None, *, masked=True, reveal=False):
    """Keep raw text for paste/export; every passive preview uses this boundary."""
    if not masked or reveal:
        return text or ""
    hits = scan_sensitive(text) if hits is None else hits
    # Older long records may already have another sensitive label but lack
    # email metadata. Passive previews must not trust that incomplete cache.
    if '邮箱' not in hits and search_email(text or ''):
        hits = [*hits, '邮箱']
    return mask_text(text or "", hits) if hits else (text or "")
