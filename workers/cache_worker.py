"""
Cache worker — Pre-warms and refreshes all caches on schedule.

Runs every 2 minutes, building dashboard, account list, campaign list,
and health summary caches for all active users.
"""

from __future__ import annotations

import asyncio

from cache import account_cache, campaign_cache, health_cache
from core.config import get_settings
from core.logging import get_logger
from repositories import accounts_repo, campaigns_repo, users_repo
from services import dashboard_service, health_service, rotation_service
from utils.formatters import format_account_status, format_health_score, mask_phone
from utils.metrics import WORKER_RUNS, metrics
from utils.pagination import Paginator

log = get_logger("cache_worker")


async def run_cache_cycle() -> None:
    """
    Run a single cache warming cycle.

    Pre-warms all user-facing caches so callbacks never wait for DB.
    """
    user_ids = await users_repo.get_all_active_user_ids()

    if not user_ids:
        return

    await log.ainfo("cache_worker.cycle_start", users=len(user_ids))

    for user_id in user_ids:
        try:
            await warm_user_cache(user_id)
        except Exception as exc:
            await log.awarning(
                "cache_worker.user_failed",
                user_id=user_id,
                error=str(exc),
            )

    # Update rotation weights
    await rotation_service.update_all_weights()

    await metrics.increment(WORKER_RUNS)
    await log.ainfo("cache_worker.cycle_complete", users=len(user_ids))


async def warm_user_cache(user_id: int) -> None:
    """Pre-warm all caches for a single user."""
    # Dashboard
    await dashboard_service.build_dashboard(user_id)

    # Account list (paginated)
    accounts = await accounts_repo.list_by_owner(user_id)
    paginator = Paginator(accounts, page=1)

    for page_num in range(1, paginator.total_pages + 1):
        p = Paginator(accounts, page=page_num)
        page_data = {
            "accounts": [
                {
                    "id": a.id,
                    "display_name": a.display_name,
                    "phone": mask_phone(a.phone),
                    "status": a.status,
                    "status_display": format_account_status(a.status),
                    "health_score": a.health_score,
                    "health_display": format_health_score(a.health_score),
                    "success_rate": round(a.success_rate, 4),
                }
                for a in p.current_page
            ],
            "total_items": len(accounts),
            "pagination": p.to_dict(),
        }
        await account_cache.set_page(user_id, page_num, page_data)

    # Account summaries
    for account in accounts:
        await account_cache.set_summary(account.id, {
            "id": account.id,
            "display_name": account.display_name,
            "phone": mask_phone(account.phone),
            "name": account.name,
            "status": account.status,
            "status_display": format_account_status(account.status),
            "health_score": account.health_score,
            "health_display": format_health_score(account.health_score),
            "rotation_score": account.rotation_score,
            "success_count": account.success_count,
            "failure_count": account.failure_count,
            "success_rate": round(account.success_rate, 4),
            "created_at": account.added_at.isoformat(),
            "last_used_at": account.last_used_at.isoformat() if account.last_used_at else None,
            "last_checked_at": account.last_checked_at.isoformat() if hasattr(account, 'last_checked_at') and account.last_checked_at else None,
            "notes": account.notes,
            "tags": account.tags,
            "flood_wait_history": [e.model_dump() for e in account.flood_wait_history],
        })

    # Campaign list (paginated)
    campaigns = await campaigns_repo.list_by_owner(user_id)
    campaign_paginator = Paginator(campaigns, page=1)

    if campaign_paginator.total_pages == 0:
        await campaign_cache.set_page(user_id, 1, {
            "campaigns": [],
            "pagination": campaign_paginator.to_dict(),
        })
    else:
        for page_num in range(1, campaign_paginator.total_pages + 1):
            p = Paginator(campaigns, page=page_num)
            page_data = {
                "campaigns": [
                    {
                        "id": c.id,
                        "name": c.name,
                        "status": c.status,
                        "total_sent": c.stats.total_sent,
                        "success_rate": round(c.stats.success_rate, 4),
                        "account_count": len(c.account_ids),
                        "group_count": len(c.group_ids),
                    }
                    for c in p.current_page
                ],
                "pagination": p.to_dict(),
            }
            await campaign_cache.set_page(user_id, page_num, page_data)

    # Build individual campaign summaries
    for c in campaigns:
        c_data = c.model_dump(mode="json")
        c_data["account_count"] = len(c.account_ids)
        c_data["group_count"] = len(c.group_ids)
        c_data["success_count"] = c.stats.success_count if hasattr(c.stats, "success_count") else 0
        c_data["failure_count"] = c.stats.failure_count if hasattr(c.stats, "failure_count") else 0
        await campaign_cache.set_summary(c.id, c_data)

    # Health summary
    summary = await health_service.get_health_summary(user_id)
    await health_cache.set_summary(user_id, summary)


async def run(stop_event: asyncio.Event | None = None) -> None:
    """
    Main worker loop. Runs cache warming on schedule.
    """
    settings = get_settings()
    interval = settings.cache_refresh_interval_seconds

    await log.ainfo("cache_worker.started", interval=interval)

    while True:
        if stop_event and stop_event.is_set():
            break

        try:
            await run_cache_cycle()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            await log.aerror("cache_worker.error", error=str(exc))

        await asyncio.sleep(interval)
