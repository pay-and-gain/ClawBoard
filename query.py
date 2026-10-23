# -*- coding: utf-8 -*-
"""兼容入口；搜索实现与缓存位于独立领域模块 clawboard.search。"""
from clawboard.search import (
    UNIT, SIZE_UNIT, KNOWN_TYPES, KNOWN_IS, SYNTAX_HELP,
    day_range, parse_date, parse_time_token, parse_size_token, parse,
    compile_pred, match, SearchService, _is_hit,
    re, time, to_pinyin, to_pinyin_initials, normalize_tag,
)
