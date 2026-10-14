# -*- coding: utf-8 -*-
"""DataMixin（数据层）+ SystemMixin（系统接入层）。

DataMixin：norm_item / load_data / save_now / validate / save / note / next_seq / ingest / _late_source
SystemMixin：setup_system / apply_hotkey / on_hotkey / on_tray / poll_bg / _poll_hotkey /
             poll_clip / quit_app / toggle_listen / tray_menu / about
"""
import hashlib
import json
import os
import time
import threading
import queue
import tkinter as tk

from clawboard import runtime
from clawboard import sound
from clawboard import update
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
    capture_source, window_title_of, get_autostart,
    start_keyboard_hook, stop_keyboard_hook, send_backspaces, send_ctrl_v,
    is_fullscreen_window, top_hwnd,
)
from clawboard.clipboard import (
    clip_seq, clip_read, clip_read_files, clip_is_private, scan_sensitive, clip_write,
)
from clawboard.trigger import TriggerEngine
from clawboard.image import clipboard_has_image, read_clipboard_dib, dib_to_png
from clawboard.tag import detect_tags
from clawboard.hotkey import HiddenWindow
from clawboard.widgets import Dialog
# 空库判定复用 onboard 的现成实现：是「是否显示首次启动引导卡片」的唯一来源，
# 两处若各写一套，补记与引导就会因判定口径不同而互相打架。
from clawboard.onboard import is_empty_data


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
        # 复制反馈：视觉 toast 与听觉音效是**两个独立开关**，互不影响。
        #
        # 这里（而非 poll_clip）挂音效是关键：poll_clip 每 400ms 轮询一次，
        # 若挂在那里会在"空剪贴板"上反复响；ingest 只在下述条件全满足时才走到这行 ——
        # 序列号真的变了、非空文本、长度过滤与忽略规则都放行 —— 即"确实记录了一条内容"。
        # manual=True（拆词/变换存新条目）是用户对面板的操作、不是一次剪贴，故两者都不触发。
        if not manual:
            if self.st.get('show_toast', True):
                self.show_copy_toast(txt)
            if self.st.get('sound_copy'):
                sound.play_copy()

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

    # ---------- P1-3 自动更新 ----------
    def setup_update_check(self):
        """启动时静默检查一次更新（带 1 小时频率闸）。

        为什么 NO_SAVE 模式直接返回：自测/压测/截图模式（runtime.NO_SAVE=True）既不该写盘、
        也不该联网 —— 与本项目"绝不污染真实数据"同一约定，且避免批量跑回归时反复打
        GitHub 未认证配额、把测试拖慢拖不稳定。
        """
        if runtime.NO_SAVE:
            return
        try:
            if not update.should_check(self.st, now_ms()):
                return
        except Exception:
            return
        self.start_update_check(manual=False)

    def start_update_check(self, manual=False, on_result=None):
        """发起一次后台检查更新。

        manual=True 时忽略频率闸（设置页「检查更新」按钮用）。无论手动/自动，拿到结果后
        都写回 update_checked_at —— 既供频率闸下次判断，也让设置页"常驻显示"复用同一次结果。
        结果经 update.check_async 回到**主线程**再处理（写 settings / 弹 tip / 调 UI）。
        """
        def done(ver):
            try:
                self.st['update_checked_at'] = now_ms()
                self.save(True)
            except Exception:
                pass
            update.LATEST = ver
            new = bool(ver) and update.is_newer(ver, APP_VER)
            update.LATEST_NEW = new
            if new:
                self.tip('发现新版本 %s，可在「设置」里前往下载' % ver)
            try:
                self.refresh_update_marker()
            except Exception:
                pass
            if on_result:
                try:
                    on_result(ver, new)
                except Exception:
                    pass

        try:
            update.check_async(self.root, done)
        except Exception as e:
            self.note('更新检查启动失败：%s' % e)

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
                own = int(self.root.winfo_id())
                own_top = top_hwnd(self.root)
                if h and h not in (own, own_top):
                    self.prev_hwnd = h
                # 前台是否全屏（排除自己 / 桌面 Shell）—— 供「全屏时不再置顶」用。
                # 这里已经有 GetForegroundWindow，顺手判一次，成本极低。
                self._fg_fullscreen = (bool(h) and h not in (own, own_top)
                                       and is_fullscreen_window(h, own_top))
            except Exception:
                pass
            if self._tray_menu:
                self._tray_menu = False
                self.tray_menu()
            if self._need_show:
                self._need_show = False
                self._user_pulled = True       # 后台请求显示 = 用户要它出来 → 主动呼出
                self.root.deiconify()
                if not self.ensure_onscreen():
                    self.render()
            if getattr(self, '_paste_fail', False):
                self._paste_fail = False
                self.tip('目标窗口拒绝焦点（可能是管理员权限），已复制，请手动 Ctrl+V')
            if self.hotkey_fallback:
                self._poll_hotkey()
            self.sync_topmost()        # 按全屏状态落地实际置顶（放在 _need_show 之后）
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
    def _read_clip_image(self):
        """读剪贴板图片并转成 PNG，返回 (png 字节, 宽, 高)；无图片/失败返回 None。

        抽成独立方法（而非留在 _ingest_image 里）是为了让 poll_clip 与
        catchup_clipboard 复用同一次读取+转换：补记需要先拿到 PNG 的哈希去查重，
        若各读一次就得多开一次剪贴板、还可能两次读到不同内容。
        """
        dib = read_clipboard_dib()
        if not dib:
            return None
        try:
            return dib_to_png(dib)
        except Exception as e:
            self.note('图片转换失败：%s' % e)
            return None

    def _store_image(self, png, w, h, quiet=False):
        """把已转好的 PNG 落盘并入库（含条数裁剪）。

        quiet=True 用于补记场景：用户并没有在复制，不弹「已记录图片」提示、
        也不播复制音（理由见 catchup_clipboard）。
        返回是否成功入库（落盘/建目录失败返回 False），供补记判断"是否真的补了"。
        """
        img_dir = os.path.join(BASE_DIR, 'images')
        try:
            os.makedirs(img_dir, exist_ok=True)
        except Exception:
            return False
        fname = '%d.png' % now_ms()
        try:
            with open(os.path.join(img_dir, fname), 'wb') as f:
                f.write(png)
        except Exception as e:
            self.note('图片保存失败：%s' % e)
            return False
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
        if not quiet:
            self.tip('已记录图片 %d×%d' % (w, h))
            # 复制音：图片也是一条"记下的新内容"，与文本路径保持一致（同样受 sound_copy 开关控制）。
            # 这里没有 manual/去重概念 —— 图片只由轮询触发、每次都是全新条目（不比文本那样查重），
            # 且 poll_clip 里「图片」与「文本/文件路径」是互斥分支，绝不会既走这里又走 ingest，
            # 所以按开关播放即可，不会漏也不会重复响。
            if self.st.get('sound_copy'):
                sound.play_copy()
        return True

    def _ingest_image(self):
        """poll_clip 用：剪贴板里有图片时入库（读 DIB → 转 PNG → 存盘 → 记录）。"""
        got = self._read_clip_image()
        if got:
            self._store_image(got[0], got[1], got[2])

    def _is_dup_text(self, txt):
        """补记去重：剪贴板文本与库中**最新一条**的 text 完全相同 → 视为重复。

        场景：用户在程序运行时复制了 X（已入库）→ 关掉程序 → 再打开，剪贴板里仍是 X。
        若不比对就会把同一条 X 再记一次，用户会莫名其妙多出一条重复。
        只比「最新一条」而不全库搜索，是因为补记的语义就是"最后复制的那条"。
        """
        clip = self.data.get('clip') or []
        return bool(clip) and clip[0].get('text') == txt

    def _is_dup_image(self, png):
        """补记去重：剪贴板图片与库中**最新一条**（当其本身是图片）的 PNG 内容相同 → 重复。

        对比 PNG 的 sha256：同一张图再次复制时 DIB 完全相同，dib_to_png 是确定性编码
        （zlib 对同输入同级别输出一致），所以"字节相同"足以代表"同一张图"。
        最新一条不是图片 / 没有图片文件 / 读盘失败 → 一律当作不重复（宁可多记一条，
        也不要因为一次读盘异常把用户真正新复制的内容丢掉）。
        """
        clip = self.data.get('clip') or []
        if not clip:
            return False
        top = clip[0]
        if top.get('content_type') != 'image':
            return False
        fname = top.get('image_path')
        if not fname:
            return False
        try:
            with open(os.path.join(BASE_DIR, 'images', fname), 'rb') as f:
                return hashlib.sha256(f.read()).digest() == hashlib.sha256(png).digest()
        except Exception:
            return False

    def _handle_clipboard_change(self, quiet=False, dedup=False):
        """剪贴板内容的统一处理：私密 → 图片 → 文本/文件路径，三选一。

        poll_clip（序列号变化时）与 catchup_clipboard（补记程序未运行期间复制的内容）
        共用这一套分支，避免两处各写一套、日后行为悄悄分叉。

        quiet=True：补记场景，抑制复制音与提示浮窗（用户并没有在复制）。
        dedup=True：补记场景，入库前先与库中最新一条比对，相同则不重复入库。

        返回处理结果字符串，供调用方决定是否需要额外反馈：
          'private' 私密跳过 / 'image' 记了图片 / 'text' 记了文本或文件路径 /
          'empty' 无可记录内容 / 'sensitive' 命中敏感词按设置不入库 /
          'dup' 与库中最新一条相同已跳过（仅 dedup=True 时可能返回）。
        """
        if self.st.get('smart_private', True) and clip_is_private():
            # 密码管理器用这个标记告诉所有监听者「这条别记」。补记时静默跳过即可。
            if not quiet:
                self.tip('这条带了「不要记录」标记，已跳过')
            return 'private'
        if clipboard_has_image():
            got = self._read_clip_image()
            if not got:
                return 'empty'
            png, w, h = got
            if dedup and self._is_dup_image(png):
                return 'dup'
            # 落盘/入库失败就不算"记了图片"，返回 'empty' 避免补记误报成功
            return 'image' if self._store_image(png, w, h, quiet=quiet) else 'empty'
        txt = clip_read()
        if not (txt and txt.strip()):
            # 资源管理器复制文件：剪贴板只有 CF_HDROP、没有文本，
            # 把文件路径当普通文本记录（多条用换行连接）。
            files = clip_read_files()
            if files:
                txt = '\n'.join(files)
        if not (txt and txt.strip()):
            return 'empty'
        if len(txt) > MAX_TEXT:
            txt = txt[:MAX_TEXT] + '\n…（内容超长已截断）'
        if dedup and self._is_dup_text(txt):
            return 'dup'
        hits = scan_sensitive(txt)
        if hits and self.st['skip_sensitive']:
            if not quiet:
                self.tip('检测到%s，按设置不入库' % '/'.join(hits))
            return 'sensitive'
        # manual=quiet：补记时借 ingest 的 manual 语义跳过复制音与提示浮窗
        #（ingest 末尾的音效/toast 只在 manual=False 时触发）。
        self.ingest(txt, hits, manual=quiet)
        return 'text'

    def catchup_clipboard(self):
        """补记「程序未运行时复制的内容」（A 方案）。

        背景：poll_clip 只在剪贴板序列号**变化**时入库；而程序启动那一刻剪贴板里已经
        有内容，clipboard.py 又把初始序列号设成基线，于是"关程序期间复制的那条"永远
        不会入库 —— 这就是用户反馈的"程序没运行时复制的内容不会出现在历史里"。

        Windows 剪贴板只保留**最后一条**，所以这里只能补回"你最后一次复制的那条"，
        更早的无法恢复（技术上限，不试图突破）。

        在「程序启动后」与「监听开关由关变开时」两处触发（关闭监听期间的内容同样会漏）。
        返回是否真的补记了一条（供测试与调用方判断）。
        """
        # ① 用户关掉了监听 → 明确表示不要记录，跳过。
        if not self.st.get('listen'):
            return False
        # ② 库为空 → 跳过。P1-1 的首次启动引导卡片，触发条件正是"整库为空"
        #    （onboard.is_empty_data / should_show）。若这里补读一条，库就不再为空，
        #    引导卡片将永远不显示 —— 新用户第一眼看不到"这是什么、怎么用"。
        #    所以空库时绝不补读（复用 onboard 的判定，保证与引导口径一致）。
        if is_empty_data(self.data):
            return False
        # ③ 补读：复用 poll_clip 的三分支逻辑（私密 → 图片 → 文本/文件路径）。
        #    quiet=True 抑制复制音/toast —— 补读发生在启动时，用户并没有在复制，
        #    突然响一声或弹个浮窗很莫名；dedup=True 与库中最新一条比对，防止"重复记一条"。
        status = self._handle_clipboard_change(quiet=True, dedup=True)
        if status in ('image', 'text'):
            self.tip(self._catchup_tip())
            return True
        # 'empty' / 'private' / 'sensitive' / 'dup' 都属于"没补记"，静默返回。
        return False

    @staticmethod
    def _catchup_tip():
        """补记成功后的提示文案。

        补读出来的这条用户没有印象"我复制过"，很容易疑惑它从哪来，所以要 tip 一句。
        若开机自启没开，再补一句建议：开机自启才能让程序常驻后台、从源头减少漏记。
        """
        msg = '已补记程序未运行时复制的内容'
        try:
            on, _ = get_autostart()
        except Exception:
            on = True     # 读不到注册表就当作已开启，避免无谓地打扰用户
        if not on:
            msg += '；想完全避免漏记：设置 → 开机自启'
        return msg

    def poll_clip(self):
        if not self.st['listen']:
            runtime.LAST_SEQ = clip_seq()
            self.root.after(400, self.poll_clip)
            return
        try:
            seq = clip_seq()
            if seq != runtime.LAST_SEQ:
                runtime.LAST_SEQ = seq
                # 三分支逻辑抽到 _handle_clipboard_change，与「补记」共用（见 catchup_clipboard）
                self._handle_clipboard_change()
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
        was = self.st['listen']
        self.st['listen'] = not self.st['listen']
        self.save(True)
        self.tip('监听已暂停' if not self.st['listen'] else '监听已恢复')
        # 由关变开：关闭监听期间复制的内容同样会漏，重开时补记一次
        #（catchup 成功时会把上面的 tip 覆盖成"已补记…"，用户就知道这条哪来的）。
        if not was and self.st['listen']:
            self.catchup_clipboard()

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
