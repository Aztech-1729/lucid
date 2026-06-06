"""
Analytics cache layer.

Manages analytics dashboard, daily/weekly rollups, and top performers.
"""

from __future__ import annotations

from typing import Any, Optional

from cache.redis_client import cache_delete, cache_get, cache_set, get_redis, make_key
from core.constants import RedisKeys, TTL_ANALYTICS


async def get_dashboard(user_id: int) -> Optional[dict]:
    """Read analytics overview from cache."""
    key = make_key(RedisKeys.ANALYTICS_DASHBOARD, user_id=user_id)
    return await cache_get(key)


async def set_dashboard(user_id: int, payload: dict[str, Any]) -> None:
    """Write analytics overview to cache."""
    key = make_key(RedisKeys.ANALYTICS_DASHBOARD, user_id=user_id)
    await cache_set(key, payload, ttl=TTL_ANALYTICS)


async def get_daily(date_str: str) -> Optional[dict]:
    """Read daily rollup from cache."""
    key = make_key(RedisKeys.ANALYTICS_DAILY, date=date_str)
    return await cache_get(key)


async def set_daily(date_str: str, payload: dict[str, Any]) -> None:
    """Write daily rollup to cache."""
    key = make_key(RedisKeys.ANALYTICS_DAILY, date=date_str)
    await cache_set(key, payload, ttl=TTL_ANALYTICS)


async def get_top_accounts() -> Optional[list]:
    """Read top accounts from cache."""
    key = make_key(RedisKeys.ANALYTICS_TOP_ACCOUNTS)
    return await cache_get(key)


async def set_top_accounts(accounts: list[dict]) -> None:
    """Write top accounts to cache."""
    key = make_key(RedisKeys.ANALYTICS_TOP_ACCOUNTS)
    await cache_set(key, accounts, ttl=TTL_ANALYTICS)


async def get_top_campaigns() -> Optional[list]:
    """Read top campaigns from cache."""
    key = make_key(RedisKeys.ANALYTICS_TOP_CAMPAIGNS)
    return await cache_get(key)


async def set_top_campaigns(campaigns: list[dict]) -> None:
    """Write top campaigns to cache."""
    key = make_key(RedisKeys.ANALYTICS_TOP_CAMPAIGNS)
    await cache_set(key, campaigns, ttl=TTL_ANALYTICS)


async def invalidate_dashboard(user_id: int) -> None:
    """Remove analytics dashboard cache."""
    key = make_key(RedisKeys.ANALYTICS_DASHBOARD, user_id=user_id)
    await cache_delete(key)
