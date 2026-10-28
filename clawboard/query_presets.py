"""Visible search controls edit existing query syntax without a second engine."""

TYPE_FILTERS = (('全部类型', None), ('普通文本', 'text'), ('图片', 'image'),
                ('链接', 'url'), ('文件', 'filelist'), ('多行文本', 'multiline'),
                ('JSON', 'json'))


def has_favorite(query):
    return any(token.lower() == 'is:fav' for token in query.split())


def set_filter(query, field, value=None):
    """Replace a positive UI-owned filter, retaining exclusions and keywords.

    Other is: flags are independent. Selecting a type/time intentionally replaces
    that positive family, matching the existing parser's space-delimited syntax.
    """
    if field not in ('type', 'time', 'favorite'):
        raise ValueError('unknown visual filter')
    prefix = 'is:fav' if field == 'favorite' else field + ':'
    tokens = [token for token in query.split()
              if not (token.lower() == prefix if field == 'favorite'
                      else token.lower().startswith(prefix))]
    if value:
        tokens.append('is:fav' if field == 'favorite' else prefix + str(value))
    return ' '.join(tokens)


def clear_visual_filters(query):
    for field in ('type', 'time', 'favorite'):
        query = set_filter(query, field)
    return query
