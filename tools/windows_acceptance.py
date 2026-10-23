"""开发工具，不参与产品运行：隔离的 Windows 交互验收面板与本地测试页。

只绑定 loopback；记录合成内容的匹配结果和长度，不记录输入正文。
运行 python tools/windows_acceptance.py，结束后保留临时目录中的验收证据。
"""
import hashlib
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import secrets
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.windows_test_guard import acquire_desktop_test_lease
acquire_desktop_test_lease()
SESSION = Path(tempfile.mkdtemp(prefix='ClawBoard-acceptance-'))
KEY = secrets.token_hex(16)
TITLE = 'ClawBoard Acceptance - ' + secrets.token_hex(4)
TEXT = {
    'single': 'ClawBoard 浏览器验收 ABC-123 😀',
    'multi': '第一行：中文验收\nSecond line: ABC-123\n第三行：😀 END',
    'rich': '富文本输入区验收：中文 ABC 😀',
}
COMMANDS = queue.Queue(maxsize=8)
LOCK = threading.Lock()
STATE = {'observations': {}, 'operations': [], 'trigger_operations': [],
         'stage': 'browser', 'ready': False}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


DATA_PATHS = [ROOT / 'ClawBoard数据.json',
              Path.home() / 'Desktop' / 'cut' / 'ClawBoard数据.json',
              Path(os.environ['APPDATA']) / 'ClawBoard' / 'ClawBoard数据.json']
BEFORE = {str(p): digest(p) for p in DATA_PATHS}
(SESSION / 'data-before.json').write_text(json.dumps(BEFORE), encoding='utf-8')

# Every importing adapter sees these temporary paths, even if it binds constants.
from clawboard import config, runtime
config.BASE_DIR = str(SESSION)
config.DATA_FILE = str(SESSION / 'ClawBoard数据.json')
config.CRASH_LOG = str(SESSION / 'crash.log')
runtime.NO_SAVE = True
settings = dict(config.DEFAULT_SETTINGS, listen=False, trigger_enabled=False,
                sound_copy=False, sound_paste=False, show_toast=False,
                show_preview=False, collapsed=False, frosted=False,
                trim_paste=False, edge_hide=False, hotkey='ctrl+shift+v')
fixture = dict(schema_version=3, settings=settings, gi=0,
               geom='520x650+100+100', clip=[
                   dict(id='accept-' + name, text=value, content_type='text',
                        seq=3-i, created_at=1000, updated_at=1000)
                   for i, (name, value) in enumerate(TEXT.items())],
               groups=[dict(name='验收专用', items=[
                   dict(id='trigger-ascii', text='【CB-ASCII-OK】', trigger='cbqa'),
                   dict(id='trigger-ime', text='【CB-NIHAO-EXPANDED】', trigger='nihao')])])
Path(config.DATA_FILE).write_text(json.dumps(fixture, ensure_ascii=False), encoding='utf-8')
FIXTURE_HASH = digest(Path(config.DATA_FILE))

PAGE = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>ClawBoard Acceptance</title>
<style>body{font:18px "Microsoft YaHei",sans-serif;max-width:1100px;margin:26px auto;padding:0 22px;color:#182436;background:#f5f7fa}h1{font-size:27px}section{background:white;padding:18px;margin:16px 0;border-radius:10px;border:1px solid #d2d9e4}button{font:inherit;padding:9px 16px;margin:6px 8px 10px 0;cursor:pointer}input,textarea,[contenteditable]{display:block;box-sizing:border-box;width:100%;padding:10px;font:20px "Microsoft YaHei",sans-serif;border:2px solid #899dbb;border-radius:5px;background:white}textarea{height:145px}[contenteditable]{min-height:70px}.hint{font-size:15px;color:#4c5d76}.result{font-weight:bold;color:#186a35;min-height:25px}#keyboard{height:120px}#stage{color:#1857a2}</style>
<h1>ClawBoard 本地验收 · 临时数据 / NO_SAVE</h1>
<p class="hint">这个页面只和本机通信。不读取真实历史；测试结果只记录匹配与长度。浏览器测试按钮会调用真实 ClawBoard 粘贴队列。</p>
<p id="stage">当前阶段：浏览器粘贴</p>
<section><button id="single-button" onclick="pasteCase('single')">测试一：粘贴到单行框</button><input id="single" aria-label="单行粘贴验收框"><p id="single-result" class="result"></p></section>
<section><button id="multi-button" onclick="pasteCase('multi')">测试二：粘贴中文、换行和表情</button><textarea id="multi" aria-label="多行粘贴验收框"></textarea><p id="multi-result" class="result"></p></section>
<section><button id="rich-button" onclick="pasteCase('rich')">测试三：粘贴到富文本框</button><div id="rich" role="textbox" aria-label="富文本粘贴验收框" contenteditable="true"></div><p id="rich-result" class="result"></p></section>
<section><h2>实际键盘 / 输入法测试区</h2><p class="hint">先等待指导。这里只使用合成内容；cbqa 和 nihao 是测试触发词。自动展开只支持独立“英文（美国）”键盘；微软拼音的“中”和“英”模式均暂停展开。KEEP| 是用于检查误删的前缀。</p><textarea id="keyboard" aria-label="实际键盘和输入法验收框" spellcheck="false">KEEP| </textarea><p id="keyboard-result" class="result"></p><button id="enable-button" onclick="post('action',{name:'enable_trigger'})">启用测试触发词</button><button id="disable-button" onclick="post('action',{name:'disable_trigger'})">停用测试触发词</button></section>
<p class="hint">测试结束前保留本页和“ClawBoard 验收专用”面板。面板使用独立临时数据；不会保存本次编辑。</p>
<script>
const expected=__EXPECTED__, key=__KEY__;
const counts={};
function post(path,data){return fetch('/'+path,{method:'POST',headers:{'Content-Type':'application/json','X-Acceptance-Key':key},body:JSON.stringify(data)}).then(r=>r.json());}
function valueOf(el){return el.isContentEditable?el.innerText:el.value;}
function observe(id,event){const el=document.getElementById(id),text=valueOf(el);counts[id]=counts[id]||{paste:0,input:0,compositionstart:0,compositionend:0};counts[id][event]=(counts[id][event]||0)+1;
const match=id==='keyboard'?text==='KEEP| 【CB-ASCII-OK】':text===expected[id];
const summary={field:id,match:match,length:text.length,counts:counts[id],prefix_preserved:id==='keyboard'?text.startsWith('KEEP|'):null,ime_replacement:id==='keyboard'?text.includes('【CB-NIHAO-EXPANDED】'):null,ime_match:id==='keyboard'?text==='KEEP| 你好':null};
post('observe',summary);document.getElementById(id+'-result').textContent=id==='keyboard'?(summary.ime_match?'中文提交完整匹配 ✓；':'')+'前缀 '+(summary.prefix_preserved?'保留':'发生变化')+'；当前字符数 '+text.length:(match?'内容完全匹配 ✓':'等待粘贴或内容尚未匹配');}
function pasteCase(id){const el=document.getElementById(id);if(el.isContentEditable)el.innerText='';else el.value='';el.focus();post('action',{name:'paste_'+id});}
for(const id of ['single','multi','rich','keyboard'])for(const ev of ['paste','input','compositionstart','compositionend'])document.getElementById(id).addEventListener(ev,()=>setTimeout(()=>observe(id,ev),0));
setInterval(()=>fetch('/status').then(r=>r.json()).then(s=>{document.getElementById('stage').textContent='当前阶段：'+(s.stage==='ime'?'输入法与触发词（监听已启用）':'浏览器粘贴（触发监听关闭）');}),1200);
</script></html>'''
PAGE = PAGE.replace('__EXPECTED__', json.dumps(TEXT, ensure_ascii=False)).replace('__KEY__', json.dumps(KEY))
PAGE = PAGE.replace('<title>ClawBoard Acceptance</title>', '<title>' + TITLE + '</title>')


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, data, code=200, html=False):
        body = data.encode('utf-8') if html else json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'text/html; charset=utf-8' if html else 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def allowed(self):
        return self.headers.get('Host') == self.server.server_name_header

    def do_GET(self):
        if not self.allowed():
            return self.reply({}, 403)
        if self.path == '/':
            return self.reply(PAGE, html=True)
        if self.path == '/status':
            with LOCK:
                return self.reply(STATE)
        self.reply({}, 404)

    def do_POST(self):
        if not self.allowed() or self.headers.get('X-Acceptance-Key') != KEY:
            return self.reply({}, 403)
        size = int(self.headers.get('Content-Length', '0'))
        if not 0 < size <= 2048:
            return self.reply({}, 400)
        try:
            body = json.loads(self.rfile.read(size))
            if self.path == '/action':
                name = body.get('name')
                if name not in ('paste_single', 'paste_multi', 'paste_rich',
                                'enable_trigger', 'disable_trigger', 'quit'):
                    return self.reply({}, 400)
                COMMANDS.put_nowait(name)
            elif self.path == '/observe':
                field = body.get('field')
                if field not in (*TEXT, 'keyboard'):
                    return self.reply({}, 400)
                # Input正文从未发送到服务端；只接受固定摘要字段。
                record = {k: body.get(k) for k in ('match', 'length', 'counts',
                                                  'prefix_preserved', 'ime_replacement', 'ime_match')}
                with LOCK:
                    STATE['observations'][field] = record
            else:
                return self.reply({}, 404)
            self.reply({'accepted': True})
        except (ValueError, queue.Full, TypeError):
            self.reply({}, 400)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args()
    import tkinter as tk
    from unittest.mock import patch
    import ClawBoard as C
    C.NO_SAVE = True
    from clawboard.win32 import init_dpi_awareness, top_hwnd, u32, window_title_of
    from clawboard.windows_layout import keyboard_layout
    from clawboard.trigger import is_supported_trigger_layout
    from clawboard.win32 import target_focus_hwnd
    init_dpi_awareness()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.daemon_threads = True
    server.server_name_header = '127.0.0.1:%d' % server.server_port
    url = 'http://' + server.server_name_header + '/'
    threading.Thread(target=server.serve_forever, daemon=True).start()
    root = tk.Tk()
    with patch.object(C.ClawBoard, 'catchup_clipboard', lambda app: False):
        app = C.ClawBoard(root)
    root.title('ClawBoard 验收专用 · NO_SAVE')
    app.title_lb.configure(text='验收专用 · NO_SAVE')
    bound_target = [0]
    app._ensure_paste()
    perform_trigger = app._paste_backend.perform_trigger

    def in_test_page(target):
        try:
            return (bool(target) and target == bound_target[0]
                    and int(u32.GetForegroundWindow() or 0) == target
                    and TITLE in (window_title_of(target) or ''))
        except Exception:
            return False

    def scoped_trigger(request, *, cancelled=None):
        class ScopedCancellation:
            def is_set(self):
                return bool((cancelled and cancelled.is_set()) or not in_test_page(request.target))
        return perform_trigger(request, cancelled=ScopedCancellation())
    app._paste_backend.perform_trigger = scoped_trigger
    original = app._paste_finished

    def finished(request, result):
        original(request, result)
        with LOCK:
            STATE['operations'].append(dict(token=request.token, copied=result.copied,
                                             pasted=result.pasted, error=result.error))
    app._paste_finished = finished
    trigger_finished = app._trigger_paste_finished

    def finish_trigger(result):
        trigger_finished(result)
        with LOCK:
            STATE['trigger_operations'].append(dict(copied=result.copied,
                                                     pasted=result.pasted, error=result.error))
    app._trigger_paste_finished = finish_trigger
    metadata = dict(url=url, directory=str(SESSION), pid=os.getpid(), no_save=True,
                    hwnd=top_hwnd(root), key=KEY)
    (SESSION / 'session.json').write_text(json.dumps(metadata), encoding='utf-8')
    (Path(tempfile.gettempdir()) / 'ClawBoard-acceptance-current.json').write_text(
        json.dumps(metadata), encoding='utf-8')
    print(json.dumps({k: v for k, v in metadata.items() if k != 'key'}, ensure_ascii=False), flush=True)

    def tick():
        try:
            name = COMMANDS.get_nowait()
        except queue.Empty:
            name = None
        if name == 'quit':
            app.quit_app()
            return
        if name in ('enable_trigger', 'disable_trigger'):
            enabled = name == 'enable_trigger'
            bound_target[0] = 0
            app.st['trigger_enabled'] = enabled
            app.apply_trigger_setting()
            if enabled:
                engine = app._trigger_engine
                feed = engine.feed

                def test_page_feed(ch):
                    # Test-only nihao must never replace input in a real app.
                    hwnd = int(u32.GetForegroundWindow() or 0)
                    if TITLE not in (window_title_of(hwnd) or ''):
                        engine.reset()
                        return None
                    if not bound_target[0]:
                        bound_target[0] = hwnd
                    if not in_test_page(hwnd):
                        engine.reset()
                        return None
                    return feed(ch)
                engine.feed = test_page_feed
            with LOCK:
                STATE['stage'] = 'ime' if enabled else 'browser'
        elif name and name.startswith('paste_'):
            hwnd = int(u32.GetForegroundWindow() or 0)
            if 'ClawBoard Acceptance' in (window_title_of(hwnd) or ''):
                app.prev_hwnd = hwnd
                if app.hidden:
                    app.hidden = False
                    root.deiconify()
                app.paste(TEXT[name[6:]], force=True)
            else:
                with LOCK:
                    STATE['operations'].append({'copied': False, 'pasted': False,
                                                'error': '测试页不在前台，未发送粘贴'})
        with LOCK:
            from clawboard import windows_hooks
            foreground = int(u32.GetForegroundWindow() or 0)
            layout = (keyboard_layout(target_focus_hwnd(foreground))
                      if TITLE in (window_title_of(foreground) or '') else 0)
            STATE.update(ready=True, no_save=bool(runtime.NO_SAVE),
                         hidden=app.hidden, hotkey=app.st.get('hotkey'),
                         hotkey_ok=app.hotkey_ok, temporary_data=True,
                         trigger_active=bool(windows_hooks._hook),
                         trigger_scope_hwnd=bound_target[0],
                         test_page_layout_supported=is_supported_trigger_layout(layout),
                         trigger_test_page_only=True)
            (SESSION / 'results.json').write_text(json.dumps(STATE, ensure_ascii=False), encoding='utf-8')
        root.after(80, tick)
    root.after(80, tick)
    try:
        root.mainloop()
    finally:
        try:
            app.st['trigger_enabled'] = False
            app.apply_trigger_setting()
            app.close_paste()
            if not app.application.closed:
                app.bridge.close()
            app.hw.stop()
            app.hw.join(3)
        finally:
            server.shutdown()
            server.server_close()
            after = {p: digest(Path(p)) for p in BEFORE}
            unchanged = before_equal = BEFORE == after
            summary = dict(real_hashes_unchanged=unchanged,
                           fixture_hash_unchanged=digest(Path(config.DATA_FILE)) == FIXTURE_HASH)
            (SESSION / 'data-after.json').write_text(json.dumps(after), encoding='utf-8')
            (SESSION / 'safety-result.json').write_text(json.dumps(summary), encoding='utf-8')
            print(json.dumps(summary), flush=True)
            if not before_equal:
                raise RuntimeError('real data hash changed')


if __name__ == '__main__':
    main()
