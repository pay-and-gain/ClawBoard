"""Small application services, independent of Tk, ctypes and global settings."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
from threading import Condition, Lock


@dataclass(frozen=True)
class ClipboardSnapshot:
    seq: int
    kind: str
    text: str = ''
    payload: bytes = b''
    source_app: str = 'unknown'
    source_title: str | None = None
    source_hwnd: int | None = None
    paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class CaptureResult:
    status: str
    snapshot: ClipboardSnapshot | None = None
    detail: str | None = None


class ClipboardService:
    """Acknowledge a clipboard sequence only after a deliberate terminal result.

    A busy clipboard returns ``retry``. Captured bytes stay in flight until the
    application accepts/discards their processed result with complete(). This
    prevents a temporary OpenClipboard failure from silently losing a copy.
    """
    TERMINAL = frozenset(('empty', 'private', 'unsupported'))

    def __init__(self, sequence_reader, snapshot_reader, processor=None, *, initial_sequence=0):
        self.sequence_reader = sequence_reader
        self.snapshot_reader = snapshot_reader
        self.processor = processor or (lambda snapshot: snapshot)
        self._last_sequence = initial_sequence
        self._inflight = None
        self._lock = Lock()
        self._polling = False
        self._generation = 0

    @property
    def last_sequence(self):
        with self._lock:
            return self._last_sequence

    @property
    def inflight_sequence(self):
        with self._lock:
            return self._inflight

    def poll(self, *, force=False):
        with self._lock:
            if self._inflight is not None or self._polling:
                return CaptureResult('pending')
            self._polling = True
            generation = self._generation
            last_sequence = self._last_sequence
        try:
            seq = self.sequence_reader()
            if seq == last_sequence and not force:
                return CaptureResult('unchanged')
            result = self.snapshot_reader(seq)
            if isinstance(result, ClipboardSnapshot):
                result = CaptureResult('captured', result)
            if not isinstance(result, CaptureResult):
                return CaptureResult('retry', detail='invalid snapshot result')
            with self._lock:
                if generation != self._generation:
                    return CaptureResult('retry', detail='capture was invalidated')
                if result.status in self.TERMINAL:
                    self._last_sequence = seq
                elif result.status == 'captured':
                    if result.snapshot is None or result.snapshot.seq != seq:
                        return CaptureResult('retry', detail='clipboard changed during capture')
                    self._inflight = seq
            return result
        except Exception as error:
            # Capture errors may include window titles; expose only their type.
            return CaptureResult('retry', detail=type(error).__name__)
        finally:
            with self._lock:
                self._polling = False

    def prepare(self, snapshot):
        """Run expensive decoding/classification in a worker, never touch UI."""
        return self.processor(snapshot)

    def complete(self, seq, *, success=True):
        with self._lock:
            if seq != self._inflight:
                return False
            if success:
                self._last_sequence = seq
            self._inflight = None
            return True

    def reset(self, seq):
        with self._lock:
            self._last_sequence = seq
            self._inflight = None
            self._generation += 1


class SaveService:
    """One writer and one latest pending snapshot; the last save is never lost.

    request() copies only Python data on the caller thread. JSON serialization
    and disk I/O happen in the dedicated writer. Rapid requests coalesce while
    preserving write order. flush() waits for the latest accepted revision.
    A writer returning False explicitly skipped a write and does not advance
    saved_revision. Failed close/flush leaves the service open for a retry.
    """
    def __init__(self, dispatcher, writer, *, on_saved=None, on_error=None):
        self.dispatcher = dispatcher
        self.writer = writer
        self.on_saved = on_saved
        self.on_error = on_error
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='clawboard-save')
        self._condition = Condition(Lock())
        self._latest = None
        self._active = False
        self._closed = False
        self._revision = 0
        self._saved_revision = 0
        self._last_error = None
        self._future = None

    @property
    def pending(self):
        with self._condition:
            return self._active or self._latest is not None

    @property
    def saved_revision(self):
        with self._condition:
            return self._saved_revision

    def request(self, data):
        snapshot = deepcopy(data)
        with self._condition:
            if self._closed:
                raise RuntimeError('save service is closed')
            self._revision += 1
            revision = self._revision
            self._latest = (revision, snapshot)
            if not self._active:
                self._active = True
                self._future = self._executor.submit(self._write_pending)
            return revision

    def _write_pending(self):
        while True:
            with self._condition:
                request = self._latest
                self._latest = None
                if request is None:
                    self._active = False
                    self._condition.notify_all()
                    return
            revision, snapshot = request
            try:
                result = self.writer(snapshot)
            except Exception as error:
                with self._condition:
                    self._last_error = (revision, error)
                self.dispatcher.post(self._notify, False, revision, error)
            else:
                with self._condition:
                    if result is not False:
                        self._saved_revision = revision
                    self._last_error = None
                self.dispatcher.post(self._notify, True, revision, result)

    def _notify(self, succeeded, revision, result):
        self.dispatcher.assert_owner()
        with self._condition:
            if self._closed:
                return
        callback = self.on_saved if succeeded else self.on_error
        if callback:
            callback(revision, result)
        elif not succeeded:
            raise result

    def flush(self, timeout=None):
        with self._condition:
            finished = self._condition.wait_for(lambda: not self._active, timeout)
            if not finished:
                raise TimeoutError('pending saves did not finish')
            if self._last_error:
                raise self._last_error[1]
            return self._saved_revision

    def close(self, *, flush=True, timeout=None):
        with self._condition:
            if self._closed:
                return
            if flush:
                finished = self._condition.wait_for(lambda: not self._active, timeout)
                if not finished:
                    raise TimeoutError('pending saves did not finish')
                if self._last_error:
                    raise self._last_error[1]
            self._closed = True
        self._executor.shutdown(wait=flush, cancel_futures=False)
