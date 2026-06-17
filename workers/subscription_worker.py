"""
Subscription worker — Periodically checks if active users' subscriptions have expired.
Auto-pauses active campaigns if their trial or plan has expired.
"""

from __future__ import annotations

import asyncio
from core.constants import CampaignStatus
from core.logging import get_logger
from repositories import campaigns_repo, users_repo

log = get_logger("subscription_worker")

async def run_subscription_cycle() -> None:
    """Check all active campaigns, and pause them if the owner's subscription has expired."""
    await log.ainfo("subscription_worker.cycle_start")
    
    users_cache = {}
    paused_count = 0
    
    async for camp in campaigns_repo.get_active():
        owner_id = camp.owner_id
        if owner_id not in users_cache:
            users_cache[owner_id] = await users_repo.get(owner_id)
            
        user = users_cache[owner_id]
        if user and not user.is_active():
            # Plan expired!
            await campaigns_repo.update_status(camp.id, CampaignStatus.PAUSED)
            await log.awarning("campaign_paused", reason="subscription_expired", campaign_id=camp.id, owner_id=owner_id)
            paused_count += 1
            
    await log.ainfo("subscription_worker.cycle_complete", paused_count=paused_count)

async def run(stop_event: asyncio.Event | None = None) -> None:
    """Main worker loop. Runs every 5 minutes."""
    await log.ainfo("subscription_worker.started")
    while True:
        if stop_event and stop_event.is_set():
            break
            
        try:
            await run_subscription_cycle()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            await log.aerror("subscription_worker.error", error=str(exc))
            
        await asyncio.sleep(300) # 5 minutes
