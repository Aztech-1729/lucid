"""
Forwarding worker — Executes message forwarding tasks.

Picks up active campaigns, manages concurrent background tasks for them,
and executes their group forwarding round-by-round.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from core.config import get_settings
from core.logging import get_logger
from repositories import campaigns_repo, account_groups_repo
from services import forwarding_service, rotation_service
from telegram.client_pool import client_pool
from utils.metrics import WORKER_RUNS, metrics
from core.constants import CampaignStatus

log = get_logger("forwarding_worker")

# Global dict to track currently running campaigns
_active_campaign_tasks: dict[str, asyncio.Task] = {}


async def run_forwarding_cycle() -> None:
    """
    Check the database for ACTIVE campaigns.
    Start a background task for any new ACTIVE campaign.
    Stop any background task if its campaign is no longer ACTIVE.
    """
    campaigns = await campaigns_repo.get_active()
    active_ids = {c.id for c in campaigns}

    # Stop tasks for campaigns that were paused or deleted
    for camp_id, task in list(_active_campaign_tasks.items()):
        if camp_id not in active_ids:
            if not task.done():
                task.cancel()
            _active_campaign_tasks.pop(camp_id, None)

    if not campaigns:
        return

    started_count = 0
    for campaign in campaigns:
        if campaign.id not in _active_campaign_tasks or _active_campaign_tasks[campaign.id].done():
            # Start background loop for this campaign
            task = asyncio.create_task(process_campaign_safe(campaign))
            _active_campaign_tasks[campaign.id] = task
            started_count += 1

    if started_count > 0:
        await log.ainfo("forwarding_worker.campaigns_started", new_started=started_count, total_running=len(_active_campaign_tasks))
        await metrics.increment(WORKER_RUNS)


async def process_campaign_safe(campaign) -> None:
    """Wrapper to catch exceptions so a campaign crash doesn't kill the worker."""
    try:
        await log.ainfo("forwarding_worker.campaign_task_started", campaign_id=campaign.id)
        await process_campaign_loop(campaign)
    except asyncio.CancelledError:
        await log.ainfo("forwarding_worker.campaign_task_cancelled", campaign_id=campaign.id)
    except Exception as exc:
        await log.aerror("forwarding_worker.campaign_fatal_error", campaign_id=campaign.id, error=str(exc))
    finally:
        _active_campaign_tasks.pop(campaign.id, None)


async def process_campaign_loop(campaign) -> None:
    """
    Main loop for a single campaign.
    Executes rounds endlessly or up to max_rounds, pausing for round_delay_seconds.
    """
    round_number = 0

    while True:
        # 1. Ensure campaign is still ACTIVE in db (e.g. paused by user)
        current_camp = await campaigns_repo.get(campaign.id)
        if not current_camp or current_camp.status != CampaignStatus.ACTIVE:
            await log.ainfo("forwarding_worker.campaign_stopped", campaign_id=campaign.id)
            break

        # 2. Check if we hit max rounds
        max_rounds = current_camp.max_rounds or 0
        if max_rounds > 0 and round_number >= max_rounds:
            await log.ainfo("forwarding_worker.campaign_completed", campaign_id=campaign.id, rounds=round_number)
            await campaigns_repo.update_status(campaign.id, CampaignStatus.COMPLETED)
            break

        round_number += 1
        await log.ainfo("forwarding_worker.round_starting", campaign_id=campaign.id, round=round_number)

        # 3. Execute ONE round (forwarding to all groups)
        await execute_single_round(current_camp)

        # 4. Determine delay until next round
        delay = current_camp.round_delay_seconds or get_settings().default_forward_delay_seconds
        
        # We don't delay if we are about to exit max rounds
        if max_rounds > 0 and round_number >= max_rounds:
            continue
            
        await log.ainfo("forwarding_worker.waiting_for_next_round", campaign_id=campaign.id, delay_seconds=delay)
        
        # Wait safely (allows cancellation if user pauses campaign)
        await asyncio.sleep(delay)


async def execute_single_round(campaign) -> None:
    """
    Selects accounts, distributes groups, and runs forwards concurrently for all accounts.
    """
    if not campaign.account_ids or not campaign.group_ids:
        return

    # Select accounts using rotation weights
    selected = await rotation_service.select_accounts(
        campaign.account_ids,
        count=len(campaign.account_ids),
    )

    if not selected:
        await log.awarning(
            "forwarding_worker.no_eligible_accounts",
            campaign_id=campaign.id,
        )
        return

    # Load target groups from account_groups
    groups = await account_groups_repo.list_by_ids(campaign.group_ids)
    if not groups:
        return

    # Distribute groups by account_id
    account_groups_map = {}
    for g in groups:
        acc_id = g.get("account_id")
        if not acc_id:
            continue
        if acc_id not in account_groups_map:
            account_groups_map[acc_id] = []
        account_groups_map[acc_id].append({
            "_id": str(g.get("_id")),
            "group_id": g.get("group_id"),
            "topic_id": g.get("topic_id"),
        })

    tasks = []
    for i, account_id in enumerate(selected):
        acc_groups = account_groups_map.get(account_id, [])
        if not acc_groups:
            continue
            
        # Stagger task creation/start for safety (0.2s per account)
        async def staggered_forward(acc_id, camp, grps, d, offset):
            if offset > 0:
                await asyncio.sleep(offset)
            return await forward_for_account(acc_id, camp, grps, d)

        tasks.append(
            staggered_forward(
                acc_id=account_id,
                camp=campaign,
                grps=acc_groups,
                d=campaign.group_delay_seconds,
                offset=i * 0.2
            )
        )

    if not tasks:
        return

    # Run forwards for this round
    task_bundle = asyncio.gather(*tasks, return_exceptions=True)
    
    # We still register it with task_manager in case old stop logic needs it
    from services.task_manager import register_task
    register_task(campaign.id, task_bundle)
    
    results = await task_bundle

    # Update campaign stats
    total_success = 0
    total_failed = 0
    for result in results:
        if isinstance(result, dict):
            total_success += result.get("success", 0)
            total_failed += result.get("failed", 0)

    # Refresh campaign stats since they might have been updated by other tasks
    latest_camp = await campaigns_repo.get(campaign.id)
    if not latest_camp:
        return

    await campaigns_repo.update_stats(campaign.id, {
        "total_sent": latest_camp.stats.total_sent + total_success + total_failed,
        "total_success": latest_camp.stats.total_success + total_success,
        "total_failed": latest_camp.stats.total_failed + total_failed,
        "last_run_at": datetime.utcnow(),
    })
    
    # Invalidate cache so UI shows fresh stats
    from cache import campaign_cache
    await campaign_cache.invalidate_summary(campaign.id)


async def forward_for_account(
    account_id: str,
    campaign,
    groups: list[dict],
    delay: float,
) -> dict:
    """Forward message from a specific account to a set of groups."""
    try:
        from repositories import accounts_repo as acc_repo
        account = await acc_repo.get(account_id)
        health_score = account.health_score if account else 100

        async with client_pool.acquire(account_id) as client:
            return await forwarding_service.forward_to_groups(
                client=client,
                account_id=account_id,
                campaign=campaign,
                groups=groups,
                delay=delay,
                health_score=health_score,
            )
    except Exception as exc:
        await log.awarning(
            "forwarding_worker.account_error",
            account_id=account_id,
            error=str(exc),
        )
        return {"success": 0, "failed": len(groups), "total": len(groups)}


async def run(stop_event: asyncio.Event | None = None) -> None:
    """
    Main worker loop.
    Periodically checks for newly activated campaigns or pauses.
    """
    settings = get_settings()
    interval = 10  # Fast check interval to spawn tasks immediately!

    await log.ainfo("forwarding_worker.started")

    while True:
        if stop_event and stop_event.is_set():
            break

        try:
            await run_forwarding_cycle()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            await log.aerror("forwarding_worker.error", error=str(exc))

        # Wait for either the polling interval OR an instant trigger
        from services.forwarding_trigger import wait_for_trigger
        await wait_for_trigger(timeout=interval)
