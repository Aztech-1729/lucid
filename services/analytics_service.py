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
