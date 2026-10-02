# -*- coding: utf-8 -*-
"""内容分类 + 文本 / 尺寸 / 长度工具。

纯函数层，无 tkinter / ctypes 依赖，全部可单测。
classify/looks_like_code/guess_lang/detect_content_type/to_plain 等判定逻辑与老版本逐字一致。
"""
import os
import re
import json
import html as _html

from clawboard.config import CLASSIFY_MAX

TYPE_ICON = {'url': '🔗', 'json': '{ }', 'multiline': '¶', 'text': '📝',
             'image': '🖼', 'filelist': '📁', 'empty': '∅'}


def type_icon(t):
    """徽章上的类型图标：比"文本/url/json"这类文字扫得快，也更省横向空间"""
    return TYPE_ICON.get((t or 'text').lower(), '📝')


# ---------- 内容自适应：判定"这到底复制的是什么" ----------
# 判定顺序与要点参考 EcoPaste(7.4k★) src-tauri/src/clipboard/detect.rs 和
# Mimer 的 Clip.swift：① 单一特征不算证据，要叠加（只有 { 不算代码）
# ② JSON 必须在代码**之前**判，且只认顶层 {}/[]（否则 "123"、'"abc"' 这类标量也会被
# json.loads 通过，JSON 就被当成普通文本了）
_URL_RE = re.compile(r'^(?:https?|ftp|file)://\S+$|^www\.\S+\.\S+$', re.I)
_MAIL_RE = re.compile(r'^[A-Za-z0-9._%+\-一-龥]+@[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+$')
_HEX_RE = re.compile(r'^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$')
_FN_COLOR_RE = re.compile(r'^(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch)\(.+\)$', re.I)
_FILELINE_RE = re.compile(r'(?::\d+){1,2}$')
_CODE_HEADS = ('func ', 'def ', 'const ', 'function ', 'import ', '#include', 'package ',
               '<?xml', '<!DOCTYPE', 'SELECT ', 'class ', 'public ', 'static ', 'var ',
               'let ', 'from ', 'if __name__', '#!/')


def looks_like_code(s):
    """证据叠加：光有 {} 不算，还得有 ; / = / 换行 / :" 佐证，
    或者是关键字开头，或者 ≥2 行有缩进（散文只缩进一行不算）"""
    if '{' in s and '}' in s and (';' in s or '=' in s or '\n' in s
                                  or (':' in s and '"' in s)):
        return True
    if '=>' in s or '</' in s or '/>' in s:
        return True
    if s.lstrip().startswith(_CODE_HEADS):
        return True
    lines = s.split('\n')
    if len(lines) >= 2 and sum(1 for L in lines if L[:1] in (' ', '\t')
                               and L.startswith(('  ', '\t'))) >= 2:
        return True
    return False


def guess_lang(s):
    """轻量语言猜测（无第三方库），只在多行代码上启用，避免单行误报"""
    h = s.lstrip()
    if h.startswith('#!'):
        return 'python' if 'python' in h else ('shell' if ('bash' in h or 'sh' in h) else 'shell')
    if h.startswith('<?php'):
        return 'php'
    if '<!DOCTYPE html' in h or re.search(r'</(div|span|body|html)>', s, re.I):
        return 'html'
    if re.search(r'^\s*(def |class |import |from [\w.]+ import)', s, re.M):
        return 'python'
    if re.search(r'\b(function|const |let |var |=>)\b', s):
        return 'javascript'
    if re.search(r'#include|std::', s):
        return 'cpp'
    if re.search(r'^\s*SELECT .+ FROM', s, re.I | re.M):
        return 'sql'
    return 'code'


def classify(text):
    """返回 (kind, meta)。kind ∈ url / email / color / path / json / code / multiline / text
    纯函数、可单测；UI 只是它的消费者。"""
    s = (text or '').strip()
    if not s:
        return 'text', {}
    if len(s) > CLASSIFY_MAX:
        return 'text', {}
    # 1. 路径（允许 path:行号 这种形态）
    core = _FILELINE_RE.sub('', s)
    if len(core) < 4096:
        p = os.path.expanduser(core)
        if (core.startswith(('/', '~', './', '../')) or os.path.isabs(core)) \
                and os.path.exists(p):
            return 'path', {'basename': os.path.basename(core.rstrip('/')) or core}
    # 2. 单行串才可能是 url / email / 色值（要求整串无空白，能挡掉绝大多数误判）
    if ' ' not in s and '\n' not in s:
        if _URL_RE.match(s):
            m = re.match(r'^(?:https?|ftp|file)://([^/\s?#]+)', s)
            return 'url', {'host': m.group(1) if m else s}
        if _MAIL_RE.match(s):
            return 'email', {}
    # 颜色单独判：rgb(30, 32, 39) 里带空格，不能受"整串无空白"那条限制。
    # 正则要求首尾完整匹配，误判风险很低
    if _HEX_RE.match(s) or _FN_COLOR_RE.match(s):
        return 'color', {}
    # 3. JSON：首字符预筛（省掉一次全量解析）+ 顶层必须是 dict/list
    if s[0] in '{[' and len(s.encode('utf-8', 'replace')) <= 100000:
        try:
            v = json.loads(s)
        except ValueError:
            pass
        else:
            if isinstance(v, (dict, list)):
                return 'json', {}
    # 4. 代码
    if looks_like_code(s):
        return 'code', {'lang': guess_lang(s)}
    return ('multiline' if '\n' in s else 'text'), {}


KIND_LABEL = {'url': '链接', 'email': '邮箱', 'color': '颜色', 'path': '路径',
              'json': 'JSON', 'code': '代码', 'multiline': '多行', 'text': '文本'}
KIND_ICON = {'url': '🔗', 'email': '✉', 'color': '🎨', 'path': '📁',
             'json': '{ }', 'code': '</>', 'multiline': '¶', 'text': '📝'}


def kind_icon(k):
    return KIND_ICON.get(k, '📝')


def detect_content_type(text):
    """我们只监听 CF_UNICODETEXT，这里判定文本的形态用于徽章与 type: 过滤"""
    t = (text or '').strip()
    if not t:
        return 'empty'
    if re.match(r'^https?://\S+$', t) and ' ' not in t:
        return 'url'
    try:
        if (t.startswith('{') and t.endswith('}')) or (t.startswith('[') and t.endswith(']')):
            json.loads(t)
            return 'json'
    except Exception:
        pass
    if '\n' in t:
        return 'multiline'
    return 'text'


def byte_size(text):
    try:
        return len(text.encode('utf-8'))
    except Exception:
        return 0


def human_size(n):
    if n < 1024:
        return '%d B' % n
    if n < 1024 * 1024:
        return '%.1f KB' % (n / 1024.0)
    return '%.1f MB' % (n / 1048576.0)


def to_plain(text):
    """F6：剥成纯文本。<br>/<p>/<li>/表格 要变成换行或制表符，实体要解码"""
    s = text or ''
    if re.search(r'<\s*(br|p|div|li|tr|table|h[1-6]|td|th)', s, re.I):
        s = re.sub(r'<\s*br\s*/?\s*>', '\n', s, flags=re.I)
        s = re.sub(r'</\s*(p|div|li|tr|h[1-6])\s*>', '\n', s, flags=re.I)
        s = re.sub(r'</\s*t[dh]\s*>', '\t', s, flags=re.I)
        s = re.sub(r'<[^>]+>', '', s)
        s = _html.unescape(s)
    s = s.replace('\xa0', ' ')
    s = s.replace('\r\n', '\n').replace('\r', '\n')
    s = re.sub(r'[ \t]+\n', '\n', s)
    s = re.sub(r'\n{3,}', '\n\n', s)
    s = '\n'.join(x.rstrip() for x in s.split('\n'))
    return s.strip('\n')


def length_filtered(txt, lo, hi):
    """按长度上下限判断是否入库，返回提示语；None 表示放行。
    对应 PasteBar settingsStore.ts:285 的 clipTextMinLength / clipTextMaxLength ——
    一个滤噪声（单个字母、误触），一个挡超长（几 MB 的日志正文）。"""
    n = len(txt or '')
    if lo and n < lo:
        return '内容只有 %d 字符（下限 %d），按设置不入库' % (n, lo)
    if hi and n > hi:
        return '内容有 %d 字符（上限 %d），按设置不入库' % (n, hi)
    return None


def crop_items(items, lim):
    """裁剪到 lim 条：从最旧的一端删，但收藏项永不自动删。
    Ditto DatabaseUtilities.cpp:844 的 RemoveOldEntries 会跳过 lDontAutoDelete，
    CopyQ itemfactory.cpp:328 的 cropToSize 用 canDropItem 豁免置顶项 —— 同一个道理。"""
    if len(items) <= lim:
        return items
    return list(items[:lim]) + [x for x in items[lim:] if x.get('fav')]


def preview(text, n=90):
    t = ' '.join((text or '').split())
    return t if len(t) <= n else t[:n] + '…'
