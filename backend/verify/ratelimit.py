"""Global token bucket shared by every camera thread: 2 requests/s, at most 4 in flight."""

import threading
import time


class RateLimiter:
    def __init__(self, rate_per_s: float = 2.0, burst: int = 2, max_in_flight: int = 4):
        self.rate_per_s = rate_per_s
        self.burst = burst
        self.max_in_flight = max_in_flight
        self._tokens = float(burst)
        self._in_flight = 0
        self._updated = time.monotonic()
        self._cond = threading.Condition()

    def acquire(self, timeout: float) -> bool:
        """Take a token and an in-flight slot, waiting at most `timeout` seconds. False if busy."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                self._refill()
                if self._tokens >= 1 and self._in_flight < self.max_in_flight:
                    self._tokens -= 1
                    self._in_flight += 1
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                wait = remaining
                if self._in_flight < self.max_in_flight:
                    wait = min(remaining, (1 - self._tokens) / self.rate_per_s)
                self._cond.wait(wait)

    def release(self) -> None:
        """Free the in-flight slot once the request has actually finished."""
        with self._cond:
            self._in_flight = max(0, self._in_flight - 1)
            self._cond.notify_all()

    def _refill(self) -> None:
        now = time.monotonic()
        self._tokens = min(self.burst, self._tokens + (now - self._updated) * self.rate_per_s)
        self._updated = now


LIMITER = RateLimiter()
