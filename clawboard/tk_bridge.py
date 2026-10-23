"""Tk adapter for application events; background services never call Tk."""
import os

from clawboard import runtime, sound
from clawboard.application import ApplicationController
from clawboard.clipboard import clip_seq
from clawboard.config import BASE_DIR
from clawboard.media import ImageStore
from clawboard.win32_snapshot import read_snapshot


class TkApplicationBridge:
    def __init__(self, app):
        self.app = app
        self.root = app.root
        self._closed = False
        self._pump_id = None
        self._capture_event = False
        self._deferred_capture = None
        self._last_error = None
        self.application = ApplicationController(
            app.data, app._store, ImageStore(os.path.join(BASE_DIR, 'images')),
            no_save=lambda: runtime.NO_SAVE,
            on_capture=self._captured, on_error=self._error)
        own = self.root.winfo_id()
        self._capture_policy = (True, False)

        def snapshot(sequence):
            # Worker receives a policy copy from configure/capture, never Tk objects.
            private, include_title = self._capture_policy
            if sequence == runtime.LAST_WRITE_SEQ:
                from clawboard.services import CaptureResult
                return CaptureResult('empty')
            return read_snapshot(sequence, private=private, own_hwnd=own,
                                 include_title=include_title)
        self.application.configure_clipboard(clip_seq, snapshot, initial_sequence=runtime.LAST_SEQ)

    def start(self):
        self._pump()

    def _pump(self):
        if self._closed:
            return
        self.application.drain()
        if self._deferred_capture and not self.application.capture_pending:
            request = self._deferred_capture
            self._deferred_capture = None
            self.request_capture(**request)
        if self._capture_event:
            accepted = self.request_capture()
            self._capture_event = not accepted and bool(self.app.st.get('listen'))
        paste_tasks = getattr(self.app, '_paste_tasks', None)
        active = bool(self.application.tasks.pending or self.application.dispatcher.pending or
                      (paste_tasks and paste_tasks.pending))
        self._pump_id = self.root.after(20 if active else 80, self._pump)

    def clipboard_changed(self):
        # Windows message thread only posts a plain callback into the queue.
        self.application.dispatcher.post(self._mark_capture)

    def _mark_capture(self):
        self._capture_event = True

    def request_capture(self, *, quiet=False, dedup=False, force=False):
        if self._closed:
            return False
        if not self.app.st.get('listen'):
            self._deferred_capture = None
            self.application.reset_clipboard(clip_seq())
            return False
        if self.application.capture_pending:
            if force:
                self._deferred_capture = dict(quiet=quiet, dedup=dedup, force=force)
            return False
        self._capture_policy = (bool(self.app.st.get('smart_private', True)),
                                bool(self.app.st.get('record_title') or self.app.st.get('ignore_titles')))
        accepted = self.application.capture(quiet=quiet, dedup=dedup, force=force)
        if force and not accepted:
            self._deferred_capture = dict(quiet=quiet, dedup=dedup, force=force)
        return accepted

    def own_write(self, sequence=None):
        runtime.LAST_SEQ = runtime.LAST_WRITE_SEQ if sequence is None else sequence
        if runtime.LAST_SEQ is None:
            return
        self.application.reset_clipboard(runtime.LAST_SEQ)

    def _captured(self, outcome):
        app = self.app
        runtime.LAST_SEQ = self.application.clipboard.last_sequence
        app._seq = self.application.history.sequence
        if outcome.status in ('text', 'image'):
            if app.tab == 'clip' and not app.hidden:
                app.render()
            if outcome.quiet:
                app.tip(app._catchup_tip())
            elif outcome.status == 'text':
                if app.st.get('show_toast', True):
                    app.show_copy_toast(outcome.item['text'])
                if app.st.get('sound_copy'):
                    sound.play_copy()
            else:
                app.tip('已记录图片 %s×%s' % (outcome.item['image_w'], outcome.item['image_h']))
                if app.st.get('sound_copy'):
                    sound.play_copy()
        elif outcome.message and not outcome.quiet:
            app.tip(outcome.message)

    def _error(self, error):
        # Surface failures once, without ever putting copied text into logs.
        name = type(error).__name__
        self.app.note('后台操作失败：' + name)
        if name != self._last_error:
            self._last_error = name
            self.app.tip('操作未完成，请检查数据目录或稍后重试（%s）' % name)

    def close(self):
        if self._closed:
            return
        self.application.flush()
        self.application.close()
        self.app.close_paste()
        self._closed = True
        if self._pump_id:
            self.root.after_cancel(self._pump_id)
            self._pump_id = None
