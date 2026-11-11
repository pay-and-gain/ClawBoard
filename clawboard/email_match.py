"""Email matching without retrying every suffix of a long word."""
import re


EMAIL_PATTERN = re.compile(r'[\w.+-]+@[\w-]+\.[\w.]{2,}')
_LOCAL_RUN = re.compile(r'[\w.+-]+')


def iter_email_matches(text):
    """Keep the original matching rule while advancing in linear time."""
    if '@' not in text:
        return
    cursor = 0
    while (local := _LOCAL_RUN.search(text, cursor)) is not None:
        match = EMAIL_PATTERN.match(text, local.start())
        if match is not None:
            yield match
            # A following address may start immediately after this match,
            # including inside the next local run (a@b.com+z@d.ef).
            cursor = match.end()
        else:
            # Every suffix in this run faces the same @ and domain. Retrying
            # them would reproduce the quadratic search of the old regex.
            cursor = local.end()


def search_email(text):
    return next(iter_email_matches(text), None)


def replace_emails(text, replacement):
    parts, cursor = [], 0
    for match in iter_email_matches(text):
        parts.extend((text[cursor:match.start()], replacement(match)))
        cursor = match.end()
    if not parts:
        return text
    parts.append(text[cursor:])
    return ''.join(parts)
