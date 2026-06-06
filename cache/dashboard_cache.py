"""
Dashboard cache layer.

Manages the pre-rendered dashboard payload for each user.
Workers write this cache; callbacks read it.
"""

from __future__ import annotations

from typing import Any, Optional

from cache.redis_client import cache_delete, cache_get, cache_set, make_key
from core.constants import RedisKeys, TTL_DASHBOARD


async def get(user_id: int) -> Optional[dict]:
    """Read the dashboard payload from cache."""
    key = make_key(RedisKeys.DASHBOARD, user_id=user_id)
    return await cache_get(key)


async def set(user_id: int, payload: dict[str, Any]) -> None:
    """Write the dashboard payload to cache."""
    key = make_key(RedisKeys.DASHBOARD, user_id=user_id)
    await cache_set(key, payload, ttl=TTL_DASHBOARD)


async def invalidate(user_id: int) -> None:
    """Remove the dashboard cache for a user."""
    key = make_key(RedisKeys.DASHBOARD, user_id=user_id)
    await cache_delete(key)
