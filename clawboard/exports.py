"""Export formatting and an injected atomic filesystem boundary, with no UI.

The adapter snapshots records on the UI thread; workers stream these values to
the destination without reading App state, widgets, or global data directories.
"""
import csv
import io
import json
import os
from pathlib import Path
import re
import tempfile
import time
import uuid

from clawboard.config import SCHEMA_VERSION
from clawboard.timefmt import full_time


class ExportCancelled(Exception):
    """The destination was not committed; any partial temp file is removed."""


def new_export_path(directory, fmt, *, prefix='导出', now=None):
    if fmt not in ('txt', 'csv', 'json', 'md'):
        raise ValueError('不支持的导出格式：' + str(fmt))
    stamp = time.strftime('%Y%m%d-%H%M%S', time.localtime(time.time() if now is None else now))
    return Path(directory) / ('%s_%s_%s.%s' % (prefix, stamp, uuid.uuid4().hex[:8], fmt))


def _encoded_chunks(items, fmt, *, now=None, schema_version=SCHEMA_VERSION):
    if fmt == 'txt':
        for index, item in enumerate(items, 1):
            if index > 1:
                yield b'\n'
            yield ('[%d] %s | %s | %s\n%s\n' % (
                index, full_time(item.get('created_at')),
                item.get('source_app') or 'unknown', item.get('content_type') or 'text',
                item.get('text', ''))).encode('utf-8')
    elif fmt == 'csv':
        yield b'\xef\xbb\xbf'
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(['时间(本地)', '来源应用', '类型', '大小(字节)', '内容'])
        yield buffer.getvalue().encode('utf-8')
        for item in items:
            buffer.seek(0)
            buffer.truncate(0)
            writer.writerow([full_time(item.get('created_at')),
                             item.get('source_app') or 'unknown', item.get('content_type') or 'text',
                             item.get('content_size') or 0, item.get('text', '').replace('\n', '\\n')])
            yield buffer.getvalue().encode('utf-8')
    elif fmt == 'json':
        payload = {'version': schema_version, 'items': items}
        for chunk in json.JSONEncoder(ensure_ascii=False, indent=1, allow_nan=False).iterencode(payload):
            yield chunk.encode('utf-8')
    elif fmt == 'md':
        stamp = time.strftime('%F %T', time.localtime(time.time() if now is None else now))
        yield ('# 剪贴板导出 %s\n' % stamp).encode('utf-8')
        for item in items:
            text = item.get('text', '')
            # A longer fence keeps embedded Markdown fences inside the content.
            longest = max((len(part) for part in re.findall(r'`+', text)), default=0)
            fence = '`' * max(3, longest + 1)
            yield ('\n## %s · %s\n\n%s\n%s\n%s\n' % (
                full_time(item.get('created_at')), item.get('source_app') or 'unknown',
                fence, text, fence)).encode('utf-8')
    else:
        raise ValueError('不支持的导出格式：' + str(fmt))


def render_items(items, fmt, *, now=None, schema_version=SCHEMA_VERSION):
    """Convenient pure formatter; disk exports stream these same chunks."""
    return b''.join(_encoded_chunks(items, fmt, now=now, schema_version=schema_version))


def _write_chunks(path, chunks, cancelled=None):
    target = Path(path)
    temporary = None
    check = cancelled or (lambda: False)
    try:
        if check():
            raise ExportCancelled()
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.' + target.name + '.', suffix='.tmp', dir=target.parent)
        with os.fdopen(fd, 'wb') as stream:
            for chunk in chunks:
                if check():
                    raise ExportCancelled()
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if check():
            raise ExportCancelled()
        os.replace(temporary, target)
        return target
    finally:
        if temporary and os.path.exists(temporary):
            try:
                os.unlink(temporary)
            except OSError:
                pass


def write_items(path, items, fmt, *, now=None, schema_version=SCHEMA_VERSION, cancelled=None):
    return _write_chunks(path, _encoded_chunks(items, fmt, now=now, schema_version=schema_version), cancelled)


def write_payload(path, payload, *, cancelled=None):
    chunks = (chunk.encode('utf-8') for chunk in
              json.JSONEncoder(ensure_ascii=False, indent=1, allow_nan=False).iterencode(payload))
    return _write_chunks(path, chunks, cancelled)
