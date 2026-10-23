"""Compatibility methods for the Tk shell, delegating to independent services."""
import os
import time

from clawboard import runtime, sound
from clawboard.config import DATA_FILE, BASE_DIR, CRASH_LOG, rotate_log_if_needed
from clawboard.history import HistoryService, prepare_text
from clawboard.models import normalize_item, normalize_data
from clawboard.storage import JsonStore
from clawboard.classify import length_filtered
from clawboard.timefmt import match_ignore
from clawboard.win32 import capture_source, window_title_of


class DataMixin:
    norm_item = staticmethod(normalize_item)
    validate = staticmethod(normalize_data)

    def load_data(self):
        self._store = JsonStore(DATA_FILE)
        result = self._store.load()
        self._load_notices = result.notices
        for notice in result.notices:
            self.note(notice)
        return result.data

    def save_now(self, d=None):
        if runtime.NO_SAVE:
            return False
        try:
            application = getattr(self, 'application', None)
            if application is not None:
                application.request_save()
                application.flush()
                return not self._store.recovery_required
            return self._store.save(self.data if d is None else d)
        except OSError as error:
            self.note('保存失败：%s' % error)
            return False

    def save(self, later=False):
        # Debounce scheduling belongs to this UI adapter; the writer never sees Tk.
        if hasattr(self, 'application'):
            self.application.mark_changed()
        if runtime.NO_SAVE:
            return

        def request():
            self.save_timer = None
            if not self.collapsed:
                self.data['geom'] = self.root.geometry()
            self.application.request_save()

        if self.save_timer:
            self.root.after_cancel(self.save_timer)
            self.save_timer = None
        if later:
            self.save_timer = self.root.after(300, request)
        else:
            request()

    def note(self, message):
        if runtime.NO_SAVE:
            return
        try:
            rotate_log_if_needed(CRASH_LOG)
            with open(CRASH_LOG, 'a', encoding='utf-8') as stream:
                stream.write('[%s] %s\n' % (time.strftime('%F %T'), message))
        except OSError:
            pass

    def next_seq(self):
        application = getattr(self, 'application', None)
        if application is not None:
            self._seq = application.history.next_sequence()
        else:
            self._seq += 1
        return self._seq

    def ingest(self, txt, hits=None, manual=False, quiet=False):
        """Synchronous compatibility entry for explicit user edits.

        Live clipboard capture prepares text in workers through ApplicationController.
        Existing scripts and dialog callbacks retain their immediate commit contract.
        """
        source, hwnd = capture_source(self.root.winfo_id(), delay_retry=False)
        title = (window_title_of(hwnd) if hwnd and
                 (self.st['record_title'] or self.st.get('ignore_titles')) else None)
        if not manual:
            message = length_filtered(txt, int(self.st.get('min_len') or 0),
                                      int(self.st.get('max_len') or 0))
            ignored = match_ignore(source, title, self.st.get('ignore_apps'), self.st.get('ignore_titles'))
            if message or ignored:
                if not quiet:
                    self.tip(message or '命中忽略规则，未记录')
                return False
        prepared = prepare_text(txt, hits)
        application = getattr(self, 'application', None)
        history = application.history if application else HistoryService(self.data)
        change = history.ingest(prepared, source_app=source,
                                source_title=title if self.st['record_title'] else None,
                                limit=int(self.st['max_items']))
        self._seq = history.sequence
        self._purge_image_files(change.removed)
        self.save(True)
        if self.tab == 'clip':
            self.render()
        if source == 'unknown' and application:
            self._late_source(change.item['id'])
        if not manual and not quiet:
            if self.st.get('show_toast', True):
                self.show_copy_toast(txt)
            if self.st.get('sound_copy'):
                sound.play_copy()
        return True

    def _late_source(self, item_id):
        # Capture the handle on the UI thread. Workers must never call winfo_id.
        own = self.root.winfo_id()
        def read():
            time.sleep(0.05)
            return capture_source(own, delay_retry=False)

        def accept(result):
            source, hwnd = result
            if source == 'unknown':
                return
            for item in self.data['clip']:
                if item['id'] == item_id:
                    item['source_app'] = source
                    if self.st['record_title'] and hwnd:
                        item['source_title'] = window_title_of(hwnd)
                    self.save(True)
                    self.render()
                    break
        self.application.tasks.submit(read, key=('source', item_id), on_result=accept,
                                      on_error=lambda error: self.note('来源补抓失败：' + type(error).__name__))
