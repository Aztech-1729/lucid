"""
Internal performance counters.

Thread-safe in-memory counters for monitoring system health.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime


class Metrics:
    """Simple in-memory counter registry."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()
        self._started_at = datetime.utcnow()

    async def increment(self, name: str, value: int = 1) -> None:
        """Increment a counter."""
        async with self._lock:
            self._counters[name] += value

    async def get(self, name: str) -> int:
        """Get a counter value."""
        return self._counters.get(name, 0)

    async def stats(self) -> dict[str, int | str]:
        """Return all counters as a dictionary."""
        async with self._lock:
            result = dict(self._counters)
        result["uptime_seconds"] = int((datetime.utcnow() - self._started_at).total_seconds())
        return result

    async def reset(self) -> None:
        """Reset all counters."""
        async with self._lock:
            self._counters.clear()
            self._started_at = datetime.utcnow()


# ── Well-known counter names ────────────────────────────────

MESSAGES_SENT = "messages_sent"
MESSAGES_FAILED = "messages_failed"
CACHE_HITS = "cache_hits"
CACHE_MISSES = "cache_misses"
FLOOD_WAITS = "flood_waits"
HEALTH_CHECKS = "health_checks"
WORKER_RUNS = "worker_runs"
WORKER_CRASHES = "worker_crashes"
CALLBACKS_HANDLED = "callbacks_handled"

# ── Global singleton ────────────────────────────────────────

metrics = Metrics()
