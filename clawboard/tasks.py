"""Bounded background work with owner-thread completion delivery."""
from concurrent.futures import CancelledError, ThreadPoolExecutor
from threading import Lock


class WorkerTasks:
    def __init__(self, dispatcher, *, max_workers=2, max_pending=8):
        if not 1 <= max_workers <= 2:
            raise ValueError('max_workers must be 1 or 2')
        if max_pending < 1:
            raise ValueError('max_pending must be positive')
        self.dispatcher = dispatcher
        self.max_pending = max_pending
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='clawboard-work')
        self._lock = Lock()
        self._pending = {}
        self._generations = {}
        self._next_token = 0
        self._closed = False

    @property
    def pending(self):
        with self._lock:
            return len(self._pending)

    @property
    def closed(self):
        with self._lock:
            return self._closed

    def submit(self, fn, *args, key=None, on_result=None, on_error=None, **kwargs):
        """Return a Future, or None when capacity is full/the runner is closed.

        Capacity includes completions waiting for the UI. This bounds callback
        backlog as well as executor work. Callers must retry rejected essential
        work; persistence should use SaveService instead of a latest-wins key.
        """
        with self._lock:
            if self._closed or len(self._pending) >= self.max_pending:
                return None
            self._next_token += 1
            token = self._next_token
            generation = None
            if key is not None:
                generation = token
                self._generations[key] = generation
            future = self._executor.submit(fn, *args, **kwargs)
            self._pending[token] = (future, key, generation, on_result, on_error)
        future.add_done_callback(lambda done: self._completed(token))
        return future

    def invalidate(self, key):
        with self._lock:
            self._next_token += 1
            if any(record[1] == key for record in self._pending.values()):
                self._generations[key] = self._next_token
            else:
                self._generations.pop(key, None)

    def _forget_idle_key(self, key):
        if key is not None and not any(record[1] == key for record in self._pending.values()):
            self._generations.pop(key, None)

    def _completed(self, token):
        with self._lock:
            if self._closed:
                self._pending.pop(token, None)
                return
        if not self.dispatcher.post(self._deliver, token):
            with self._lock:
                self._pending.pop(token, None)

    def _deliver(self, token):
        self.dispatcher.assert_owner()
        with self._lock:
            record = self._pending.pop(token, None)
            if record is None or self._closed:
                return
            future, key, generation, on_result, on_error = record
            if key is not None and self._generations.get(key) != generation:
                self._forget_idle_key(key)
                return
            self._forget_idle_key(key)
        try:
            result = future.result()
        except CancelledError:
            return
        except Exception as error:
            if on_error:
                on_error(error)
            else:
                raise
        else:
            if on_result:
                on_result(result)

    def shutdown(self, *, wait=False, cancel_pending=True):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            futures = [entry[0] for entry in self._pending.values()]
        if cancel_pending:
            for future in futures:
                future.cancel()
        self._executor.shutdown(wait=wait, cancel_futures=cancel_pending)
        with self._lock:
            self._pending.clear()
