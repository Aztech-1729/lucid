"""
Analytics service — Analytics aggregation logic.

Computes daily/weekly rollups, top performers, and per-campaign stats.
Writes results to analytics cache.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from cache import analytics_cache
from core.logging import get_logger
from repositories import analytics_repo

log = get_logger("analytics_service")


async def aggregate_daily(owner_id: int, date_str: str | None = None) -> dict:
    """
    Aggregate daily stats for a user.

    If no date_str is provided, uses today's date.
    """
    if date_str is None:
        date_str = datetime.utcnow().strftime("%Y%m%d")

    stats = await analytics_repo.get_daily_stats(owner_id, date_str)

    # Persist rollup in MongoDB
    await analytics_repo.upsert_daily(owner_id, date_str, stats)

    # Update cache
    await analytics_cache.set_daily(date_str, stats)

    return stats


async def aggregate_weekly(owner_id: int, week_str: str | None = None) -> dict:
    """
    Aggregate weekly stats for a user.
    """
    if week_str is None:
        now = datetime.utcnow()
        week_str = f"{now.year}{now.isocalendar()[1]:02d}"

    # Sum daily stats for the week
    now = datetime.utcnow()
    start_of_week = now - timedelta(days=now.weekday())

    total = {
        "total_sent": 0,
        "total_success": 0,
        "total_failed": 0,
        "flood_events": 0,
        "active_accounts": 0,
        "active_campaigns": 0,
    }

    for day_offset in range(7):
        day = start_of_week + timedelta(days=day_offset)
        if day > now:
            break
        date_str = day.strftime("%Y%m%d")
        daily = await analytics_repo.get_daily_stats(owner_id, date_str)
        for key in ("total_sent", "total_success", "total_failed", "flood_events"):
            total[key] += daily.get(key, 0)
        total["active_accounts"] = max(
            total["active_accounts"], daily.get("active_accounts", 0)
        )
        total["active_campaigns"] = max(
            total["active_campaigns"], daily.get("active_campaigns", 0)
        )

    await analytics_repo.upsert_weekly(owner_id, week_str, total)
    return total


async def update_top_performers(owner_id: int) -> None:
    """Refresh top accounts and top campaigns caches."""
    top_accounts = await analytics_repo.get_top_accounts(owner_id)
    top_campaigns = await analytics_repo.get_top_campaigns(owner_id)

    await analytics_cache.set_top_accounts(top_accounts)
    await analytics_cache.set_top_campaigns(top_campaigns)


async def build_dashboard(owner_id: int) -> dict:
    """
    Build the analytics dashboard payload for a user.
    """
    today = datetime.utcnow().strftime("%Y%m%d")
    daily = await analytics_repo.get_daily_stats(owner_id, today)
    top_accounts = await analytics_repo.get_top_accounts(owner_id, limit=5)
    top_campaigns = await analytics_repo.get_top_campaigns(owner_id, limit=5)

    # Calculate success rate
    total_sent = daily.get("total_sent", 0)
    total_success = daily.get("total_success", 0)
    success_rate = (total_success / total_sent) if total_sent > 0 else 0.0

    payload = {
        "today": {
            **daily,
            "success_rate": round(success_rate, 4),
        },
        "top_accounts": [
            {
                "account_id": a["_id"],
                "total": a.get("total", 0),
                "success": a.get("success", 0),
                "rate": round(a.get("rate", 0), 4),
            }
            for a in top_accounts
        ],
        "top_campaigns": [
            {
                "campaign_id": c["_id"],
                "total_sent": c.get("total_sent", 0),
                "success": c.get("success", 0),
            }
            for c in top_campaigns
        ],
        "updated_at": datetime.utcnow().isoformat(),
    }

    await analytics_cache.set_dashboard(owner_id, payload)
    return payload
