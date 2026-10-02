# -*- coding: utf-8 -*-
"""主题配色：DARK/LIGHT/T + 自定义背景色推导。

T 是可原地读写（禁止重绑定）的跨模块共享 dict，测试与业务代码都通过它共享当前配色。
"""

DARK = dict(bg='#1e2027', panel='#252831', card='#2c303b', card_h='#39404f',
            card_s='#33465f', card_m='#3d4f6b', fg='#e6e8ee', fg2='#9aa0ad',
            acc='#4f8cff', acc2='#2f6fe0', line='#333844', danger='#e05c5c')
LIGHT = dict(bg='#f4f5f8', panel='#e9ebf0', card='#ffffff', card_h='#eef1f7',
             card_s='#dbe7ff', card_m='#e3edff', fg='#1f2430', fg2='#6b7280',
             acc='#2563eb', acc2='#1d4ed8', line='#d6dae3', danger='#c0392b')
T = dict(DARK)


def set_theme(name):
    T.clear()
    T.update(DARK if name == 'dark' else LIGHT)


def _rgb(c):
    c = (c or '').lstrip('#')
    if len(c) != 6:
        return None
    try:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def shade(c, k):
    """把颜色整体乘 k（>1 变亮、<1 变暗），各通道夹在 0-255"""
    t = _rgb(c)
    if not t:
        return c
    f = lambda v: max(0, min(255, int(round(v * k))))
    return '#%02x%02x%02x' % tuple(f(v) for v in t)


def is_dark(c):
    """按亮度判断深浅，用来决定文字该用浅色还是深色"""
    t = _rgb(c)
    if not t:
        return True
    return (t[0] * 299 + t[1] * 587 + t[2] * 114) / 1000.0 < 128


def apply_theme(st):
    """应用主题，并按自定义背景色推导出整套配色。
    用户只选一个背景色，剩下的面板/卡片/边框由它按比例推出来，
    文字色按背景深浅自动选 —— 免得选了白底却配白字。"""
    set_theme(st.get('theme', 'dark'))
    c = (st.get('bg_color') or '').strip()
    if not c or not _rgb(c):
        return
    T['bg'] = c
    if is_dark(c):
        T.update(panel=shade(c, 1.18), card=shade(c, 1.42), card_h=shade(c, 1.72),
                 card_s=shade(c, 1.55), card_m=shade(c, 1.62), line=shade(c, 1.70),
                 fg='#e6e8ee', fg2='#9aa0ad')
    else:
        T.update(panel=shade(c, 0.95), card=shade(c, 1.06), card_h=shade(c, 0.96),
                 card_s=shade(c, 0.86), card_m=shade(c, 0.89), line=shade(c, 0.85),
                 fg='#1f2430', fg2='#6b7280')
