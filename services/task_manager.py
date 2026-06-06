"""
Task Manager — Tracks and cancels active campaign tasks.
"""

from __future__ import annotations

import asyncio
from typing import Dict, Set

from core.logging import get_logger

log = get_logger("task_manager")

# Dictionary mapping campaign_id -> set of asyncio.Task
_active_tasks: Dict[str, Set[asyncio.Task]] = {}

def register_task(campaign_id: str, task: asyncio.Task) -> None:
    """Register a task to a campaign."""
    if campaign_id not in _active_tasks:
        _active_tasks[campaign_id] = set()
    _active_tasks[campaign_id].add(task)
    # Cleanup task from set when done
    task.add_done_callback(lambda t: _active_tasks.get(campaign_id, set()).discard(t))

async def cancel_campaign_tasks(campaign_id: str) -> None:
    """Cancel all active tasks for a specific campaign."""
    tasks = _active_tasks.get(campaign_id, set())
    if not tasks:
        return

    log.info("task_manager.cancelling_tasks", campaign_id=campaign_id, task_count=len(tasks))
    for task in tasks:
        if not task.done():
            task.cancel()
    
    # Wait for cancellation to complete
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _active_tasks.pop(campaign_id, None)
