"""Application orchestration between immutable worker results and UI adapters.

The controller owns services and mutable history. It knows neither Tk nor Win32;
the shell injects clipboard readers and drains owner-thread events. Workers may
decode data and perform file I/O, but only the owner thread commits a record.
"""
from copy import deepcopy
from dataclasses import dataclass
import struct
from threading import Event, Lock

from clawboard.classify import crop_items, length_filtered
from clawboard.config import MAX_TEXT
from clawboard.dispatch import EventDispatcher
from clawboard.history import HistoryService, prepare_text
from clawboard.image import dib_to_png
from clawboard.search import SearchService
from clawboard.services import ClipboardService, SaveService
from clawboard.storage import RecoveryRequiredError
from clawboard.tasks import WorkerTasks
from clawboard.timefmt import match_ignore


@dataclass(frozen=True)
class CaptureOutcome:
    status: str
    item: dict | None = None
    quiet: bool = False
    message: str = ''
    removed: tuple = ()


@dataclass(frozen=True)
class _PreparedCapture:
    status: str
    snapshot: object = None
    text: object = None
    image_name: str | None = None
    width: int = 0
    height: int = 0
    message: str = ''


class ApplicationController:
    def __init__(self, data, store, image_store, *, no_save=lambda: False,
                 on_capture=None, on_error=None):
        self.data = data
        self.store = store
        self.image_store = image_store
        self.no_save = no_save
        self.on_capture = on_capture
        self.on_error = on_error
        self.history = HistoryService(data)
        self.search = SearchService()
        self.dispatcher = EventDispatcher(on_error=self._report_error)
        self.tasks = WorkerTasks(self.dispatcher)
        self.saves = SaveService(self.dispatcher, self._write_snapshot,
                                 on_saved=self._saved,
                                 on_error=lambda revision, error: self._report_error(error))
        self.clipboard = None
        self._capture_busy = False
        self._capture_generation = 0
        self._closing = Event()
        self._image_lock = Lock()
        self._uncommitted_images = set()
        self._cleanup_images = set()
        self._cleanup_inflight = set()
        self._unassigned_gc = set()
        self._pending_gc = {}
        self._confirmed_gc = set()
        self._readonly_notified = False
        self.data_revision = 0

    @property
    def closed(self):
        return self._closing.is_set()

    @property
    def capture_pending(self):
        return self._capture_busy

    @property
    def pending(self):
        return bool(self._capture_busy or self.tasks.pending or self.saves.pending
                    or self.dispatcher.pending)

    def mark_changed(self):
        self.dispatcher.assert_owner()
        self.data_revision += 1
        return self.data_revision

    def configure_clipboard(self, sequence_reader, snapshot_reader, initial_sequence=0):
        self.dispatcher.assert_owner()
        self._capture_generation += 1
        self.clipboard = ClipboardService(sequence_reader, snapshot_reader,
                                          initial_sequence=initial_sequence)
        return self.clipboard

    def reset_clipboard(self, seq):
        self.dispatcher.assert_owner()
        self._capture_generation += 1
        if self.clipboard is not None:
            self.clipboard.reset(seq)

    def invalidate_clipboard(self):
        self.dispatcher.assert_owner()
        self._capture_generation += 1
        if self.clipboard is not None:
            self.clipboard.reset(self.clipboard.last_sequence)

    def capture(self, quiet=False, dedup=False, force=False):
        """Queue at most one capture; rejected work is retried by the adapter."""
        self.dispatcher.assert_owner()
        settings = dict(self.data.get('settings') or {})
        if (self.closed or self._capture_busy or self.clipboard is None
                or not settings.get('listen', True)):
            return False
        top = deepcopy(self.data['clip'][0]) if self.data.get('clip') else None
        generation = self._capture_generation
        clipboard = self.clipboard
        future = self.tasks.submit(
            self._prepare_capture, clipboard, settings, top, dedup, force,
            on_result=lambda result: self._finish_capture(result, clipboard, generation, quiet),
            on_error=lambda error: self._capture_failed(error, clipboard, generation))
        if future is None:
            return False
        self._capture_busy = True
        return True

    def _prepare_capture(self, clipboard, settings, top, dedup, force):
        capture = clipboard.poll(force=force)
        if capture.status != 'captured':
            return _PreparedCapture(capture.status, message=capture.detail or '')
        snapshot = capture.snapshot
        if self.closed:
            return _PreparedCapture('stale', snapshot)
        ignored = match_ignore(snapshot.source_app, snapshot.source_title,
                               settings.get('ignore_apps'), settings.get('ignore_titles'))
        if ignored:
            return _PreparedCapture('skip', snapshot, message='命中忽略规则，未记录')
        if snapshot.kind == 'image':
            try:
                png, width, height = dib_to_png(snapshot.payload)
            except (ValueError, struct.error, OverflowError):
                return _PreparedCapture('unsupported', snapshot,
                                        message='图片格式暂不支持，未记录')
            if (dedup and top and top.get('content_type') == 'image'
                    and self.image_store.same_content(top.get('image_path'), png)):
                return _PreparedCapture('dup', snapshot)
            name = None
            if not self.no_save() and not self.closed and not self.store.recovery_required:
                name = self.image_store.write(png)
                # Register before delivery so close/reset can reclaim captures
                # that were written but never accepted into the history.
                with self._image_lock:
                    discard = self.closed
                    if not discard:
                        self._uncommitted_images.add(name)
                if discard:
                    self.image_store.remove(name)
                    return _PreparedCapture('stale', snapshot)
            return _PreparedCapture('image', snapshot, image_name=name, width=width, height=height)
        if snapshot.kind not in ('text', 'files'):
            return _PreparedCapture('unsupported', snapshot)
        text = snapshot.text
        if not (text and text.strip()):
            return _PreparedCapture('empty', snapshot)
        if len(text) > MAX_TEXT:
            text = text[:MAX_TEXT] + '\n…（内容超长已截断）'
        if (dedup and top and top.get('content_type') != 'image'
                and top.get('text') == text):
            return _PreparedCapture('dup', snapshot)
        filtered = length_filtered(text, int(settings.get('min_len') or 0),
                                   int(settings.get('max_len') or 0))
        if filtered:
            return _PreparedCapture('skip', snapshot, message=filtered)
        prepared = prepare_text(text)
        if prepared.hits and settings.get('skip_sensitive'):
            return _PreparedCapture('sensitive', snapshot,
                                    message='检测到敏感内容，按设置不入库')
        return _PreparedCapture('text', snapshot, prepared)

    def _finish_capture(self, result, clipboard, generation, quiet):
        self.dispatcher.assert_owner()
        self._capture_busy = False
        snapshot = result.snapshot
        valid = (not self.closed and clipboard is self.clipboard
                 and generation == self._capture_generation
                 and self.data.get('settings', {}).get('listen', True))
        if snapshot is not None:
            valid = valid and clipboard.inflight_sequence == snapshot.seq
        if not valid or result.status == 'stale':
            self._discard_image(result.image_name)
            if snapshot is not None:
                clipboard.complete(snapshot.seq, success=False)
            return
        if result.status in ('unchanged', 'pending', 'retry'):
            return
        item, removed = None, ()
        settings = self.data.get('settings') or {}
        limit = int(settings.get('max_items') or 500)
        if result.status == 'text':
            change = self.history.ingest(
                result.text, source_app=snapshot.source_app,
                source_title=snapshot.source_title if settings.get('record_title') else None,
                limit=limit)
            item, removed = change.item, change.removed
        elif result.status == 'image':
            stamp = self.history.clock()
            item = {'id': self.history.identity(), 'text': '[图片]',
                    'created_at': stamp, 'updated_at': stamp,
                    'seq': self.history.next_sequence(), 'content_type': 'image',
                    'image_w': result.width, 'image_h': result.height,
                    'source_app': snapshot.source_app, 'copy_count': 1, 'fav': 0,
                    'is_estimated': 0}
            if result.image_name:
                item['image_path'] = result.image_name
            if settings.get('record_title') and snapshot.source_title:
                item['source_title'] = snapshot.source_title
            items = self.data['clip']
            items.insert(0, item)
            retained = crop_items(items, limit)
            kept_ids = {entry['id'] for entry in retained}
            removed = tuple(entry for entry in items if entry['id'] not in kept_ids)
            self.data['clip'] = retained
            with self._image_lock:
                self._uncommitted_images.discard(result.image_name)
        if snapshot is not None:
            clipboard.complete(snapshot.seq)
        if item is not None:
            self.queue_image_cleanup(entry.get('image_path') for entry in removed)
            self.request_save()
        if self.on_capture:
            self.on_capture(CaptureOutcome(result.status, item, quiet, result.message, removed))

    def _capture_failed(self, error, clipboard, generation):
        self._capture_busy = False
        seq = clipboard.inflight_sequence
        if seq is not None:
            clipboard.complete(seq, success=False)
        if not self.closed and generation == self._capture_generation:
            # Exception strings from third-party applications can contain a
            # copied value or window title; diagnostic metadata is sufficient.
            self._report_error(RuntimeError('剪贴板处理失败（%s），稍后重试' % type(error).__name__))

    def _discard_image(self, name):
        if not name:
            return
        with self._image_lock:
            self._uncommitted_images.discard(name)
        self._cleanup_images.add(name)
        self._pump_cleanup()

    def _remove_images(self, names, protected=False):
        removed = []
        for name in names:
            if protected and (self.no_save() or self.store.recovery_required):
                continue
            self.image_store.remove(name)
            removed.append(name)
        return tuple(removed)

    def queue_image_cleanup(self, names):
        """Bind deleted history images to the next requested JSON snapshot.

        UI adapters may call this just before removing records. Files stay in
        place until a snapshot without those references is durably saved.
        """
        self.dispatcher.assert_owner()
        if self.closed or self.no_save() or self.store.recovery_required:
            return False
        self._unassigned_gc.update(name for name in names if name)
        return True

    def _saved(self, revision, result):
        if result is not False:
            self._confirm_saved(revision)

    def _confirm_saved(self, revision, *, schedule=True):
        if self.no_save() or self.store.recovery_required:
            return
        referenced = {item.get('image_path') for item in self.data.get('clip', [])}
        for group in self.data.get('groups', []):
            referenced.update(item.get('image_path') for item in group.get('items', []))
        for saved in tuple(self._pending_gc):
            if saved <= revision:
                self._confirmed_gc.update(self._pending_gc.pop(saved) - referenced)
        if schedule:
            self._pump_cleanup()

    def _cleanup_finished(self, names, protected, removed):
        self._cleanup_inflight.difference_update(names)
        queue = self._confirmed_gc if protected else self._cleanup_images
        queue.difference_update(removed)

    def _cleanup_failed(self, names, error):
        self._cleanup_inflight.difference_update(names)
        self._report_error(error)

    def _pump_cleanup(self):
        if self.closed:
            return
        for queue, protected in ((self._cleanup_images, False), (self._confirmed_gc, True)):
            if protected and (self.no_save() or self.store.recovery_required):
                continue
            names = tuple(queue - self._cleanup_inflight)
            if not names:
                continue
            future = self.tasks.submit(self._remove_images, names, protected,
                on_result=lambda removed, names=names, guarded=protected:
                    self._cleanup_finished(names, guarded, removed),
                on_error=lambda error, names=names: self._cleanup_failed(names, error))
            if future is not None:
                self._cleanup_inflight.update(names)

    def _write_snapshot(self, data):
        if self.no_save():
            return False
        return self.store.save(data)

    def request_save(self):
        self.dispatcher.assert_owner()
        if self.closed:
            return None
        self.mark_changed()
        if self.no_save():
            return None
        if self.store.recovery_required:
            if not self._readonly_notified:
                self._readonly_notified = True
                self._report_error(RecoveryRequiredError('数据处于只读保护，自动保存已停止；请先恢复备份。'))
            return None
        revision = self.saves.request(self.data)
        if self._unassigned_gc:
            self._pending_gc.setdefault(revision, set()).update(self._unassigned_gc)
            self._unassigned_gc.clear()
        return revision

    def flush(self, timeout=5):
        return self.saves.flush(timeout)

    def drain(self, limit=64):
        count = self.dispatcher.drain(limit)
        self._pump_cleanup()
        return count

    def _report_error(self, error):
        if not self.closed and self.on_error:
            self.on_error(error)

    def close(self):
        self.dispatcher.assert_owner()
        if self.closed:
            return
        # A failed final save must leave the whole controller usable. Retrying
        # close requests a fresh snapshot instead of rethrowing a stale failure.
        if not self.no_save() and not self.store.recovery_required:
            self.request_save()
        saved_revision = self.saves.flush(timeout=5)
        self._confirm_saved(saved_revision, schedule=False)
        self.saves.close(flush=True, timeout=5)
        self._closing.set()
        self._capture_generation += 1
        self._capture_busy = False
        self.tasks.shutdown(wait=False)
        with self._image_lock:
            orphaned = tuple(self._uncommitted_images | self._cleanup_images)
            self._uncommitted_images.clear()
            self._cleanup_images.clear()
        # At most the single in-flight capture can be orphaned. A worker that
        # finishes writing later observes _closing and removes its own file.
        self._remove_images(orphaned)
        self._remove_images(tuple(self._confirmed_gc), protected=True)
        self._confirmed_gc.clear()
        self.search.clear()
        self.dispatcher.close()
