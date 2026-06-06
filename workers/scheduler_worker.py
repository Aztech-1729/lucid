"""
Scheduler worker — Cron-style task dispatcher.

Always running. Dispatches all other workers on their schedules,
monitors heartbeats, and restarts crashed workers.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from core.constants import CRASH_RECOVERY_DELAY, WorkerStatus
from core.logging import get_logger
from database import collections
from database.mongo import get_db
from utils.helpers import generate_id
from utils.metrics import WORKER_CRASHES, WORKER_RUNS, metrics
from workers import (
    analytics_worker,
    cache_worker,
    cleanup_worker,
    forwarding_worker,
    health_worker,
    log_worker,
)

log = get_logger("scheduler_worker")


class WorkerManager:
    """Manages background worker tasks with crash recovery."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._stop_event = asyncio.Event()
        self._generation_id = generate_id()

    async def start_all(self) -> None:
        """Launch all background workers."""
        workers = {
            "health_worker": health_worker.run,
            "analytics_worker": analytics_worker.run,
            "cache_worker": cache_worker.run,
            "forwarding_worker": forwarding_worker.run,
            "cleanup_worker": cleanup_worker.run,
            "log_worker": log_worker.run,
        }

        for name, worker_fn in workers.items():
            self._tasks[name] = asyncio.create_task(
                self._run_worker_safe(name, worker_fn),
                name=f"worker:{name}",
            )
            await self._record_worker(name, WorkerStatus.RUNNING)

        await log.ainfo(
            "scheduler.all_started",
            workers=list(workers.keys()),
            generation=self._generation_id,
        )

    async def stop_all(self) -> None:
        """Stop all workers gracefully."""
        self._stop_event.set()

        for name, task in self._tasks.items():
            task.cancel()

        # Wait for all tasks to finish
        if self._tasks:
            await asyncio.gather(
                *self._tasks.values(),
                return_exceptions=True,
            )

        for name in self._tasks:
            await self._record_worker(name, WorkerStatus.STOPPED)

        self._tasks.clear()
        await log.ainfo("scheduler.all_stopped")

    async def _run_worker_safe(self, name: str, worker_fn) -> None:
        """
        Run a worker with crash recovery.

        If the worker crashes, it is restarted after a delay.
        This loop continues until the stop event is set.
        """
        restart_count = 0

        while not self._stop_event.is_set():
            try:
                await worker_fn(stop_event=self._stop_event)
                break  # Clean exit
            except asyncio.CancelledError:
                break
            except Exception as exc:
                restart_count += 1
                await metrics.increment(WORKER_CRASHES)

                await log.aerror(
                    "scheduler.worker_crashed",
                    worker=name,
                    restart_count=restart_count,
                    error=str(exc),
                )

                await self._record_worker(
                    name,
                    WorkerStatus.CRASHED,
                    crash_reason=str(exc),
                    restart_count=restart_count,
                )

                # Wait before restart
                await asyncio.sleep(CRASH_RECOVERY_DELAY)

                await log.ainfo(
                    "scheduler.worker_restarting",
                    worker=name,
                    restart_count=restart_count,
                )

                await self._record_worker(name, WorkerStatus.RUNNING)

    async def _record_worker(
        self,
        worker_id: str,
        status: WorkerStatus,
        crash_reason: Optional[str] = None,
        restart_count: int = 0,
    ) -> None:
        """Record worker lifecycle in MongoDB."""
        try:
            db = get_db()
            await db[collections.WORKER_RECORDS].update_one(
                {"worker_id": worker_id},
                {
                    "$set": {
                        "worker_id": worker_id,
                        "generation_id": self._generation_id,
                        "status": status,
                        "crash_reason": crash_reason,
                        "restart_count": restart_count,
                        "last_heartbeat": datetime.utcnow(),
                        "updated_at": datetime.utcnow(),
                    },
                    "$setOnInsert": {
                        "created_at": datetime.utcnow(),
                    },
                },
                upsert=True,
            )
        except Exception:
            pass  # Don't let recording failures crash the scheduler

    async def get_status(self) -> dict:
        """Get the status of all workers."""
        result = {}
        for name, task in self._tasks.items():
            result[name] = {
                "running": not task.done(),
                "cancelled": task.cancelled(),
            }
        return result


# ── Global singleton ────────────────────────────────────────

worker_manager = WorkerManager()
