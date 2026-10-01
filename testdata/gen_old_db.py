# -*- coding: utf-8 -*-
"""生成 v1 格式的旧数据库样本（无任何 F0/F1/F2 字段），用于迁移实测"""
import json
import os
import random
import string

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'old_v1.json')
random.seed(42)
clip = []
for i in range(300):
    clip.append({
        'id': 'old_%d' % i,
        'text': ''.join(random.choice(string.ascii_letters + '中文测试内容') for _ in range(40)) + str(i),
        'time': '10-01 %02d:%02d' % (i % 24, i % 60),
    })
data = {
    'clip': clip,
    'groups': [{'name': '默认', 'items': [
        {'id': 'p_%d' % i, 'name': '常用语%d' % i, 'text': '常用内容 %d' % i}
        for i in range(20)]}],
    'gi': 0,
    'geom': '340x480+1000+500',
    # 故意不带 settings / schema_version，模拟 1.1.0 之前的老文件
}
with open(out, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=1)
print('生成 %s：clip=%d 条，phrase=%d 条' % (out, len(clip), 20))
