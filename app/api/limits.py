"""Request limits for the two expensive endpoints (/plan, /research).

Each plan costs 5 searches and 2–4 LLM calls and takes tens of seconds, so an
unprotected endpoint is an easy way to burn quota and money. Two simple,
in-process guards:

1. ``SlidingWindowLimiter``: at most N requests per client per 60 s
   (``RATE_LIMIT_PER_MINUTE``). The client key is the caller's IP. Note: when
   the Streamlit UI is the caller, all users share the UI's IP, so this acts as
   a per-replica cap on UI traffic, which is still a useful cost guard.
2. ``ConcurrencyLimiter``: at most M plans running at once in this replica
   (``MAX_CONCURRENT_PLANS``); extra requests are refused with 429 immediately
   instead of queueing and timing out.

Limits: state is per process (each Kubernetes replica has its own counters) and
resets on restart. Real per-user limits belong at the edge (Cloud Armor rate
rules on the load balancer), documented in docs/25_security.md.
"""

from __future__ import annotations

import asyncio
import math
import threading
import time
from collections import deque
from collections.abc import AsyncIterator

from fastapi import Depends, Request

from app.config import Settings, get_settings
from app.core.exceptions import RateLimitError
from app.observability.metrics import metrics

_MAX_TRACKED_CLIENTS = 10_000


class SlidingWindowLimiter:
    def __init__(self, window_seconds: float = 60.0):
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, now: float | None = None) -> float | None:
        """Record a hit. Return None if allowed, else seconds until the next slot frees."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= limit:
                return self.window - (now - hits[0])
            hits.append(now)
            if len(self._hits) > _MAX_TRACKED_CLIENTS:  # bound memory under many distinct clients
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] >= self.window]:
                    del self._hits[k]
            return None


class ConcurrencyLimiter:
    def __init__(self) -> None:
        self.active = 0
        self._lock = asyncio.Lock()

    async def try_acquire(self, limit: int) -> bool:
        async with self._lock:
            if limit and self.active >= limit:
                return False
            self.active += 1
            return True

    async def release(self) -> None:
        async with self._lock:
            self.active -= 1


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def enforce_limits(request: Request, settings: Settings = Depends(get_settings)) -> AsyncIterator[None]:
    """FastAPI dependency: rate limit, then hold a concurrency slot for the whole request."""
    state = request.app.state
    if settings.rate_limit_per_minute:
        retry_after = state.rate_limiter.check(_client_key(request), settings.rate_limit_per_minute)
        if retry_after is not None:
            metrics.increment("rate_limited_total", {"reason": "rate"})
            raise RateLimitError(
                f"Too many requests: limit is {settings.rate_limit_per_minute} per minute.",
                details={"reason": "rate", "retry_after_seconds": math.ceil(retry_after)},
            )
    if not await state.concurrency.try_acquire(settings.max_concurrent_plans):
        metrics.increment("rate_limited_total", {"reason": "busy"})
        raise RateLimitError(
            "The planner is busy with other trips. Please try again in a minute.",
            details={"reason": "busy", "retry_after_seconds": 30},
        )
    try:
        yield
    finally:
        await state.concurrency.release()
