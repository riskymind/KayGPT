"""Sliding-window rate limiter (in-process).

Limits are per worker process. That is adequate for a single Render instance; with several
instances, put a shared limiter (Redis) or the platform's WAF in front. Documented in deployment.md.
"""

from __future__ import annotations

import time
from collections import deque


class RateLimiter:
    def __init__(self, max_keys: int = 50_000) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._max_keys = max_keys

    def hit(self, key: str, limit: int, window_seconds: float = 60.0) -> int | None:
        """Record a hit. Returns None if allowed, else seconds until the next slot frees up."""
        if limit <= 0:
            return None
        now = time.monotonic()
        bucket = self._hits.get(key)
        if bucket is None:
            if len(self._hits) >= self._max_keys:
                self._evict(now, window_seconds)
            bucket = self._hits[key] = deque()
        while bucket and now - bucket[0] >= window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            return max(1, int(window_seconds - (now - bucket[0])) + 1)
        bucket.append(now)
        return None

    def _evict(self, now: float, window_seconds: float) -> None:
        stale = [k for k, b in self._hits.items() if not b or now - b[-1] >= window_seconds]
        for key in stale:
            del self._hits[key]
        if len(self._hits) >= self._max_keys:
            self._hits.clear()
