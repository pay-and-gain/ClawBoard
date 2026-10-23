"""Serialized paste operations and a small owner-thread UI adapter.

The backend receives plain requests and injected Windows functions. File probes,
PNG decoding and clipboard writes run on one bounded worker. UI callbacks travel
through EventDispatcher; the worker never calls Tk, including root.after.
"""
from dataclasses import dataclass
from pathlib import Path
from threading import Event
import time

from clawboard import runtime
from clawboard.classify import to_plain
from clawboard.config import BASE_DIR
from clawboard.tasks import WorkerTasks
from clawboard.timefmt import now_ms
from clawboard.trigger import is_supported_trigger_layout


@dataclass(frozen=True)
class PasteRequest:
    token: int
    text: str = ''
    image_name: str | None = None
    cid: str | None = None
    target: int = 0
    should_paste: bool = False
    overlap: bool = False
    plain: bool = False
    trim: bool = True


@dataclass(frozen=True)
class PasteResult:
    copied: bool
    pasted: bool = False
    sequence: int | None = None
    error: str = ''


@dataclass(frozen=True)
class TriggerRequest:
    trigger: str
    replacement: str
    target: int
    focus: int
    layout: int = 0


class _AnyCancelled:
    def __init__(self, *events):
        self.events = tuple(event for event in events if event is not None)

    def is_set(self):
        return any(event.is_set() for event in self.events)


class PasteBackend:
    """Native/file operations injected so ordering is testable without Windows."""
    def __init__(self, *, write_text, write_files, looks_files, write_image,
                 read_image, decode_image, can_message, message, activate,
                 send_keys, sequence, sleep=time.sleep, foreground=None,
                 target_focus=None, replace_keys=None, current_sequence=None,
                 read_layout=None, replace_keys_guarded=None, can_inject=None):
        self.write_text = write_text
        self.write_files = write_files
        self.looks_files = looks_files
        self.write_image = write_image
        self.read_image = read_image
        self.decode_image = decode_image
        self.can_message = can_message
        self.message = message
        self.activate = activate
        self.send_keys = send_keys
        self.sequence = sequence
        self.sleep = sleep
        self.foreground = foreground
        self.target_focus = target_focus
        self.replace_keys = replace_keys
        self.current_sequence = current_sequence
        self.read_layout = read_layout
        self.replace_keys_guarded = replace_keys_guarded
        self.can_inject = can_inject

    def write(self, text, cancelled=None):
        files = self.looks_files(text)
        if files:
            paths = [line.strip() for line in text.splitlines() if line.strip()]
            if cancelled and cancelled.is_set():
                return False
            return self.write_files(paths)
        if cancelled and cancelled.is_set():
            return False
        return self.write_text(text)

    def _clipboard_current(self, sequence):
        try:
            return self.current_sequence is None or self.current_sequence() == sequence
        except Exception:
            return False

    def _input_permitted(self, target):
        try:
            # Platform-free fake backends may omit this port. The Windows
            # composition always supplies the conservative integrity check.
            return self.can_inject is None or bool(self.can_inject(target))
        except Exception:
            return False

    def focus_paste(self, target, cancelled=None, expected_sequence=None):
        if not target or (cancelled and cancelled.is_set()):
            return False
        self.sleep(0.06)
        if cancelled and cancelled.is_set():
            return False
        if not self._input_permitted(target):
            return False
        if not self.activate(target, timeout=0.4):
            return False
        self.sleep(0.05)
        if cancelled and cancelled.is_set():
            return False
        if self.foreground and int(self.foreground() or 0) != target:
            return False
        if expected_sequence is not None and not self._clipboard_current(expected_sequence):
            return False
        if not self._input_permitted(target):
            return False
        if not self.send_keys():
            return False
        # SendInput queues keystrokes. Keep the clipboard stable briefly before
        # another queued request can replace it with different content.
        self.sleep(0.12)
        return True

    def perform(self, request, *, before_focus=lambda: True, cancelled=None):
        if cancelled and cancelled.is_set():
            return PasteResult(False, error='粘贴已取消')
        try:
            if request.image_name:
                dib, _, _ = self.decode_image(self.read_image(request.image_name))
                if cancelled and cancelled.is_set():
                    return PasteResult(False, error='粘贴已取消')
                copied = self.write_image(dib)
                large_plain = False
            else:
                text = to_plain(request.text) if request.plain else request.text
                text = text.strip() if request.trim else text
                large_plain = request.plain and len(text.encode('utf-8')) > 5 * 1024 * 1024
                if cancelled and cancelled.is_set():
                    return PasteResult(False, error='粘贴已取消')
                copied = self.write_text(text) if request.plain else self.write(text, cancelled)
        except FileNotFoundError:
            return PasteResult(False, error='图片文件已丢失')
        except Exception as error:
            return PasteResult(False, error='内容读取失败（%s）' % type(error).__name__)
        if not copied:
            return PasteResult(False, error='粘贴已取消' if cancelled and cancelled.is_set()
                               else '剪贴板被占用，写入失败')
        sequence = int(self.sequence())
        if not request.should_paste or large_plain:
            message = '文本超 5MB，已放入剪贴板，请手动 Ctrl+V' if large_plain else ''
            return PasteResult(True, sequence=sequence, error=message)
        if cancelled and cancelled.is_set():
            return PasteResult(True, sequence=sequence, error='已复制，粘贴已取消')
        try:
            if not request.image_name and self.can_message(request.target):
                pasted = (not (cancelled and cancelled.is_set())
                          and self._clipboard_current(sequence)
                          and bool(self.message(request.target)))
            else:
                permitted = not request.overlap or before_focus()
                pasted = permitted and self.focus_paste(request.target, cancelled, sequence)
        except Exception:
            pasted = False
        return PasteResult(True, bool(pasted), sequence,
                           '' if pasted else '目标窗口拒绝焦点或粘贴，已复制，请手动 Ctrl+V')

    def trigger_context_valid(self, request, cancelled=None):
        try:
            return bool(not (cancelled and cancelled.is_set())
                        and request.target and request.focus and self.foreground
                        and self.target_focus and self.read_layout
                        and self._input_permitted(request.target)
                        and is_supported_trigger_layout(request.layout)
                        and int(self.foreground() or 0) == request.target
                        and int(self.target_focus(request.target) or 0) == request.focus
                        and self.read_layout(request.focus) == request.layout
                        and not (cancelled and cancelled.is_set()))
        except Exception:
            return False

    def perform_trigger(self, request, *, cancelled=None):
        """先准备剪贴板；原输入框和独立 US 布局仍一致时才允许删除缩写。"""
        def still_target():
            return self.trigger_context_valid(request, cancelled)

        # 钩子在原按键送达输入框之前回调，需先让分隔符进入目标消息队列。
        self.sleep(0.05)
        if not still_target():
            return PasteResult(False)
        try:
            if not self.write_text(request.replacement):
                return PasteResult(False, error='剪贴板被占用，触发词未替换')
            sequence = int(self.sequence())
        except Exception:
            return PasteResult(False, error='剪贴板写入失败，触发词未替换')
        if not still_target() or not self._clipboard_current(sequence):
            return PasteResult(True, sequence=sequence,
                               error='触发词替换已取消，内容已复制')
        try:
            count = len(request.trigger) + 1
            if self.replace_keys_guarded:
                pasted = bool(self.replace_keys_guarded(
                    count, guard=lambda: still_target() and self._clipboard_current(sequence)))
            else:
                pasted = bool(self.replace_keys and self.replace_keys(count))
        except Exception:
            pasted = False
        if pasted:
            self.sleep(0.12)
        return PasteResult(True, pasted, sequence,
                           '' if pasted else '触发词替换未完成，内容已复制，请检查输入框后手动粘贴')


def windows_backend():
    # Imports stay at the adapter boundary. Tests of PasteBackend need neither
    # winreg nor a desktop, and codec imports remain platform independent.
    from clawboard.clipboard import clip_write, clip_write_files, looks_like_file_list, clip_seq
    from clawboard.image import png_to_dib, write_clipboard_dib
    from clawboard.media import ImageStore
    from clawboard.win32 import (can_paste_message, paste_message, force_foreground,
                                send_ctrl_v, target_focus_hwnd, u32)
    from clawboard.windows_input import send_replacement
    from clawboard.windows_layout import keyboard_layout
    from clawboard.windows_focus import can_send_input
    images = ImageStore(Path(BASE_DIR) / 'images')
    return PasteBackend(write_text=clip_write, write_files=clip_write_files,
                        looks_files=looks_like_file_list, write_image=write_clipboard_dib,
                        read_image=images.read, decode_image=png_to_dib,
                        can_message=can_paste_message, message=paste_message,
                        activate=force_foreground, send_keys=send_ctrl_v,
                        sequence=lambda: runtime.LAST_WRITE_SEQ,
                        foreground=u32.GetForegroundWindow, target_focus=target_focus_hwnd,
                        replace_keys=send_replacement, current_sequence=clip_seq,
                        read_layout=keyboard_layout, replace_keys_guarded=send_replacement,
                        can_inject=can_send_input)


class PasteMixin:
    """Public legacy paste API backed by one bounded serial queue per app."""
    def trim_for_paste(self, text):
        return (text or '').strip() if self.st.get('trim_paste', True) else (text or '')

    def _ensure_paste(self):
        if getattr(self, '_paste_tasks', None) is None:
            self._paste_tasks = WorkerTasks(self.application.dispatcher,
                                            max_workers=1, max_pending=4)
            self._paste_cancelled = Event()
            self._paste_token = 0
            self._paste_yields = set()
        if getattr(self, '_paste_backend', None) is None:
            self._paste_backend = windows_backend()

    def write_clip(self, text):
        """Synchronous compatibility entry; queued paste uses the backend directly."""
        guard = getattr(self, 'ensure_current_results', None)
        if guard and not guard():
            return False
        self._ensure_paste()
        if self._paste_tasks.pending:
            self.tip('正在粘贴，请稍后复制')
            return False
        copied = bool(self._paste_backend.write(text))
        if copied:
            self.application.reset_clipboard(int(self._paste_backend.sequence()))
        return copied

    def paste(self, text, force=False, cid=None):
        item = self.find_raw_item(cid) if cid else None
        if item and item.get('content_type') == 'image':
            return self.paste_image(item, force)
        return self._queue_paste(text=text or '', force=force, cid=cid)

    def paste_image(self, item, force=False):
        name = item.get('image_path')
        if not name:
            self.tip('图片文件已丢失')
            return False
        return self._queue_paste(image_name=name, force=force, cid=item.get('id'))

    def _queue_paste(self, *, text='', image_name=None, force=False, cid=None, plain=False):
        self.application.dispatcher.assert_owner()
        guard = getattr(self, 'ensure_current_results', None)
        if guard and not guard():
            return False
        self._ensure_paste()
        if self._paste_cancelled.is_set():
            return False
        self._paste_token += 1
        should_paste = bool((self.st.get('autopaste') or force) and not self.hidden)
        target = int(self.prev_hwnd or 0)
        request = PasteRequest(self._paste_token, text, image_name, cid, target,
                               should_paste, should_paste and self._panel_overlaps(target),
                               plain, bool(self.st.get('trim_paste', True)))
        future = self._paste_tasks.submit(
            self._paste_backend.perform, request,
            before_focus=lambda: self._request_paste_focus(request.token),
            cancelled=self._paste_cancelled,
            on_result=lambda result: self._paste_finished(request, result),
            on_error=lambda error: self._paste_finished(
                request, PasteResult(False, error='粘贴未完成（%s）' % type(error).__name__)))
        if future is None:
            self.tip('粘贴操作较多，请稍后重试')
            return False
        return True

    def _queue_trigger(self, request, cancelled=None, stopped=None):
        self.application.dispatcher.assert_owner()
        self._ensure_paste()
        cancellation = _AnyCancelled(self._paste_cancelled, cancelled, stopped)
        if not self._paste_backend.trigger_context_valid(request, cancellation):
            return False
        future = self._paste_tasks.submit(
            self._paste_backend.perform_trigger, request, cancelled=cancellation,
            on_result=self._trigger_paste_finished,
            on_error=lambda error: self.tip('触发词替换未完成（%s）' % type(error).__name__))
        if future is None:
            self.tip('粘贴操作较多，触发词未替换')
            return False
        return True

    def _trigger_paste_finished(self, result):
        self.application.dispatcher.assert_owner()
        if result.copied and result.sequence is not None:
            self.application.reset_clipboard(result.sequence)
        if result.error:
            self.tip(result.error)

    def _request_paste_focus(self, token):
        ready = Event()
        allowed = [False]
        if not self.application.dispatcher.post(self._begin_paste_focus, token, ready, allowed):
            return False
        arrived = ready.wait(0.8)
        if not arrived:
            # A stalled UI may drain this callback later. Mark the expired gate
            # so it cannot lower the window after the paste has already failed.
            ready.set()
        return arrived and allowed[0] and not self._paste_cancelled.is_set()

    def _begin_paste_focus(self, token, ready, allowed):
        self.application.dispatcher.assert_owner()
        try:
            if ready.is_set() or self._paste_cancelled.is_set():
                return
            if not self.hidden:
                self.root.attributes('-topmost', False)
                self._topmost_applied = False
                self._topmost_yield = True
                self._paste_yields.add(token)
            allowed[0] = True
        finally:
            ready.set()

    def _paste_finished(self, request, result):
        self.application.dispatcher.assert_owner()
        yielded = request.token in self._paste_yields
        self._paste_yields.discard(request.token)
        if yielded and not self._paste_yields:
            self._restore_topmost()
        if result.copied and result.sequence is not None:
            # Use the sequence captured by this write, never the current value:
            # the user may have copied something else while delivery was queued.
            self.application.reset_clipboard(result.sequence)
            item = self.find_raw_item(request.cid) if request.cid else None
            if item:
                item['last_used_at'] = now_ms()
                item['use_count'] = int(item.get('use_count') or 0) + 1
                self.save(True)
        if result.pasted:
            if request.cid:
                self.vlist.flash(request.cid)
            if self.st.get('sound_paste'):
                from clawboard import sound
                sound.play_paste()
        if result.error:
            self.tip(result.error)

    def _panel_overlaps(self, hwnd):
        from clawboard.win32 import window_rect, rects_overlap
        try:
            target = window_rect(hwnd)
            if not target:
                return True
            x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
            w, h = self.root.winfo_width(), self.root.winfo_height()
            return rects_overlap((x, y, x + w, y + h), target)
        except Exception:
            return True

    def _restore_topmost(self):
        self._topmost_yield = False
        if not self.hidden:
            self.sync_topmost()

    def _paste_message_worker(self, hwnd):
        self._ensure_paste()
        return bool(self._paste_backend.message(hwnd))

    def _paste_worker(self, hwnd, restore_topmost=False):
        """Compatibility worker API; completion still returns through the queue."""
        self._ensure_paste()
        ok = self._paste_backend.focus_paste(hwnd, self._paste_cancelled)
        self.application.dispatcher.post(self._legacy_paste_finished, ok, restore_topmost)
        return ok

    def _legacy_paste_finished(self, ok, restore):
        self._paste_fail = not ok
        if restore:
            self._restore_topmost()

    def paste_plain_sel(self):
        items = self.vlist.items
        selected = self.sel_clip if self.tab == 'clip' else self.sel_phrase
        selected = selected or (items[0]['id'] if items else None)
        for item in items:
            if item['id'] == selected:
                return self.paste_plain(item)
        self.tip('先选中一条再按 Ctrl+Shift+Enter')

    def paste_plain(self, it):
        return self._queue_paste(text=it.get('text') or '', force=True,
                                 cid=it.get('id'), plain=True)

    def close_paste(self):
        runner = getattr(self, '_paste_tasks', None)
        if runner is None:
            return
        self._paste_cancelled.set()
        runner.shutdown(wait=False)
        yielded = bool(self._paste_yields)
        self._paste_yields.clear()
        if yielded:
            self._restore_topmost()
