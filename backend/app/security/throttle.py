"""A small in-memory sliding-window limiter.

State lives in this process, so with several API instances each keeps its own counts. That is enough to blunt
password guessing and runaway model spend for a demo; a real deployment would back this with a shared store.
"""

import threading
import time
from collections import deque


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> deque[float] | None:
        """The hits still inside the window, or None (and no stored entry) when there are none."""
        hits = self._hits.get(key)
        if hits is None:
            return None
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if not hits:
            del self._hits[key]
            return None
        return hits

    def blocked(self, key: str, now: float | None = None) -> bool:
        """True when `key` has already used its allowance in the window. Does not count a new hit."""
        with self._lock:
            hits = self._recent(key, time.monotonic() if now is None else now)
            return hits is not None and len(hits) >= self.limit

    def hit(self, key: str, now: float | None = None) -> bool:
        """Records one use. Returns False when this use exceeds the allowance."""
        with self._lock:
            t = time.monotonic() if now is None else now
            hits = self._recent(key, t) or self._hits.setdefault(key, deque())
            hits.append(t)
            return len(hits) <= self.limit

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)
