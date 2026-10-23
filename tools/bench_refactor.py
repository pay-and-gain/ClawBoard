"""开发工具，不参与产品运行：compare synthetic CPU workloads on two source trees.

The baseline must be the unmodified upstream 6a10466 source tree. Measurements
cover CPU work only; they do not measure Windows desktop latency or frame rate.
"""
import argparse
import ast
import io
import json
import pathlib
import platform
import statistics
import struct
import subprocess
import sys
import time
import zlib

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--baseline', type=pathlib.Path, required=True)
parser.add_argument('--candidate', type=pathlib.Path,
                    default=pathlib.Path(__file__).resolve().parents[1])
parser.add_argument('--output', type=pathlib.Path,
                    default=pathlib.Path('performance-comparison.json'))
args = parser.parse_args()
OLD = args.baseline.resolve()
NEW = args.candidate.resolve()
sys.path.insert(0, str(NEW))
from clawboard.image import dib_to_png, png_to_dib
from clawboard.viewmodels import ViewProjection


def measure(fn, repeats=3):
    elapsed = []
    for _ in range(repeats):
        start = time.perf_counter()
        result = fn()
        elapsed.append((time.perf_counter() - start) * 1000)
    return {'median_ms': round(statistics.median(elapsed), 3),
            'samples_ms': [round(x, 3) for x in elapsed]}, result


script = '''
import sys,time,json,statistics
sys.path.insert(0,sys.argv[1])
import query
runner=query.match
if sys.argv[2]=='new':
 from clawboard.search import SearchService
 runner=SearchService().match
seed='项目账号 文档日志 hello world data entry 1234567890 '
text=(seed*60)[:2000]
items=[{'id':str(i),'text':text+str(i),'source_app':'chrome'} for i in range(500)]
out={}
for q in ('app:chrome','hello','zhanghao'):
 t=time.perf_counter();got=runner(q,items);cold=(time.perf_counter()-t)*1000
 samples=[]
 for _ in range(3):
  t=time.perf_counter();got=runner(q,items);samples.append((time.perf_counter()-t)*1000)
 out[q]={'cold_ms':round(cold,3),'median_ms':round(statistics.median(samples),3),'matches':len(got[0])}
print(json.dumps(out))
'''
search = {}
for kind, root in [('old', OLD), ('new', NEW)]:
    completed = subprocess.run([sys.executable, '-c', script, str(root), kind],
                               check=True, capture_output=True, text=True)
    search[kind] = json.loads(completed.stdout)
    print('SEARCH', kind, json.dumps(search[kind]), flush=True)

ns = {'struct': struct, 'zlib': zlib}
tree = ast.parse((OLD / 'clawboard/image.py').read_text(encoding='utf-8'))
tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('dib_to_png', 'png_to_dib')]
exec(compile(tree, 'original-image-codec', 'exec'), ns)
images = []
for width, height in [(1920, 1080), (3840, 2160)]:
    row = (bytes(range(256)) * ((width * 4 + 255) // 256))[:width * 4]
    pixels = row * height
    dib = struct.pack('<IiiHHIIiiII', 40, width, height, 1, 32, 0, len(pixels), 0, 0, 0, 0) + pixels
    old_encode, encoded = measure(lambda: ns['dib_to_png'](dib), 1)
    new_encode, new_encoded = measure(lambda: dib_to_png(dib), 1)
    old_decode, old_decoded = measure(lambda: ns['png_to_dib'](encoded[0]), 1)
    new_decode, new_decoded = measure(lambda: png_to_dib(encoded[0]), 1)
    assert old_decoded == new_decoded == (dib, width, height)
    assert png_to_dib(new_encoded[0]) == (dib, width, height)
    result = {'width': width, 'height': height, 'old_encode': old_encode, 'new_encode': new_encode,
              'old_decode': old_decode, 'new_decode': new_decode}
    images.append(result)
    print('IMAGE', json.dumps(result), flush=True)

items = [{'id': str(i), 'text': ('项目 日志 hello 123\n' * 150)[:2000],
          'content_type': 'text', 'kind_auto': 'text', 'source_app': 'chrome'} for i in range(5000)]
projection = ViewProjection()
def project_visible():
    rows = projection.project(items, 'clip', {'mask_sensitive': True, 'show_time': True})
    return [dict(rows[i]) for i in range(10)]
project, _ = measure(project_visible)
result = {'environment': {'python': platform.python_version(), 'system': platform.platform()},
          'scope': 'Synthetic CPU measurements, not Windows GUI frame rate or a user-machine guarantee',
          'search_500_items_2000_chars': search, 'images': images,
          'project_5000_only_10_visible': project}
path = args.output
path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print('RESULT', str(path), flush=True)
