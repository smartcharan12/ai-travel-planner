"""Minimal in-process metrics registry behind GET /api/v1/metrics.

Two primitives cover what we need:

- counters  monotonically increasing integers, e.g. ``http_requests_total{status=200}``
- timings   count / sum / max of durations, e.g. LLM latency per call

Honest limitation: the numbers live in this process's memory. With 3
Kubernetes replicas each pod reports only its own traffic, and a restart
resets them. That is acceptable here because the durable, cross-pod view is
built from logs in ELK (Stage 4). A larger system would export these to
Prometheus / Cloud Monitoring instead.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict


def _key(name: str, labels: dict[str, str] | None) -> str:
    """Render ``name{a=1,b=2}`` with sorted labels so keys are stable."""
    if not labels:
        return name
    rendered = ",".join(f"{k}={labels[k]}" for k in sorted(labels))
    return f"{name}{{{rendered}}}"


class MetricsRegistry:
    def __init__(self) -> None:
        # FastAPI runs sync dependencies in a thread pool, so guard mutations.
        self._lock = threading.Lock()
        self._started = time.monotonic()
        self._counters: dict[str, int] = defaultdict(int)
        self._timings: dict[str, dict[str, float]] = {}

    def increment(self, name: str, labels: dict[str, str] | None = None, value: int = 1) -> None:
        with self._lock:
            self._counters[_key(name, labels)] += value

    def observe_ms(self, name: str, duration_ms: float, labels: dict[str, str] | None = None) -> None:
        key = _key(name, labels)
        with self._lock:
            stats = self._timings.setdefault(key, {"count": 0, "sum": 0.0, "max": 0.0})
            stats["count"] += 1
            stats["sum"] += duration_ms
            stats["max"] = max(stats["max"], duration_ms)

    def snapshot(self) -> dict:
        """Copy current values; averages are derived here rather than stored."""
        with self._lock:
            timings = {
                key: {
                    "count": s["count"],
                    "avg": round(s["sum"] / s["count"], 2) if s["count"] else 0.0,
                    "max": round(s["max"], 2),
                }
                for key, s in self._timings.items()
            }
            return {
                "uptime_seconds": round(time.monotonic() - self._started, 1),
                "counters": dict(self._counters),
                "timings_ms": timings,
            }


# One registry per process. Imported wherever something is worth counting.
metrics = MetricsRegistry()
