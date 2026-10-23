"""Thread-safe delivery to the thread that owns the UI.

Workers only enqueue plain callbacks. The UI adapter decides when to drain the
queue; this module deliberately never imports Tk or calls a UI scheduler.
"""
from collections import deque
from queue import Empty, Queue
from threading import Lock, get_ident


class EventDispatcher:
    def __init__(self, *, owner_thread_id=None, on_error=None):
        self.owner_thread_id = get_ident() if owner_thread_id is None else owner_thread_id
        self._queue = Queue()
        self._lock = Lock()
        self._closed = False
        self.on_error = on_error
        self.errors = deque(maxlen=32)

    @property
    def closed(self):
        with self._lock:
            return self._closed

    @property
    def pending(self):
        return self._queue.qsize()

    def assert_owner(self):
        if get_ident() != self.owner_thread_id:
            raise RuntimeError('UI events must be drained by their owning thread')

    def post(self, callback, *args, **kwargs):
        if not callable(callback):
            raise TypeError('event callback must be callable')
        with self._lock:
            if self._closed:
                return False
            self._queue.put((callback, args, kwargs))
        return True

    def drain(self, limit=64):
        self.assert_owner()
        count = 0
        while count < max(0, limit):
            with self._lock:
                if self._closed:
                    break
                try:
                    callback, args, kwargs = self._queue.get_nowait()
                except Empty:
                    break
            try:
                callback(*args, **kwargs)
            except Exception as error:
                # One failing callback must not stop clipboard/hotkey delivery.
                self.errors.append(error)
                if self.on_error:
                    try:
                        self.on_error(error)
                    except Exception as handler_error:
                        self.errors.append(handler_error)
            count += 1
        return count

    def close(self):
        self.assert_owner()
        with self._lock:
            self._closed = True
            while True:
                try:
                    self._queue.get_nowait()
                except Empty:
                    break
