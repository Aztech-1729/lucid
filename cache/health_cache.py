"""
Health cache layer.

Manages health summary, per-account health, and alerts.
"""

from __future__ import annotations

from typing import Any, Optional

from cache.redis_client import cache_delete, cache_get, cache_set, make_key
from core.constants import RedisKeys, TTL_HEALTH_SUMMARY


async def get_summary(user_id: int) -> Optional[dict]:
    """Read the health overview payload from cache."""
    key = make_key(RedisKeys.HEALTH_SUMMARY, user_id=user_id)
    return await cache_get(key)


async def set_summary(user_id: int, payload: dict[str, Any]) -> None:
    """Write the health overview payload to cache."""
    key = make_key(RedisKeys.HEALTH_SUMMARY, user_id=user_id)
    await cache_set(key, payload, ttl=TTL_HEALTH_SUMMARY)


async def invalidate_summary(user_id: int) -> None:
    """Remove the health overview cache."""
    key = make_key(RedisKeys.HEALTH_SUMMARY, user_id=user_id)
    await cache_delete(key)


async def get_account(account_id: str) -> Optional[dict]:
    """Read health data for a specific account."""
    key = make_key(RedisKeys.HEALTH_ACCOUNT, account_id=account_id)
    return await cache_get(key)


async def set_account(account_id: str, payload: dict[str, Any]) -> None:
    """Write health data for a specific account."""
    key = make_key(RedisKeys.HEALTH_ACCOUNT, account_id=account_id)
    await cache_set(key, payload, ttl=TTL_HEALTH_SUMMARY)


async def get_alerts(user_id: int) -> Optional[list]:
    """Read recent health alerts from cache."""
    key = make_key(RedisKeys.HEALTH_ALERTS, user_id=user_id)
    return await cache_get(key)


async def set_alerts(user_id: int, alerts: list[dict]) -> None:
    """Write recent health alerts to cache."""
    key = make_key(RedisKeys.HEALTH_ALERTS, user_id=user_id)
    await cache_set(key, alerts, ttl=TTL_HEALTH_SUMMARY)
