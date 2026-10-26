# -*- coding: utf-8 -*-
"""Tk / Windows system adapter; domain work belongs to application services.

DataMixin：norm_item / load_data / save_now / validate / save / note / next_seq / ingest / _late_source
SystemMixin：setup_system / apply_hotkey / on_hotkey / on_tray / poll_bg / _poll_hotkey /
             poll_clip / quit_app / toggle_listen / tray_menu / about
"""
import hashlib
import json
import os
import time
import threading
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
    start_keyboard_hook, stop_keyboard_hook, target_focus_hwnd,
    is_fullscreen_window, top_hwnd,
)
from clawboard.clipboard import (
    clip_seq, clip_read, clip_read_files, clip_is_private, scan_sensitive,
)
from clawboard.paste_adapter import TriggerRequest
from clawboard.trigger import TriggerEngine, is_supported_trigger_layout
from clawboard.windows_layout import keyboard_layout
from clawboard.windows_focus import window_is_current_process
from clawboard.image import clipboard_has_image, read_clipboard_dib, dib_to_png
from clawboard.tag import detect_tags
from clawboard.hotkey import HiddenWindow
from clawboard.widgets import Dialog
# 空库判定复用 onboard 的现成实现：是「是否显示首次启动引导卡片」的唯一来源，
# 两处若各写一套，补记与引导就会因判定口径不同而互相打架。
from clawboard.onboard import is_empty_data


class SystemMixin:
    # ---------- 系统接入 ----------
    def setup_system(self):
        self.hw = HiddenWindow(self.on_hotkey, self.on_tray, self.bridge.clipboard_changed)
        self.hw.start()
        self._system_deadline = time.monotonic() + 3
        self._finish_system_setup()

    def _finish_system_setup(self):
        if self.application.closed:
            return
        if not self.hw.ready.is_set():
            if time.monotonic() < self._system_deadline:
                self.root.after(30, self._finish_system_setup)
                return
            self.hotkey_fallback = True
            self.note('系统消息线程初始化超时，已启用热键轮询')
            return
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
        self._stop_trigger_worker()
        # 重新启用时必须替换旧闭包，而不是沿用已经停止的监听回调。
        stop_keyboard_hook()
        self._ensure_paste()
        engine = self._trigger_engine = TriggerEngine()
        stopped = self._trigger_stop = threading.Event()
        own = top_hwnd(self.root)
        context = [None]
        pending = self._trigger_pending = [None]
        self._refresh_triggers()

        def reset():
            if pending[0] is not None:
                pending[0].set()
                pending[0] = None
            context[0] = None
            engine.reset()

        def input_target():
            target = int(u32.GetForegroundWindow() or 0)
            focus = int(target_focus_hwnd(target) or 0) if target else 0
            layout = keyboard_layout(focus)
            current = (target, focus, layout)
            if current != context[0]:
                reset()
                context[0] = current
            if (stopped.is_set() or not target or target == own
                    or window_is_current_process(target) is not False
                    or not is_supported_trigger_layout(layout)):
                reset()
                return None
            if pending[0] is not None:
                pending[0].set()
                pending[0] = None
            return current

        def on_char(ch):
            if ch in ('\n', '\t'):
                reset()
                return
            current = input_target()
            if current is None:
                return
            r = engine.feed(ch)
            if r:
                engine.reset()
                cancellation = pending[0] = threading.Event()
                self.application.dispatcher.post(
                    self._queue_trigger, TriggerRequest(*r, *current), cancellation, stopped)

        def on_backspace():
            if input_target() is not None:
                engine.feed_backspace()

        if start_keyboard_hook(on_char, on_backspace, on_reset=reset):
            n = len(self._trigger_engine.triggers)
            self.note('触发词监听已启动（%d 个触发词）' % n)
        else:
            stopped.set()
            self.note('触发词监听启动失败')

    def _stop_trigger_worker(self):
        """取消旧一代监听及其排队请求；替换由普通粘贴串行 worker 执行。"""
        stopped = getattr(self, '_trigger_stop', None)
        if stopped is not None:
            stopped.set()

    def _refresh_triggers(self):
        """从常用语收集触发词映射 {触发词: 内容}。"""
        pending = getattr(self, '_trigger_pending', None)
        if pending and pending[0] is not None:
            pending[0].set()
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
            self._stop_trigger_worker()
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
        self.application.dispatcher.post(self.toggle_show)

    def on_tray(self, which):
        if which == 'left':
            self.application.dispatcher.post(self.toggle_show)
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
                external = bool(h) and h not in (own, own_top) and window_is_current_process(h) is False
                if external:
                    self.prev_hwnd = h
                # 前台是否全屏（排除自己 / 桌面 Shell）—— 供「全屏时不再置顶」用。
                # 这里已经有 GetForegroundWindow，顺手判一次，成本极低。
                self._fg_fullscreen = bool(external and is_fullscreen_window(h, own_top))
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
            self.sync_window_dpi()
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
        # Legacy diagnostics still call this synchronous entry directly. The
        # production controller guards its own storage, but that cannot protect
        # callers bypassing it; reject before mkdir, image writes or cropping.
        store = getattr(self, '_store', None)
        if store is None:
            store = getattr(getattr(self, 'application', None), 'store', None)
        if runtime.NO_SAVE or (store is not None and store.recovery_required):
            return False
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
          'skip' 被长度过滤/忽略规则拦下未入库 /
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
        # quiet=quiet：补记时只抑制复制音/toast，**不**跳过长度过滤与忽略规则
        #（补记是自动行为，用户的过滤设置必须继续生效）。用 ingest 的返回值判断是否真的
        #入库，被过滤/忽略规则拦下时返回 'skip'，避免补记误报"已补记"。
        return 'text' if self.ingest(txt, hits, quiet=quiet) else 'skip'

    def catchup_clipboard(self):
        """Queue a quiet catch-up; conversion and storage happen outside Tk."""
        if not self.st.get('listen') or is_empty_data(self.data):
            return False
        return self.bridge.request_capture(quiet=True, dedup=True, force=True)

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
        self.bridge.request_capture()
        interval = 1000 if getattr(self.hw, 'clipboard_listener', False) else 400
        self.root.after(interval, self.poll_clip)

    def quit_app(self):
        # 记一条：事后才能区分「用户正常退出」和「进程被外部杀掉」（后者不会留下任何痕迹）
        self.note('用户触发退出（托盘 / Ctrl+Q / 设置里的退出按钮）')
        self.save()
        workbench = getattr(self, '_workbench_window', None)
        if workbench is not None and workbench.win.winfo_exists():
            workbench.close()
        try:
            self.bridge.close()
        except Exception as error:
            self.note('退出前保存失败：' + type(error).__name__)
            self.tip('保存未完成，请检查数据目录后再次退出')
            return
        try:
            stop_trigger = getattr(self, '_stop_trigger_worker', None)
            if stop_trigger:
                stop_trigger()
            stop_keyboard_hook()
        except Exception:
            pass
        try:
            self.hw.unreg_hotkey()
            self.hw.tray_del()
            self.hw.stop()
        except Exception:
            pass
        self.root.destroy()

    def toggle_listen(self):
        was = self.st['listen']
        self.st['listen'] = not self.st['listen']
        if was:
            self.application.invalidate_clipboard()
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
        m.add_command(label='打开工作台', command=self.open_workbench)
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
