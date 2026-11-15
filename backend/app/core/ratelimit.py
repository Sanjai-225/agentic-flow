"""Sliding-window rate limiter for public ingress (form submissions, webhooks).

In-process and per worker: with several workers each enforces its own window. This is documented as a
known limitation; a shared store (e.g. Redis) is a Milestone 4 production-hardening item.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Dict, Tuple


class RateLimiter:
    def __init__(self) -> None:
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_seconds: float = 60.0) -> Tuple[bool, float]:
        """Record a hit for ``key``; return (allowed, retry_after_seconds)."""
        if limit <= 0:
            return True, 0.0
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] > window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                return False, max(0.0, window_seconds - (now - hits[0]))
            hits.append(now)
            if len(self._hits) > 50_000:  # bound memory: drop idle keys
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] > window_seconds][:10_000]:
                    self._hits.pop(k, None)
            return True, 0.0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def client_ip(request: object) -> str:
    client = getattr(request, "client", None)
    return getattr(client, "host", None) or "unknown"
