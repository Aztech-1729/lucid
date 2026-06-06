"""
Campaign cache layer.

Manages per-campaign summaries and paginated campaign lists.
"""

from __future__ import annotations

from typing import Any, Optional

from cache.redis_client import cache_delete, cache_delete_pattern, cache_get, cache_set, make_key
from core.constants import RedisKeys, TTL_CAMPAIGN_SUMMARY


async def get_summary(campaign_id: str) -> Optional[dict]:
    """Read a single campaign's summary from cache."""
    key = make_key(RedisKeys.CAMPAIGN_SUMMARY, campaign_id=campaign_id)
    return await cache_get(key)


async def set_summary(campaign_id: str, payload: dict[str, Any]) -> None:
    """Write a single campaign's summary to cache."""
    key = make_key(RedisKeys.CAMPAIGN_SUMMARY, campaign_id=campaign_id)
    await cache_set(key, payload, ttl=TTL_CAMPAIGN_SUMMARY)


async def invalidate_summary(campaign_id: str) -> None:
    """Remove a campaign's summary cache."""
    key = make_key(RedisKeys.CAMPAIGN_SUMMARY, campaign_id=campaign_id)
    await cache_delete(key)


async def get_page(user_id: int, page: int) -> Optional[dict]:
    """Read a paginated campaign list page from cache."""
    key = make_key(RedisKeys.CAMPAIGN_LIST_PAGE, user_id=user_id, page=page)
    return await cache_get(key)


async def set_page(user_id: int, page: int, payload: dict[str, Any]) -> None:
    """Write a paginated campaign list page to cache."""
    key = make_key(RedisKeys.CAMPAIGN_LIST_PAGE, user_id=user_id, page=page)
    await cache_set(key, payload, ttl=TTL_CAMPAIGN_SUMMARY)


async def invalidate_list(user_id: int) -> int:
    """Remove all paginated campaign list pages for a user."""
    pattern = make_key(RedisKeys.CAMPAIGN_LIST_PAGE, user_id=user_id, page="*")
    return await cache_delete_pattern(pattern)
