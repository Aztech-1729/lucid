"""
Dashboard service — Dashboard state assembly.

Builds the dashboard payload from account, health, campaign, and
analytics data. Writes to dashboard cache for instant callback reads.
"""

from __future__ import annotations

from datetime import datetime

from cache import dashboard_cache
from core.logging import get_logger
from repositories import accounts_repo, campaigns_repo, health_repo, users_repo

log = get_logger("dashboard_service")


async def build_dashboard(user_id: int) -> dict:
    """
    Assemble and cache the dashboard payload for a user.

    Called by the cache_worker on schedule.
    """
    # User info
    user = await users_repo.get(user_id)
    username = user.username if user else "User"

    # Account counts by status
    # We use a broad filter to ensure everything is counted
    accounts = await accounts_repo.list_by_owner(user_id)
    total_accounts = len(accounts)
    # Active = anything not BANNED or DISABLED
    from core.constants import AccountStatus
    active_count = sum(1 for a in accounts if a.status not in (AccountStatus.BANNED, AccountStatus.DISABLED))

    # Campaign counts
    campaigns = await campaigns_repo.list_by_owner(user_id)
    active_campaigns = sum(1 for c in campaigns if c.status == "ACTIVE")

    # Health summary
    health_counts = await health_repo.count_by_state(user_id)

    # All-time analytics
    from repositories import analytics_repo
    stats = await analytics_repo.get_all_time_stats(user_id)

    total_sent = stats.get("total_sent", 0)
    total_success = stats.get("total_success", 0)
    total_failed = stats.get("total_failed", 0)
    success_rate = (total_success / total_sent * 100) if total_sent > 0 else 0

    # Health summary
    total_health = sum(health_counts.values()) if health_counts else 0
    healthy_count = health_counts.get("HEALTHY", 0) if health_counts else 0
    overall_health = round((healthy_count / total_health) * 100) if total_health > 0 else 100

    # Flat payload matching menus.render_dashboard() expected keys
    payload = {
        "username": username or "User",
        "total_accounts": total_accounts,
        "active_accounts": active_count,
        "active_campaigns": active_campaigns,
        "total_forwarded": total_sent,
        "successful": total_success,
        "failed": total_failed,
        "success_rate": success_rate,
        "uptime": 99.9,
        "healthy_accounts": healthy_count,
        "warning_accounts": health_counts.get("WARNING", 0) if health_counts else 0,
        "limited_accounts": health_counts.get("LIMITED", 0) if health_counts else 0,
        "quarantined_accounts": health_counts.get("QUARANTINED", 0) if health_counts else 0,
        "overall_health": overall_health,
        "updated_at": datetime.utcnow().isoformat(),
    }

    await dashboard_cache.set(user_id, payload)
    return payload
