"""Bounded, cached background verification shared by all camera engines."""

from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
import logging
import threading
import time
from typing import Callable

from pydantic import ValidationError

from app.models import Verdict

log = logging.getLogger('policylens.engine.verification')
VerificationKey = tuple[str, str, str, int]  # camera, session, check, original track ID


def unavailable(reason='verification unavailable') -> Verdict:
    return Verdict(answer=None, confidence=0, reason=reason)


class StubVerifier:
    """Explicit offline test substitute; never infer a real property from pixels."""

    def __init__(self, answers: dict[str, Verdict] | None = None):
        self.answers = {key: value.model_copy(deep=True) for key, value in (answers or {}).items()}
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def __call__(self, crop, check: str) -> Verdict:
        with self._lock:
            self.calls.append(check)
        verdict = self.answers.get(check, unavailable('stub verifier; no visual analysis'))
        return verdict.model_copy(deep=True)


@dataclass
class Ticket:
    key: VerificationKey
    deadline: float
    future: Future | None = None
    result: Verdict | None = None
    cancelled: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)


class VerificationScheduler:
    """Inject Person 2's verify_crop callable; no Gemini dependency lives here.

    submit/poll never wait on the provider. A timeout returns manual review while
    the actual worker retains its capacity slot until the provider exits. Python
    cannot terminate a running third-party call; the provider must enforce its
    own network timeout. Sharing one scheduler enforces one global start rate.
    """

    def __init__(self, verifier: Callable | None = None, *, max_workers=2,
                 max_pending=8, calls_per_second=2, timeout_seconds=4, cache_size=256):
        if min(max_workers, max_pending, cache_size) < 1:
            raise ValueError('Worker, pending and cache sizes must be positive')
        if not 0 < calls_per_second <= 2:
            raise ValueError('Verification rate must be positive and at most 2 calls/s')
        if timeout_seconds <= 0:
            raise ValueError('Verification timeout must be positive')
        self.verifier = verifier if verifier is not None else StubVerifier()
        self.timeout = timeout_seconds
        self.cache_size = cache_size
        self._executor = ThreadPoolExecutor(max_workers=max_workers,
                                            thread_name_prefix='policy-verifier')
        self._slots = threading.BoundedSemaphore(max_pending)
        self._cache: OrderedDict[VerificationKey, Ticket] = OrderedDict()
        self._lock = threading.Lock()
        self._gate = threading.Condition()
        self._interval = 1 / calls_per_second
        self._next_start = 0.0
        self._closed = False

    def submit(self, key: VerificationKey, crop, check: str) -> Ticket | None:
        """Return a cached/in-flight ticket, or None if the bounded queue is full."""
        with self._lock:
            if self._closed:
                raise RuntimeError('Verification scheduler is closed')
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            if not self._slots.acquire(blocking=False):
                return None
            ticket = Ticket(key, time.monotonic() + self.timeout)
            try:
                ticket.future = self._executor.submit(self._execute, ticket, crop, check)
            except Exception:
                self._slots.release()
                raise
            ticket.future.add_done_callback(lambda _: self._slots.release())
            self._cache[key] = ticket
            # Never evict active jobs; they already fit within max_pending.
            for old_key in list(self._cache):
                if len(self._cache) <= self.cache_size:
                    break
                old = self._cache[old_key]
                if old_key != key and old.future.done():
                    del self._cache[old_key]
            return ticket

    def _acquire_start(self, ticket: Ticket) -> bool:
        with self._gate:
            while not ticket.cancelled.is_set() and not self._closed:
                now = time.monotonic()
                if now >= ticket.deadline:
                    return False
                delay = self._next_start - now
                if delay <= 0:
                    self._next_start = now + self._interval
                    return True
                self._gate.wait(min(delay, ticket.deadline - now))
        return False

    def _execute(self, ticket: Ticket, crop, check: str):
        started = time.monotonic()
        verdict = unavailable('verification timed out')
        for attempt in range(2):
            if not self._acquire_start(ticket):
                break
            try:
                raw = self.verifier(crop, check)
                data = raw.model_dump() if hasattr(raw, 'model_dump') else raw
                verdict = Verdict.model_validate(data)
                break
            except ValidationError:
                verdict = unavailable('invalid verifier response')
                if attempt == 0:
                    continue
            except Exception:
                # Provider exception messages can contain sensitive endpoints.
                log.warning('Verification provider failed camera=%s check=%s', ticket.key[0], check)
                verdict = unavailable()
            break
        finished = time.monotonic()
        log.info('Verification camera=%s check=%s latency_ms=%.1f',
                 ticket.key[0], check, (finished - started) * 1000)
        return finished, verdict

    def poll(self, ticket: Ticket) -> Verdict | None:
        """None means pending; Verdict(answer=None) means a completed unclear check."""
        with ticket.lock:
            if ticket.result is not None:
                return ticket.result.model_copy(deep=True)
            if ticket.future.done() and not ticket.future.cancelled():
                finished, verdict = ticket.future.result()
                ticket.result = (verdict if finished <= ticket.deadline
                                 else unavailable('verification timed out'))
            elif ticket.cancelled.is_set() or time.monotonic() >= ticket.deadline:
                ticket.cancelled.set()
                ticket.future.cancel()
                ticket.result = unavailable('verification timed out')
            else:
                return None
            return ticket.result.model_copy(deep=True)

    def cancel_session(self, camera_id: str, session_id: str) -> None:
        with self._lock:
            for key in list(self._cache):
                if key[:2] == (camera_id, session_id):
                    ticket = self._cache.pop(key)
                    ticket.cancelled.set()
                    ticket.future.cancel()
        with self._gate:
            self._gate.notify_all()

    def close(self, wait=True) -> None:
        with self._lock:
            self._closed = True
        with self._gate:
            self._gate.notify_all()
        self._executor.shutdown(wait=wait, cancel_futures=True)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


_default: VerificationScheduler | None = None
_default_lock = threading.Lock()


def default_scheduler() -> VerificationScheduler:
    """One lazy process-wide scheduler for camera engines using the safe stub."""
    global _default
    with _default_lock:
        if _default is None:
            _default = VerificationScheduler()
        return _default
