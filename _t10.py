# -*- coding: utf-8 -*-
"""实测：写入剪贴板再读回来，会不会凭空多出前后空格（读之前先存原内容，测完恢复）"""
import ClawBoard as C

old = C.clip_read()
print('原剪贴板内容:', repr((old or '')[:60]))

cases = [
    'hello',
    '中文测试abc',
    '多行\n第二行\n第三行',
    '  前面本来就有空格',
    'token abc123',
]
bad = []
for t in cases:
    if not C.clip_write(t):
        print('clip_write 失败:', repr(t))
        continue
    got = C.clip_read()
    ok = (got == t)
    print('%-24r -> %-28r %s' % (t, (got or '')[:40], 'OK' if ok else '*** 不一致 ***'))
    if not ok:
        bad.append((t, got))
        print('    前导字符: %r  原: %r' % ((got or '')[:3], t[:3]))
        print('    len %r -> %r' % (len(t), len(got or '')))

# 顺带看看 utf-16 编码本身
for t in ('hello', '中文'):
    b = t.encode('utf-16-le')
    print('utf16le(%r) = %s  长度 %d' % (t, b.hex(), len(b)))

if old is not None:
    C.clip_write(old)
    print('已恢复原剪贴板:', repr((C.clip_read() or '')[:60]))
print('结论:', '没有多余空格' if not bad else '发现 %d 处不一致' % len(bad))
