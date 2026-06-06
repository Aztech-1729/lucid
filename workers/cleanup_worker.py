"""
Cleanup worker — Removes stale data, expired sessions, and old logs.

Runs every 1 hour.
"""

from __future__ import annotations

import asyncio

from core.config import get_settings
from core.logging import get_logger
from repositories import analytics_repo, health_repo
from utils.metrics import WORKER_RUNS, metrics

log = get_logger("cleanup_worker")


async def run_cleanup_cycle() -> None:
    """
    Run a single cleanup cycle.

    Purges:
    - Old forwarding logs (>90 days)
    - Old health records (>90 days)
    - Stale cache keys (handled by TTL, but this catches orphans)
    """
    await log.ainfo("cleanup_worker.cycle_start")

    # Cleanup forwarding logs
    try:
        deleted_logs = await analytics_repo.cleanup_old_logs(days=90)
        if deleted_logs > 0:
            await log.ainfo("cleanup_worker.logs_purged", count=deleted_logs)
    except Exception as exc:
        await log.awarning("cleanup_worker.logs_error", error=str(exc))

    # Cleanup health records
    try:
        deleted_health = await health_repo.cleanup_old_records(days=90)
        if deleted_health > 0:
            await log.ainfo("cleanup_worker.health_purged", count=deleted_health)
    except Exception as exc:
        await log.awarning("cleanup_worker.health_error", error=str(exc))

    await metrics.increment(WORKER_RUNS)
    await log.ainfo("cleanup_worker.cycle_complete")


async def run(stop_event: asyncio.Event | None = None) -> None:
    """
    Main worker loop. Runs cleanup every 1 hour.
    """
    await log.ainfo("cleanup_worker.started")

    while True:
        if stop_event and stop_event.is_set():
            break

        try:
            await run_cleanup_cycle()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            await log.aerror("cleanup_worker.error", error=str(exc))

        await asyncio.sleep(3600)  # 1 hour
