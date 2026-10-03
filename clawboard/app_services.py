# -*- coding: utf-8 -*-
"""DataMixin（数据层）+ SystemMixin（系统接入层）。

DataMixin：norm_item / load_data / save_now / validate / save / note / next_seq / ingest / _late_source
SystemMixin：setup_system / apply_hotkey / on_hotkey / on_tray / poll_bg / _poll_hotkey /
             poll_clip / quit_app / toggle_listen / tray_menu / about
"""
import json
import os
import time
import threading
import queue
import tkinter as tk

from clawboard import runtime
from clawboard.config import (
    APP_NAME, APP_VER, DATA_FILE, CRASH_LOG, DEFAULT_SETTINGS,
    FONT, MAX_TEXT, SCHEMA_VERSION, rotate_log_if_needed, BASE_DIR,
)
from clawboard.theme import T
from clawboard.runtime import uid, now_str
from clawboard.classify import classify, crop_items, detect_content_type, byte_size, length_filtered
from clawboard.timefmt import now_ms, match_ignore, backup_data, migrate
from clawboard.win32 import (
    u32, MOD_CONTROL, MOD_SHIFT, MOD_ALT, VK_V, VK_CONTROL,
    capture_source, window_title_of,
    start_keyboard_hook, stop_keyboard_hook, send_backspaces, send_ctrl_v,
)
from clawboard.clipboard import clip_seq, clip_read, clip_is_private, scan_sensitive, clip_write
from clawboard.trigger import TriggerEngine
from clawboard.image import clipboard_has_image, read_clipboard_dib, dib_to_png
from clawboard.tag import detect_tags
from clawboard.hotkey import HiddenWindow
from clawboard.widgets import Dialog


class DataMixin:
    # ---------- 数据 ----------
    @staticmethod
    def norm_item(it, seq):
        """保证单条记录字段齐全（任何缺字段都在这里兜住）"""
        if not isinstance(it, dict):
            return None
        if not isinstance(it.get('text'), str):
            return None
        if not it.get('created_at'):
            it['created_at'] = now_ms() - seq * 1000
            it['is_estimated'] = 1
        it.setdefault('is_estimated', 0)
        it.setdefault('seq', seq)
        it.setdefault('updated_at', it.get('created_at'))
        it.setdefault('last_used_at', None)
        it.setdefault('source_app', 'unknown')
        it.setdefault('source_title', None)
        it.setdefault('copy_count', 1)
        it.setdefault('fav', 0)
        it.setdefault('use_count', 0)
        it.setdefault('pinned', 0)
        it.setdefault('meta', None)
        it.setdefault('sens', None)
        it.setdefault('time', time.strftime('%m-%d %H:%M',
                                            time.localtime(it['created_at'] / 1000.0)))
        if not it.get('content_type'):
            it['content_type'] = detect_content_type(it.get('text', ''))
        if not it.get('content_size'):
            it['content_size'] = byte_size(it.get('text', ''))
        it.setdefault('id', uid())
        return it

    def load_data(self):
        # 注意：schema_version 默认必须是 1，否则老文件（无该字段）会被误判为已迁移
        d = {'clip': [], 'groups': [{'name': '默认', 'items': []}], 'gi': 0,
             'geom': None, 'settings': dict(DEFAULT_SETTINGS), 'schema_version': 1}
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                for k in list(d):
                    if k in loaded:
                        d[k] = loaded[k]
            except Exception:
                self.note('数据文件读取失败，已用默认值启动（原文件未改动）')
        if int(d.get('schema_version', 1)) < SCHEMA_VERSION:
            bak = backup_data()
            try:
                d = self.validate(migrate(d))
                self.save_now(d)
                self.note('数据已迁移到 v%d（备份：%s）' % (SCHEMA_VERSION, bak))
            except Exception as e:
                self.note('迁移失败，已回滚备份：%s' % e)
                if bak and os.path.exists(bak):
                    try:
                        with open(bak, 'rb') as a:
                            with open(DATA_FILE, 'wb') as b:
                                b.write(a.read())
                    except Exception:
                        pass
                d = self.validate(d)
        else:
            d = self.validate(d)
        return d

    def save_now(self, d=None):
        """同步落盘（迁移后立即写回用）"""
        if runtime.NO_SAVE:
            return False
        d = d or self.data
        tmp = DATA_FILE + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
            os.replace(tmp, DATA_FILE)
            return True
        except Exception as e:
            self.note('保存失败：%s' % e)
            return False

    @staticmethod
    def validate(d):
        """配置 schema 校验：任何非法字段回退默认值，绝不崩溃"""
        if not isinstance(d.get('clip'), list):
            d['clip'] = []
        seq = 0
        normed = []
        for x in d['clip']:
            seq += 1
            it = DataMixin.norm_item(x, seq)
            if it:
                normed.append(it)
        d['clip'] = normed
        gs = []
        raw_groups = d.get('groups')
        if not isinstance(raw_groups, list):
            raw_groups = []
        for g in raw_groups:
            if not isinstance(g, dict) or not isinstance(g.get('name'), str):
                continue
            items = []
            for x in g.get('items', []):
                seq += 1
                it = DataMixin.norm_item(x, seq)
                if it:
                    items.append(it)
            gs.append({'name': g['name'], 'items': items})
        d['groups'] = gs or [{'name': '默认', 'items': []}]
        try:
            gi = int(d.get('gi', 0))
        except Exception:
            gi = 0
        d['gi'] = min(max(0, gi), len(d['groups']) - 1)
        s = d.get('settings') if isinstance(d.get('settings'), dict) else {}
        fixed = dict(DEFAULT_SETTINGS)
        for k, v in fixed.items():
            if k in s and isinstance(s[k], type(v)):
                fixed[k] = s[k]
        if fixed['theme'] not in ('dark', 'light'):
            fixed['theme'] = 'dark'
        try:
            fixed['max_items'] = min(5000, max(10, int(fixed['max_items'])))
        except Exception:
            fixed['max_items'] = 500
        d['settings'] = fixed
        if not isinstance(d.get('geom'), str):
            d['geom'] = None
        return d

    def save(self, later=False):
        if runtime.NO_SAVE:
            return

        def do():
            # 折叠时窗口只有 210x34 的标题条。若把这个尺寸写进 geom，就会顶掉
            # "展开后该回到哪" —— 下次展开只能落到最小尺寸、还被丢到右下角。
            # 所以折叠期间不更新 geom，展开时的位置由 _expanded_geometry() 还原。
            if not self.collapsed:
                self.data['geom'] = self.root.geometry()
            tmp = DATA_FILE + '.tmp'
            try:
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=1)
                os.replace(tmp, DATA_FILE)
            except Exception as e:
                self.note('保存失败：%s' % e)
            self.save_timer = None
        if later:
            if self.save_timer:
                self.root.after_cancel(self.save_timer)
            self.save_timer = self.root.after(300, do)
        else:
            do()

    def note(self, msg):
        """写运行日志。绝不写入剪贴板原文。"""
        # NO_SAVE 的自测/压测实例同样不该往真实 crash.log 里写字：
        # 自测会反复建实例，每次都留一行"热键被占用"，把真正有用的诊断记录刷掉
        if runtime.NO_SAVE:
            return
        try:
            # crash.log 上限：超过 512KB 截断，只保留最近 ~256KB（诊断只看最近的）
            rotate_log_if_needed(CRASH_LOG)
            with open(CRASH_LOG, 'a', encoding='utf-8') as f:
                f.write('[%s] %s\n' % (time.strftime('%F %T'), msg))
        except Exception:
            pass

    def next_seq(self):
        self._seq += 1
        return self._seq

    def ingest(self, txt, hits=None, manual=False):
        """入库：重复内容只刷新 updated_at / copy_count，created_at 永不改写。
        manual=True 是用户手动添加（拆词、变换存新条目），此时跳过忽略规则与长度过滤。"""
        ts = now_ms()
        # 不在这里做 50ms 延迟重试：那会卡住 UI 线程。抓不到就交给后台线程补抓。
        src, src_hwnd = capture_source(self.root.winfo_id(), delay_retry=False)
        # 只在真的要用标题时才去取（取标题是有开销的）
        title = None
        if src_hwnd and (self.st['record_title'] or (self.st.get('ignore_titles') or '').strip()):
            title = window_title_of(src_hwnd)
        if not manual:
            lo = int(self.st.get('min_len') or 0)
            hi = int(self.st.get('max_len') or 0)
            msg = length_filtered(txt, lo, hi)
            if msg:
                self.tip(msg)
                return
            hit = match_ignore(src, title, self.st.get('ignore_apps'),
                               self.st.get('ignore_titles'))
            if hit:
                self.tip('命中忽略规则（%s），未记录' % hit)
                return
        dup = None
        for x in self.data['clip']:
            if x.get('text') == txt:
                dup = x
                break
        if dup is not None:
            # 统一用 rec 指向"本次要置顶的那条"，后面收尾逻辑只写一份。
            # 原来这里只操作 dup、不给 rec 赋值，收尾时 rec['source_title'] 会
            # UnboundLocalError —— 表现为"重复复制一条，列表毫无反应"
            # （crash.log 里刷了几十条「监听异常：cannot access local variable 'rec'」）
            rec = dup
            rec['copy_count'] = int(rec.get('copy_count') or 1) + 1
            rec['updated_at'] = ts
            rec['time'] = now_str()
            if src != 'unknown':
                rec['source_app'] = src
            self.data['clip'].remove(rec)      # 置顶由下面的统一 insert 完成
        else:
            exist = [int(x.get('created_at') or 0) for x in self.data['clip']]
            mx = max(exist) if exist else 0
            if ts < mx:
                self.note('系统时钟回拨（新 %d < 库中最大 %d），本次用 seq 兜底排序' % (ts, mx))
                ts = mx + 1
            rec = {'id': uid(), 'text': txt, 'created_at': ts, 'updated_at': ts,
               'seq': self.next_seq(), 'source_app': src,
               'content_type': detect_content_type(txt),
               'kind_auto': classify(txt)[0],   # 入库时判一次类型，渲染层不再重算
               'content_size': byte_size(txt), 'copy_count': 1, 'fav': 0,
               'is_estimated': 0}
            tags = detect_tags(txt)
            if tags:
                rec['tags'] = tags
        # 空值字段一律不落盘：1 万条能省下 MB 级内存与文件体积
        if title and self.st['record_title']:
            rec['source_title'] = title
        if hits:
            rec['sens'] = hits
        self.data['clip'].insert(0, rec)
        if src == 'unknown':
            threading.Thread(target=self._late_source, args=(rec['id'],),
                             daemon=True).start()
        lim = int(self.st['max_items'])
        if len(self.data['clip']) > lim:
            removed = [x for x in self.data['clip'][lim:] if not x.get('fav')]
            self._purge_image_files(removed)
            self.data['clip'] = crop_items(self.data['clip'], lim)
        self.save(True)
        if self.tab == 'clip':
            self.render()
        # 复制提示浮窗（手动添加如拆词/变换不弹）
        if not manual and self.st.get('show_toast', True):
            self.show_copy_toast(txt)

    def _late_source(self, rid):
        """后台补抓来源：竞态下第一次可能抓到自己或抓空，50ms 后再试一次"""
        time.sleep(0.05)
        src, hwnd = capture_source(self.root.winfo_id(), delay_retry=False)
        if src == 'unknown':
            return
        for x in self.data['clip']:
            if x.get('id') == rid:
                x['source_app'] = src
                if self.st.get('record_title') and hwnd:
                    t = window_title_of(hwnd)
                    if t:
                        x['source_title'] = t
                break
        else:
            return
        self.save(True)
        try:
            self.root.after(0, self.render)
        except Exception:
            pass


class SystemMixin:
    # ---------- 系统接入 ----------
    def setup_system(self):
        self.hw = HiddenWindow(self.on_hotkey, self.on_tray)
        self.hw.start()
        self.hw.ready.wait(3)
        if not self.hw.tray_add():
            self.note('托盘图标添加失败')
        self.apply_hotkey()
        self.setup_trigger()

    def setup_trigger(self):
        """启动触发词监听（若设置开启）。全局键盘钩子在独立线程跑消息循环。"""
        if not self.st.get('trigger_enabled'):
            return
        self._trigger_engine = TriggerEngine()
        self._trigger_q = queue.Queue()
        self._refresh_triggers()

        def on_char(ch):
            r = self._trigger_engine.feed(ch)
            if r:
                self._trigger_q.put(r)

        def on_backspace():
            self._trigger_engine.feed_backspace()

        if start_keyboard_hook(on_char, on_backspace):
            n = len(self._trigger_engine.triggers)
            self.note('触发词监听已启动（%d 个触发词）' % n)
            if n:
                threading.Thread(target=self._trigger_worker, daemon=True).start()
        else:
            self.note('触发词监听启动失败')

    def _trigger_worker(self):
        """独立线程：消费触发事件，执行替换（退格 + 剪贴板 + Ctrl+V）。"""
        while True:
            trig, repl = self._trigger_q.get()
            try:
                time.sleep(0.05)                    # 等分隔符的 keydown/keyup 收尾
                send_backspaces(len(trig) + 1)      # 删掉 触发词 + 分隔符
                time.sleep(0.03)
                clip_write(repl)
                send_ctrl_v()
            except Exception as e:
                self.note('触发词替换失败：%s' % e)

    def _refresh_triggers(self):
        """从常用语收集触发词映射 {触发词: 内容}。"""
        trigs = {}
        for g in self.data.get('groups', []):
            for it in g.get('items', []):
                t = (it.get('trigger') or '').strip()
                if t:
                    trigs[t] = it.get('text') or ''
        self._trigger_engine.set_triggers(trigs)

    def apply_trigger_setting(self):
        """触发词开关切换后调用：开 → 启动钩子，关 → 卸载钩子。"""
        if self.st.get('trigger_enabled'):
            self.setup_trigger()
        else:
            try:
                stop_keyboard_hook()
            except Exception:
                pass

    def apply_hotkey(self):
        table = {'ctrl+shift+v': (MOD_CONTROL | MOD_SHIFT, VK_V),
                 'alt+v': (MOD_ALT, VK_V),
                 'ctrl+alt+v': (MOD_CONTROL | MOD_ALT, VK_V)}
        # 被占用就自动退到备用组合，而不是直接放弃（Ctrl+Shift+V 常被输入法/其他软件抢）
        want = self.st.get('hotkey', 'ctrl+shift+v')
        order = [want] + [k for k in table if k != want]
        used = None
        for key in order:
            if key in table and self.hw.reg_hotkey(*table[key]):
                used = key
                break
        self.hotkey_ok = bool(used)
        self.hotkey_fallback = (not used)
        if used and used != want:
            self.st['hotkey'] = used
            self.save(True)
            self.note('热键 %s 被占用，自动改用 %s' % (want, used))
            self.tip('热键被占用，已改用 %s' % used.upper())
        elif not used:
            self.note('所有候选热键均注册失败，降级为轮询检测')
            self.tip('热键全被占用，已启用降级检测')

    def on_hotkey(self):
        self.root.after(0, self.toggle_show)

    def on_tray(self, which):
        if which == 'left':
            self.root.after(0, self.toggle_show)
        else:
            self._tray_menu = True

    def poll_bg(self):
        """主线程统一消费后台事件 + 热键降级 + 靠边隐藏 + 前台窗口记录。

        整个循环体包在 try 里：以前任何一处异常都会让这个 after 链断掉，
        后果是面板点了没反应、粘贴后回不来、托盘菜单失效 —— 必须保证永续。
        """
        try:
            try:
                h = u32.GetForegroundWindow()
                if h and h != self.root.winfo_id():
                    self.prev_hwnd = h
            except Exception:
                pass
            if self._tray_menu:
                self._tray_menu = False
                self.tray_menu()
            if self._need_show:
                self._need_show = False
                self.root.deiconify()
                self.root.attributes('-topmost', True)
                if not self.ensure_onscreen():
                    self.render()
            if getattr(self, '_paste_fail', False):
                self._paste_fail = False
                self.tip('目标窗口拒绝焦点（可能是管理员权限），已复制，请手动 Ctrl+V')
            if self.hotkey_fallback:
                self._poll_hotkey()
            self.edge_update()
        except Exception as e:
            self.note('poll_bg 异常已吞掉（循环继续）：%s' % e)
        self.root.after(120, self.poll_bg)

    def _poll_hotkey(self):
        """RegisterHotKey 失败时的降级：轮询检测组合键（带按下防抖）"""
        try:
            down = ((u32.GetAsyncKeyState(VK_CONTROL) & 0x8000) and
                    (u32.GetAsyncKeyState(0x10) & 0x8000) and      # VK_SHIFT
                    (u32.GetAsyncKeyState(VK_V) & 0x8000))
        except Exception:
            return
        if down and not self._hk_down:
            self._hk_down = True
            self.toggle_show()
        elif not down:
            self._hk_down = False

    # ---------- 循环 ----------
    def _ingest_image(self):
        """剪贴板里有图片时入库：读 DIB → 转 PNG → 存盘 → 记录条目。"""
        dib = read_clipboard_dib()
        if not dib:
            return
        try:
            png, w, h = dib_to_png(dib)
        except Exception as e:
            self.note('图片转换失败：%s' % e)
            return
        img_dir = os.path.join(BASE_DIR, 'images')
        try:
            os.makedirs(img_dir, exist_ok=True)
        except Exception:
            return
        fname = '%d.png' % now_ms()
        try:
            with open(os.path.join(img_dir, fname), 'wb') as f:
                f.write(png)
        except Exception as e:
            self.note('图片保存失败：%s' % e)
            return
        ts = now_ms()
        rec = {'id': uid(), 'text': '[图片]', 'created_at': ts, 'updated_at': ts,
               'seq': self.next_seq(), 'content_type': 'image',
               'image_path': fname, 'image_w': w, 'image_h': h,
               'copy_count': 1, 'fav': 0, 'is_estimated': 0}
        self.data['clip'].insert(0, rec)
        lim = int(self.st['max_items'])
        if len(self.data['clip']) > lim:
            removed = [x for x in self.data['clip'][lim:] if not x.get('fav')]
            self._purge_image_files(removed)
            self.data['clip'] = crop_items(self.data['clip'], lim)
        self.save(True)
        if self.tab == 'clip':
            self.render()
        self.tip('已记录图片 %d×%d' % (w, h))

    def poll_clip(self):
        if not self.st['listen']:
            runtime.LAST_SEQ = clip_seq()
            self.root.after(400, self.poll_clip)
            return
        try:
            seq = clip_seq()
            if seq != runtime.LAST_SEQ:
                runtime.LAST_SEQ = seq
                if self.st.get('smart_private', True) and clip_is_private():
                    # 密码管理器用这个标记告诉所有监听者「这条别记」
                    self.tip('这条带了「不要记录」标记，已跳过')
                elif clipboard_has_image():
                    self._ingest_image()
                else:
                    txt = clip_read()
                    if txt and txt.strip():
                        if len(txt) > MAX_TEXT:
                            txt = txt[:MAX_TEXT] + '\n…（内容超长已截断）'
                        hits = scan_sensitive(txt)
                        if hits and self.st['skip_sensitive']:
                            self.tip('检测到%s，按设置不入库' % '/'.join(hits))
                        else:
                            self.ingest(txt, hits)
        except Exception as e:
            self.note('监听异常：%s' % e)
        self.root.after(400, self.poll_clip)

    def quit_app(self):
        # 记一条：事后才能区分「用户正常退出」和「进程被外部杀掉」（后者不会留下任何痕迹）
        self.note('用户触发退出（托盘 / Ctrl+Q / 设置里的退出按钮）')
        try:
            stop_keyboard_hook()
        except Exception:
            pass
        try:
            self.hw.unreg_hotkey()
            self.hw.tray_del()
            self.hw.stop()
        except Exception:
            pass
        self.save()
        self.root.destroy()

    def toggle_listen(self):
        self.st['listen'] = not self.st['listen']
        self.save(True)
        self.tip('监听已暂停' if not self.st['listen'] else '监听已恢复')

    def tray_menu(self):
        m = tk.Menu(self.root, tearoff=0, bg=T['panel'], fg=T['fg'], bd=0,
                    activebackground=T['card_h'], activeforeground=T['fg'],
                    font=FONT, relief='flat')
        m.add_command(label='打开面板', command=self.toggle_show)
        m.add_command(label=('⏸ 暂停监听' if self.st['listen'] else '▶ 恢复监听'),
                      command=self.toggle_listen)
        m.add_command(label='⚙ 设置', command=self.open_settings)
        m.add_command(label='⟲ 面板找不到了？重置位置', command=self.reset_position)
        m.add_command(label='ℹ 关于', command=self.about)
        m.add_separator()
        m.add_command(label='✕ 退出', command=self.quit_app)
        try:
            m.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        except Exception:
            pass

    def about(self):
        Dialog(self.root, '关于 ' + APP_NAME,
               [('', '%s %s\n\n零依赖 Python / tkinter\n数据文件：%s\n\n唤起热键：%s' %
                 (APP_NAME, APP_VER, DATA_FILE, self.st['hotkey']), True)],
               on_ok=lambda v: None, ok_text='知道了').show(430, 260)
