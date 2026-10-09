# -*- coding: utf-8 -*-
"""ClawBoard README 截图流水线。

开发工具，不参与产品运行；允许依赖 Pillow，不影响 ClawBoard 的零依赖承诺。
（本文件只在开发机手动执行，用于产出 docs/images/ 下的仓库截图，绝不随产品分发。）

流水线原理：
  1. 用一份**演示数据**在内存里起一个真实 ClawBoard 实例（NO_SAVE=True，绝不写盘）；
  2. 用 Win32 PrintWindow(hwnd, memdc, PW_RENDERFULLCONTENT=2) + GetDIBits 抓窗口位图；
  3. 用 Pillow 做圆角 / 描边 / 投影 / 浅灰底 / 拼图与图注后处理，输出 PNG。

用法：
    python tools/shots/make_shots.py                # 生成全部截图
    python tools/shots/make_shots.py main-window    # 只生成指定几张
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import tempfile
import time

# ---------------------------------------------------------------------------
# 0. 路径准备：项目根目录加入 sys.path
# ---------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT_DIR = os.path.join(ROOT, 'docs', 'images')
sys.path.insert(0, ROOT)

# ---------------------------------------------------------------------------
# 1. 数据重定向（在任何 clawboard 模块 import **之前**）
#    把数据目录 / 数据文件指到临时目录，保证仓库里的真实数据文件
#    ClawBoard数据.json 连读都不读、更不会被写。
# ---------------------------------------------------------------------------
import clawboard.config as _cfg            # noqa: E402

_TMP = tempfile.mkdtemp(prefix='cbshot_')
_cfg.BASE_DIR = _TMP
_cfg.DATA_FILE = os.path.join(_TMP, 'ClawBoard数据.json')
_cfg.CRASH_LOG = os.path.join(_TMP, 'crash.log')

# ---------------------------------------------------------------------------
# 2. 进程级 DPI 感知（与真实 exe 同环境：本机 125% → 逻辑尺寸 ×1.25）
# ---------------------------------------------------------------------------
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import tkinter as tk                       # noqa: E402
from PIL import Image, ImageDraw, ImageFilter, ImageFont   # noqa: E402

import ClawBoard as C                      # noqa: E402
from clawboard.tag import detect_tags      # noqa: E402

# 硬性要求：绝不写盘（ClawBoard 的模块 __setattr__ 会把值转发到 runtime.NO_SAVE）
C.NO_SAVE = True

u = ctypes.windll.user32
g = ctypes.windll.gdi32

# ---------------------------------------------------------------------------
# 3. 视觉常量
# ---------------------------------------------------------------------------
S = 1                                  # 原生物理像素输出（进程已是 125% DPI 感知，无需再放大）
BG = (244, 245, 248)                   # 浅灰底：深色主题截图配浅底更显眼
BORDER = (208, 212, 221)
SHADOW_RGBA = (18, 21, 30, 40)
FONT_PATH = r'C:\Windows\Fonts\msyh.ttc'
CAP_COLOR = (78, 84, 98)
WIN = '420x600+120+120'                 # 单窗口截图的窗口尺寸/位置


# ---------------------------------------------------------------------------
# 4. 窗口抓图（PrintWindow + GetDIBits）
# ---------------------------------------------------------------------------
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [('biSize', wt.DWORD), ('biWidth', ctypes.c_long),
                ('biHeight', ctypes.c_long), ('biPlanes', wt.WORD),
                ('biBitCount', wt.WORD), ('biCompression', wt.DWORD),
                ('biSizeImage', wt.DWORD), ('biXPelsPerMeter', ctypes.c_long),
                ('biYPelsPerMeter', ctypes.c_long), ('biClrUsed', wt.DWORD),
                ('biClrImportant', wt.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [('bmiHeader', BITMAPINFOHEADER), ('bmiColors', wt.DWORD * 3)]


def window_rect(hwnd):
    """返回窗口的物理屏幕矩形 (left, top, width, height)。"""
    r = wt.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def grab(hwnd):
    """抓取窗口内容为 PIL RGB 图（物理像素）。"""
    _, _, W, H = window_rect(hwnd)
    W, H = max(1, W), max(1, H)
    hdc = u.GetWindowDC(hwnd)
    memdc = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, W, H)
    old = g.SelectObject(memdc, bmp)
    # PW_RENDERFULLCONTENT = 2：能抓到自绘 / 分层窗口的内容
    u.PrintWindow(hwnd, memdc, 2)
    bi = BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = W
    bi.bmiHeader.biHeight = -H            # 负数 = top-down
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    bi.bmiHeader.biCompression = 0
    buf = ctypes.create_string_buffer(W * H * 4)
    g.GetDIBits(memdc, bmp, 0, H, buf, ctypes.byref(bi), 0)
    img = Image.frombuffer('RGBA', (W, H), buf, 'raw', 'BGRA', 0, 1).convert('RGB')
    g.SelectObject(memdc, old)
    g.DeleteObject(bmp)
    g.DeleteDC(memdc)
    u.ReleaseDC(hwnd, hdc)
    return img


def grab_widget(win):
    """抓取一个 Tk 顶层窗口（winfo_id() 即 HWND）。"""
    try:
        win.update_idletasks()
        win.update()
    except Exception:
        pass
    time.sleep(0.12)
    return grab(win.winfo_id())


# ---------------------------------------------------------------------------
# 5. 后处理：圆角 + 描边 + 投影 + 浅灰底
# ---------------------------------------------------------------------------
def rounded_mask(size, rad):
    m = Image.new('L', size, 0)
    ImageDraw.Draw(m).rounded_rectangle(
        [0, 0, size[0] - 1, size[1] - 1], radius=rad, fill=255)
    return m


def decorate(raw, scale=S, pad=14, radius=11, bg=BG, border=BORDER,
             shadow=SHADOW_RGBA):
    """单窗口装饰：放大 → 圆角 → 投影 → 描边 → 浅灰底，返回 RGBA 图。"""
    if scale != 1:
        raw = raw.resize((raw.width * scale, raw.height * scale), Image.LANCZOS)
    w, h = raw.size
    P = pad * scale
    R = radius * scale
    cv = Image.new('RGBA', (w + 2 * P, h + 2 * P), bg + (255,))
    # 投影
    sh = Image.new('RGBA', cv.size, (0, 0, 0, 0))
    layer = Image.new('RGBA', (w, h), shadow)
    sh.paste(layer, (P, P + int(2.5 * scale)), rounded_mask((w, h), R))
    sh = sh.filter(ImageFilter.GaussianBlur(6 * scale))
    cv = Image.alpha_composite(cv, sh)
    # 窗口本体
    win = raw.convert('RGBA')
    win.putalpha(rounded_mask((w, h), R))
    cv.alpha_composite(win, (P, P))
    # 1px 描边
    ImageDraw.Draw(cv).rounded_rectangle(
        [P, P, P + w - 1, P + h - 1], radius=R,
        outline=border + (255,), width=max(1, scale))
    return cv


def _font(px):
    try:
        return ImageFont.truetype(FONT_PATH, px)
    except Exception:
        return ImageFont.load_default()


def compose(tiles, captions=None, gap=26, pad=22, bg=BG, cap_px=15,
            valign='top', scale=S):
    """把若干已装饰的窗口图拼到一张浅灰底画布上，可选图注，返回 RGBA 图。"""
    n = len(tiles)
    gap *= scale
    pad *= scale
    cap_px *= scale
    cap_h = (cap_px + 16 * scale) if captions else 0
    tw = [t.width for t in tiles]
    th = [t.height for t in tiles]
    W = sum(tw) + gap * (n - 1) + pad * 2
    H = max(th) + cap_h + pad * 2
    cv = Image.new('RGBA', (W, H), bg + (255,))
    x = pad
    for i, t in enumerate(tiles):
        if valign == 'bottom':
            y = pad + (max(th) - t.height)
        else:
            y = pad
        cv.alpha_composite(t, (x, y))
        if captions:
            d = ImageDraw.Draw(cv)
            f = _font(cap_px)
            cx = x + tw[i] // 2
            twid = d.textlength(captions[i], font=f)
            ty = pad + max(th) + 8 * scale
            d.text((cx - twid / 2, ty), captions[i], font=f, fill=CAP_COLOR + (255,))
        x += tw[i] + gap
    return cv


def save(img, name):
    path = os.path.join(OUT_DIR, name)
    if os.path.exists(path):
        os.remove(path)
    img.convert('RGB').save(path, 'PNG', optimize=True, compress_level=9)
    kb = os.path.getsize(path) / 1024.0
    print('  -> %-24s %5dx%-5d %6.1f KB' % (name, img.width, img.height, kb))


# ---------------------------------------------------------------------------
# 6. 演示数据（全部为脱敏虚构内容）
# ---------------------------------------------------------------------------
NOW = int(time.time() * 1000)
_DEMO_SEQ = [0]


def _demo(text, app, ctype=None, fav=0, mins=10, lines=None, img=None):
    _DEMO_SEQ[0] += 1
    ts = NOW - mins * 60 * 1000
    it = {
        'id': 'demo_%d' % _DEMO_SEQ[0],
        'text': text,
        'created_at': ts,
        'updated_at': ts,
        'last_used_at': None,
        'seq': 1000 - _DEMO_SEQ[0],
        'source_app': app,
        'copy_count': 1,
        'fav': fav,
        'pinned': 0,
        'use_count': 0,
        'is_estimated': 0,
        'content_type': ctype or C.detect_content_type(text),
        'content_size': C.byte_size(text),
        'kind_auto': C.classify(text)[0],
        'tags': detect_tags(text),
    }
    if img:
        it.update(content_type='image', image_path=img[0],
                  image_w=img[1], image_h=img[2], text='[图片]')
    if lines is not None:
        it['text'] = text
    return it


def demo_clip(app):
    """11 条脱敏演示记录：覆盖链接 / 邮箱 / JSON / 代码 / 手机号 / 日期等类型。"""
    return [
        _demo('https://github.com/pay-and-gain/ClawBoard', 'msedge',
              ctype='url', fav=1, mins=3),
        _demo('user@example.com', 'outlook', mins=9),
        _demo('{"app": "ClawBoard", "version": "2.2.4", "deps": []}', 'Code',
              ctype='json', mins=17),
        _demo('13800138000', 'chrome', mins=24),
        _demo('北京市朝阳区示例路 88 号 A 座 12 层', 'notepad', mins=36),
        _demo("def hello(name):\n    print('Hello,', name)\n\n"
              "hello('ClawBoard')", 'Code', mins=45),
        _demo('https://github.com/anlen123/wincpl', 'msedge',
              ctype='url', mins=58),
        _demo('好的，我这边确认一下，稍后回复您。', 'WeChat', mins=72),
        _demo('2025-10-04', 'notepad', mins=96),
        _demo('https://pay-and-gain.github.io/ClawBoard/', 'msedge',
              ctype='url', mins=128),
        _demo('https://github.com/pay-and-gain/ClawBoard/releases', 'msedge',
              ctype='url', mins=150),
    ]


def make_demo_png(path):
    """造一张彩色演示图（图片剪贴板截图用），避免任何真实截图。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    w, h = 720, 440
    im = Image.new('RGB', (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (int(40 + 150 * x / w), int(90 + 120 * y / h),
                        int(210 - 90 * x / w))
    d = ImageDraw.Draw(im)
    d.rectangle([40, 40, w - 40, h - 40], outline=(255, 255, 255), width=3)
    d.ellipse([90, 120, 240, 270], fill=(255, 214, 102))
    d.polygon([(330, 300), (470, 300), (400, 150)], fill=(255, 255, 255))
    d.text((60, 320), 'ClawBoard  -  demo image', font=_font(30),
           fill=(255, 255, 255))
    im.save(path, 'PNG')


# ---------------------------------------------------------------------------
# 7. 构建实例
# ---------------------------------------------------------------------------
def reset_title(app):
    """把标题栏文案复位成「⚡ ClawBoard」，避免启动期的临时提示（如「热键被占用」）
    残留在标题栏上污染截图。"""
    try:
        app.title_lb.configure(text='⚡ ' + C.APP_NAME)
    except Exception:
        pass


def snap(win, app=None):
    """复位标题后抓图（供截图统一调用）。"""
    if app is not None:
        reset_title(app)
    return grab_widget(win)


def build_app():
    C.DEFAULT_SETTINGS['collapsed'] = False
    C.DEFAULT_SETTINGS['theme'] = 'dark'
    C.DEFAULT_SETTINGS['show_time'] = True     # 列表里展示「时间」
    C.DEFAULT_SETTINGS['show_preview'] = True
    C.DEFAULT_SETTINGS['ui_scale'] = 1.0
    C.DEFAULT_SETTINGS['hotkey'] = 'none'      # 演示实例不注册热键，免得弹「热键被占用」
    root = tk.Tk()
    app = C.ClawBoard(root)
    if app.collapsed:                          # 兜底：确保展开
        app.collapsed = False
        app.body.pack(fill='both', expand=True)
        root.minsize(*app.min_size())
    root.geometry(WIN)
    root.update()
    reset_title(app)
    # 演示数据（图片条目图片先落盘到临时目录的 images/）
    _img_name = 'demo_image.png'
    make_demo_png(os.path.join(_TMP, 'images', _img_name))
    items = demo_clip(app)
    img_item = _demo('[图片]', 'Snipping Tool', mins=1,
                     img=(_img_name, 720, 440))
    items.insert(0, img_item)
    app.data['clip'] = items
    app.tab = 'clip'
    app.search.set('')
    app.render()
    root.update()
    reset_title(app)
    return root, app, img_item


# ---------------------------------------------------------------------------
# 8. 各张截图
# ---------------------------------------------------------------------------
def shot_main_window(root, app):
    print('[main-window] 主界面（暗色 / 有内容）')
    root.geometry(WIN)
    app.tab = 'clip'
    app.search.set('')
    app.sel_clip = None
    app.render()
    root.update()
    save(decorate(snap(root, app)), 'main-window.png')


def shot_search_highlight(root, app):
    print('[search-highlight] 高级搜索 + 高亮')
    root.geometry(WIN)
    app.tab = 'clip'
    app.sel_clip = None
    app.search.set('ClawBoard type:url')
    app.render()
    root.update()
    app.focus_search()
    root.update()
    save(decorate(snap(root, app)), 'search-highlight.png')
    app.search.set('')
    app.render()


def shot_image_clipboard(root, app, img_item):
    print('[image-clipboard] 图片条目 + 角落大图预览')
    app.tab = 'clip'
    app.search.set('')
    app.sel_clip = img_item['id']
    app.vlist.sel = img_item['id']
    app.render()
    root.update()
    app._preview_now()
    root.update()
    time.sleep(0.2)
    pv = getattr(app, '_preview', None)
    root.geometry(WIN)
    root.update()
    if pv is not None:
        try:
            pv.win.update_idletasks()
            pw = pv.win.winfo_width() or 420
            ph = pv.win.winfo_height() or 300
            # 贴到面板右侧、底边对齐（角落预览的真实观感）
            pv.win.geometry('%dx%d+%d+%d' % (pw, ph, 120 + 420 + 18,
                                             120 + max(0, 600 - ph)))
            pv.win.update()
            time.sleep(0.2)
        except Exception:
            pv = None
    main_t = decorate(snap(root, app))
    if pv is not None:
        pv_t = decorate(grab_widget(pv.win))
        out = compose([main_t, pv_t], captions=['剪贴板面板', '角落大图预览'],
                      valign='bottom')
    else:
        out = main_t
    save(out, 'image-clipboard.png')
    app.close_preview()
    app.sel_clip = None
    root.update()


def shot_phrases(root, app):
    print('[phrases] 常用语面板')
    g = app.cur_group()
    g['items'] = [
        {'id': 'ph_1', 'name': '家庭地址', 'text': '北京市海淀区示例路 1 号院 2 单元 301',
         'trigger': 'dz'},
        {'id': 'ph_2', 'name': '工作邮箱', 'text': 'user@example.com', 'trigger': 'yx'},
        {'id': 'ph_3', 'name': '发票抬头', 'text': '某某科技（示例）有限公司', 'trigger': ''},
        {'id': 'ph_4', 'name': '收款账号', 'text': '招商银行 6214 8300 0000 0000',
         'trigger': 'zh'},
        {'id': 'ph_5', 'name': '常用回复', 'text': '收到，我看下稍后回复你～', 'trigger': ''},
        {'id': 'ph_6', 'name': '会议纪要模板',
         'text': '时间：\n参会人：\n议题：\n结论：\n待办：', 'trigger': ''},
    ]
    app.tab = 'phrase'
    app.search.set('')
    app.render()
    root.geometry(WIN)
    root.update()
    panel = decorate(snap(root, app), pad=12)
    # 触发词设置：用应用自带的 Dialog 组件（不读取真实剪贴板），填演示值
    dlg = C.Dialog(root, '新增常用语',
                   [('名称（可留空）', '家庭地址', False),
                    ('触发词（可留空）', 'dz', False),
                    ('内容', '北京市海淀区示例路 1 号院 2 单元 301', True)])
    dlg.show(400, 380)
    root.update()
    dlg_win = dlg.win
    try:
        dlg_win.geometry('400x380+%d+%d' % (120 + 420 + 18, 120 + 130))
        dlg_win.update()
        time.sleep(0.2)
        dialog = decorate(grab_widget(dlg_win), pad=12)
    finally:
        try:
            dlg_win.destroy()
        except Exception:
            pass
    save(compose([panel, dialog],
                 captions=['常用语面板', '触发词设置（dz → 地址）'], valign='top'),
         'phrases.png')
    app.tab = 'clip'
    app.render()


def shot_transform(root, app):
    print('[transform] 文本变换（27 项）')
    app.tab = 'clip'
    app.search.set('')
    jid = None
    for it in app.data['clip']:
        if it.get('content_type') == 'json':
            jid = it['id']
            break
    app.sel_clip = jid
    app.vlist.sel = jid
    app.render()
    root.update()
    text, it = app.current_target_text()
    tw = C.TransformWindow(app, text, it)
    root.update()
    try:
        tw.win.geometry('760x540+80+90')
        tw.win.update()
        time.sleep(0.25)
        try:                                    # 选中首个推荐变换并执行，填充「结果」
            if tw.lb.size():
                tw.lb.selection_clear(0, 'end')
                tw.lb.selection_set(0)
                tw.run()
        except Exception:
            pass
        tw.win.update()
        time.sleep(0.15)
        save(decorate(snap(tw.win)), 'transform.png')
    finally:
        try:
            tw.win.destroy()
        except Exception:
            pass
    app.sel_clip = None
    root.update()


def shot_command_palette(root, app):
    print('[command-palette] 命令面板（Ctrl+Shift+P）')
    app.open_command_palette()
    root.update()
    cp = getattr(app, '_command_palette', None)
    if cp is None:
        print('  ! 命令面板未创建，跳过')
        return
    try:
        cp.win.geometry('420x360+120+110')
        cp.win.update()
        time.sleep(0.25)
        save(decorate(snap(cp.win)), 'command-palette.png')
    finally:
        try:
            cp.win.destroy()
        except Exception:
            pass
    app._command_palette = None
    root.update()


def shot_folded_edge(root, app):
    print('[folded-edge] 折叠贴边态')
    if not app.collapsed:
        app.toggle_collapse()
    root.update()
    # 固定在屏幕上一处，抓成一条标题栏
    root.geometry('210x%d+300+300' % C.scaled(C.BAR_H))
    root.update()
    time.sleep(0.15)
    save(decorate(snap(root, app)), 'folded-edge.png')
    if app.collapsed:
        app.toggle_collapse()
    root.update()


def shot_scale_compare(root, app):
    print('[scale-compare] 界面等比缩放 50% / 100% / 150%')
    # 固定一个较矮的基准窗口（三档都按精确比例缩放），既保证比例准确，
    # 又让 150% 档不至于把整张拼图撑得过大（控制单图体积 < 300KB）。
    BASE_W, BASE_H = 350, 320
    tiles, caps = [], []
    for lvl, cap in ((0.5, '50%'), (1.0, '100%'), (1.5, '150%')):
        app.set_ui_scale(lvl)
        root.update()
        # 放开最小尺寸限制，才能拿到精确的 0.5x 比例（否则被 min_size clamp 住）
        root.minsize(1, 1)
        root.geometry('%dx%d+140+140' % (int(round(BASE_W * lvl)),
                                         int(round(BASE_H * lvl))))
        root.update()
        app.search.set('')
        app.render()
        root.update()
        time.sleep(0.15)
        tiles.append(decorate(snap(root, app), pad=8, shadow=(0, 0, 0, 0)))
        caps.append(cap)
    app.set_ui_scale(1.0)
    root.update()
    save(compose(tiles, captions=caps, gap=18, pad=16, valign='top'),
         'scale-compare.png')


def shot_theme_compare(root, app):
    print('[theme-compare] 亮色 / 暗色主题对比')
    tiles, caps = [], []
    for name, cap in (('light', '亮色主题'), ('dark', '暗色主题')):
        app.st['theme'] = name
        app.rebuild()
        root.update()
        root.geometry(WIN)
        app.search.set('')
        app.render()
        root.update()
        time.sleep(0.15)
        tiles.append(decorate(snap(root, app), pad=10))
        caps.append(cap)
    app.st['theme'] = 'dark'
    app.rebuild()
    root.update()
    save(compose(tiles, captions=caps, valign='top'), 'theme-compare.png')


def shot_settings(root, app):
    print('[settings] 设置界面（重制，更高清）')
    sw = C.SettingsWindow(app)
    root.update()
    time.sleep(0.2)
    try:
        sw.win.geometry('430x640+%d+120' % (120 + 420 + 40))
        sw.win.update()
        time.sleep(0.25)
        save(decorate(snap(sw.win)), 'settings-general.png')
        # 滚到底部 → 进阶项
        sw.sc.canvas.yview_moveto(1.0)
        sw.win.update()
        time.sleep(0.25)
        save(decorate(snap(sw.win)), 'settings-advanced.png')
    finally:
        try:
            sw.win.destroy()
        except Exception:
            pass
    root.update()


# ---------------------------------------------------------------------------
# 9. 主流程
# ---------------------------------------------------------------------------
SHOTS = {
    'main-window': shot_main_window,
    'search-highlight': shot_search_highlight,
    'image-clipboard': shot_image_clipboard,
    'phrases': shot_phrases,
    'transform': shot_transform,
    'command-palette': shot_command_palette,
    'folded-edge': shot_folded_edge,
    'scale-compare': shot_scale_compare,
    'theme-compare': shot_theme_compare,
    'settings': shot_settings,
}


def main():
    wanted = sys.argv[1:] or list(SHOTS)
    os.makedirs(OUT_DIR, exist_ok=True)
    print('输出目录：%s' % OUT_DIR)
    root, app, img_item = build_app()
    try:
        for name in wanted:
            fn = SHOTS.get(name)
            if not fn:
                print('  跳过未知截图：%s' % name)
                continue
            if name == 'image-clipboard':
                fn(root, app, img_item)
            else:
                fn(root, app)
            root.update()
    finally:
        try:
            app.hw.unreg_hotkey()
            app.hw.tray_del()
            app.hw.stop()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass
    print('完成。', flush=True)
    # 强制退出：Tk / 托盘 / 热键线程可能残留，os._exit 避免进程挂住不退出
    os._exit(0)


if __name__ == '__main__':
    main()
