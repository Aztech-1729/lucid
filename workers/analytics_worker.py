"""
Analytics worker — Aggregates stats into Redis on schedule.

Runs every 5 minutes, computing daily/weekly rollups and
top performer lists for all active users.
"""

from __future__ import annotations

import asyncio

from core.config import get_settings
from core.logging import get_logger
from repositories import users_repo
from services import analytics_service
from utils.metrics import WORKER_RUNS, metrics

log = get_logger("analytics_worker")


async def run_analytics_cycle() -> None:
    """
    Run a single analytics aggregation cycle.

    Aggregates daily stats, updates top performers, and builds
    analytics dashboards for all active users.
    """
    user_ids = await users_repo.get_all_active_user_ids()

    if not user_ids:
        return

    await log.ainfo("analytics_worker.cycle_start", users=len(user_ids))

    for user_id in user_ids:
        try:
            # Aggregate today's stats
            await analytics_service.aggregate_daily(user_id)

            # Update top performers
            await analytics_service.update_top_performers(user_id)

            # Build analytics dashboard
            await analytics_service.build_dashboard(user_id)

        except Exception as exc:
            await log.awarning(
                "analytics_worker.user_failed",
                user_id=user_id,
                error=str(exc),
            )

    await metrics.increment(WORKER_RUNS)
    await log.ainfo("analytics_worker.cycle_complete", users=len(user_ids))


async def run(stop_event: asyncio.Event | None = None) -> None:
    """
    Main worker loop. Runs analytics aggregation on schedule.
    """
    settings = get_settings()
    interval = settings.analytics_refresh_interval_seconds

    await log.ainfo("analytics_worker.started", interval=interval)

    while True:
        if stop_event and stop_event.is_set():
            break

        try:
            await run_analytics_cycle()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            await log.aerror("analytics_worker.error", error=str(exc))

        await asyncio.sleep(interval)
