"""开发工具，不参与产品运行：用Pillow生成原创纸感爪印图标的PNG/ICO。

应用标志和托盘轮廓分别对应docs/plans/v3-upgrade中的两枚原创SVG母版。
Pillow仅用于开发期抗锯齿与栅格化；产品只读取生成资源，不依赖Pillow。
"""
from io import BytesIO
import json
import math
from pathlib import Path
import struct

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'packaging/ui-assets'
SIZES = (8, 10, 12, 14, 16, 18, 20, 22, 24, 28, 30, 32, 36, 40, 48, 64, 96, 128, 256)
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
NAMES = ('add', 'delete', 'split', 'clear', 'transform', 'settings', 'more', 'pin',
         'collapse', 'close', 'workbench', 'filter', 'text', 'link', 'image',
         'file', 'code', 'search', 'copy', 'edit', 'folder', 'check', 'back',
         'next', 'restore', 'clock')


def bezier(start, *curves):
    points = [start]
    for one, two, end in curves:
        for i in range(1, 25):
            t, a = i / 24, 1 - i / 24
            points.append(tuple(a ** 3 * start[k] + 3 * a * a * t * one[k]
                                + 3 * a * t * t * two[k] + t ** 3 * end[k] for k in (0, 1)))
        start = end
    return points


class Painter:
    def __init__(self, units, color=(0, 0, 0, 255), pixels=384):
        self.scale = pixels / units
        self.image = Image.new('RGBA', (pixels, pixels))
        self.draw = ImageDraw.Draw(self.image)
        self.color = color

    def coords(self, points):
        return [(x * self.scale, y * self.scale) for x, y in points]

    def path(self, points, color=None, width=1.8, closed=False, fill=False):
        points = self.coords(points)
        color = color or self.color
        if fill:
            self.draw.polygon(points, fill=color)
            return
        if closed:
            points += points[:1]
        self.draw.line(points, fill=color, width=max(1, round(width * self.scale)), joint='curve')
        radius = width * self.scale / 2
        for x, y in points:
            self.draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=color)

    def ellipse(self, box, color=None, width=None):
        box = tuple(v * self.scale for v in box)
        if width:
            self.draw.ellipse(box, outline=color or self.color, width=round(width * self.scale))
        else:
            self.draw.ellipse(box, fill=color or self.color)

    def rect(self, box, radius=0, color=None, width=None):
        box = tuple(v * self.scale for v in box)
        self.draw.rounded_rectangle(box, radius=radius*self.scale,
                                    fill=None if width else color or self.color,
                                    outline=color or self.color if width else None,
                                    width=round((width or 1)*self.scale))


def logo():
    p = Painter(256, pixels=1024)
    green, paper, fold = '#235b50', '#f8f5ea', '#bad7c6'
    p.rect((12, 12, 244, 244), 58, green)
    body = [(70, 57), (158, 57), (192, 91), (192, 191)]
    body += bezier((192, 191), ((192, 198), (186, 204), (179, 204)))[1:]
    body += [(70, 204)] + bezier((70, 204), ((63, 204), (57, 198), (57, 191)))[1:]
    body += [(57, 70)] + bezier((57, 70), ((57, 63), (63, 57), (70, 57)))[1:]
    p.path(body, paper, fill=True)
    p.path([(158, 57), (158, 81)] + bezier((158, 81), ((158, 87), (162, 91), (168, 91)))[1:]
           + [(192, 91)], fold, fill=True)
    for cx, cy, angle in ((103, 122, -28), (127, 112, 0), (151, 122, 28)):
        a = math.radians(angle)
        points = [(cx + 10*math.cos(t)*math.cos(a)-13*math.sin(t)*math.sin(a),
                   cy + 10*math.cos(t)*math.sin(a)+13*math.sin(t)*math.cos(a))
                  for t in (i*math.tau/100 for i in range(100))]
        p.path(points, green, fill=True)
    foot = bezier((104, 150), ((108, 132), (117, 126), (127, 126)),
                  ((137, 126), (146, 132), (150, 150)),
                  ((154, 165), (143, 172), (127, 167)),
                  ((111, 172), (100, 165), (104, 150)))
    p.path(foot, green, fill=True)
    return p.image


def tray(dark=False, paused=False):
    color = '#e6eee6' if dark else '#23352c'
    p = Painter(16, color, pixels=256)
    p.rect((3.5, 2.5, 12.5, 14.5), 1, width=1.4)
    p.rect((5.5, 1, 10.5, 4), 1.2)
    for x, y in ((5.5, 7), (8, 6), (10.5, 7)):
        p.ellipse((x-1, y-1, x+1, y+1))
    foot = bezier((5.7, 10.2), ((6.1, 8.8), (7, 8), (8, 8)),
                  ((9, 8), (9.9, 8.8), (10.3, 10.2)),
                  ((10.8, 11.6), (9.7, 12.2), (8, 11.7)),
                  ((6.3, 12.2), (5.2, 11.6), (5.7, 10.2)))
    p.path(foot, fill=True)
    if paused:
        # A visible pause mark survives monochrome/high contrast, unlike a tint.
        p.ellipse((9, 9, 16, 16), '#fafbf8' if not dark else '#202822')
        p.rect((10.7, 10.4, 12, 14.4), .4)
        p.rect((13.1, 10.4, 14.4, 14.4), .4)
    return p.image


def action(name):
    p = Painter(24)
    line, circle, box = p.path, p.ellipse, p.rect
    if name == 'add':
        line([(12, 5), (12, 19)]); line([(5, 12), (19, 12)])
    elif name == 'delete':
        line([(4, 7), (20, 7)]); line([(9, 7), (9, 4), (15, 4), (15, 7)])
        line([(6, 7), (7, 20), (17, 20), (18, 7)]); line([(10, 11), (10, 16)]); line([(14, 11), (14, 16)])
    elif name == 'split':
        line([(12, 3), (12, 9), (5, 16), (5, 12)]); line([(12, 9), (19, 16), (19, 12)])
        line([(5, 16), (9, 16)]); line([(15, 16), (19, 16)]); line([(5, 21), (8, 21)]); line([(16, 21), (19, 21)])
    elif name == 'clear':
        line([(5, 5), (19, 19)]); line([(19, 5), (5, 19)]); line([(4, 21), (20, 21)])
    elif name == 'transform':
        line([(4, 7), (20, 7), (16, 3)]); line([(20, 7), (16, 11)])
        line([(20, 17), (4, 17), (8, 13)]); line([(4, 17), (8, 21)])
    elif name == 'settings':
        line([(9, 3), (8, 6), (5, 7), (6, 10), (4, 12), (6, 14), (5, 17),
              (8, 18), (9, 21), (15, 21), (16, 18), (19, 17), (18, 14),
              (20, 12), (18, 10), (19, 7), (16, 6), (15, 3)], closed=True)
        circle((9, 9, 15, 15), width=1.8)
    elif name == 'more':
        for x in (5, 12, 19): circle((x-1, 11, x+1, 13))
    elif name == 'pin':
        line([(8, 3), (16, 3), (15, 9), (19, 13), (5, 13), (9, 9), (8, 3)])
        line([(12, 13), (12, 21)])
    elif name == 'collapse': line([(5, 12), (19, 12)])
    elif name == 'close': line([(6, 6), (18, 18)]); line([(6, 18), (18, 6)])
    elif name == 'workbench':
        box((3, 4, 21, 20), 2, width=1.8); line([(9, 4), (9, 20)]); line([(15, 4), (15, 20)])
    elif name == 'filter': line([(3, 4), (21, 4), (14, 12), (14, 19), (10, 21), (10, 12), (3, 4)])
    elif name in ('text', 'file'):
        line([(6, 3), (15, 3), (19, 7), (19, 21), (6, 21), (6, 3)])
        line([(14, 3), (14, 8), (19, 8)])
        if name == 'text': line([(9, 12), (16, 12)]); line([(9, 16), (14, 16)])
    elif name == 'link':
        line(bezier((10, 7), ((12, 3), (17, 3), (20, 6)), ((23, 9), (21, 13), (17, 15))))
        line(bezier((14, 17), ((12, 21), (7, 21), (4, 18)), ((1, 15), (3, 11), (7, 9))))
        line([(8, 16), (16, 8)])
    elif name == 'image':
        box((3, 3, 21, 21), 2, width=1.8); circle((6.5, 6.5, 9.5, 9.5), width=1.5)
        line([(3, 17), (9, 11), (14, 16), (17, 13), (21, 17)])
    elif name == 'code':
        line([(8, 6), (3, 12), (8, 18)]); line([(16, 6), (21, 12), (16, 18)]); line([(14, 4), (10, 20)])
    elif name == 'search': circle((4, 4, 17, 17), width=1.8); line([(16, 16), (21, 21)])
    elif name == 'copy':
        box((8, 8, 21, 21), 2, width=1.8); line([(16, 5), (16, 3), (3, 3), (3, 16), (5, 16)])
    elif name == 'edit': line([(5, 15), (16, 4), (20, 8), (9, 19), (4, 20), (5, 15)]); line([(13, 7), (17, 11)])
    elif name == 'folder': line([(3, 6), (10, 6), (12, 9), (21, 9), (21, 20), (3, 20), (3, 6)])
    elif name == 'check': line([(5, 12), (9, 16), (19, 6)])
    elif name in ('back', 'next'):
        line([(14, 5), (7, 12), (14, 19)] if name == 'back' else [(10, 5), (17, 12), (10, 19)])
    elif name == 'restore':
        line([(4, 4), (4, 10), (10, 10)])
        line(bezier((4, 10), ((6, 2), (19, 2), (20, 11)), ((22, 21), (9, 24), (5, 17))))
    elif name == 'clock':
        circle((3, 3, 21, 21), width=1.8); line([(12, 7), (12, 12), (16, 14)])
    return p.image.resize((64, 64), Image.Resampling.LANCZOS)


def write_ico(path, image, sizes):
    encoded = []
    for size in sizes:
        stream = BytesIO()
        image.resize((size, size), Image.Resampling.LANCZOS).save(stream, format='PNG')
        encoded.append((size, stream.getvalue()))
    header, body = bytearray(struct.pack('<HHH', 0, 1, len(encoded))), bytearray()
    offset = 6 + 16 * len(encoded)
    for size, data in encoded:
        header.extend(struct.pack('<BBBBHHII', size if size < 256 else 0,
                                  size if size < 256 else 0, 0, 0, 1, 32, len(data), offset))
        body.extend(data); offset += len(data)
    path.write_bytes(header + body)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    application = logo()
    for size in SIZES:
        application.resize((size, size), Image.Resampling.LANCZOS).save(OUTPUT / ('logo-%d.png' % size))
    write_ico(OUTPUT / 'app.ico', application, ICO_SIZES)
    for dark in (False, True):
        for paused in (False, True):
            stem = 'tray-' + ('dark' if dark else 'light') + ('-paused' if paused else '')
            image = tray(dark, paused)
            write_ico(OUTPUT / (stem + '.ico'), image, ICO_SIZES[:7])
            for size in (16, 20, 24, 32):
                image.resize((size, size), Image.Resampling.LANCZOS).save(OUTPUT / ('%s-%d.png' % (stem, size)))
    for name in NAMES:
        action(name).save(OUTPUT / (name + '.png'))
    manifest = dict(format=1, brand='paper-paw', action_masks=dict(size=64, names=NAMES),
                    logo_sizes=SIZES, application_ico_sizes=ICO_SIZES,
                    source_masters=['docs/plans/v3-upgrade/icon-a-paw-note.svg',
                                    'docs/plans/v3-upgrade/icon-a-tray.svg'])
    (OUTPUT / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('Generated paper-paw application/tray icons and %d action masks in %s' % (len(NAMES), OUTPUT))


if __name__ == '__main__':
    main()
