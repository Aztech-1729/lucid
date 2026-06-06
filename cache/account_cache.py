"""
Account cache layer.

Manages per-account summaries and paginated account lists.
"""

from __future__ import annotations

from typing import Any, Optional

from cache.redis_client import cache_delete, cache_delete_pattern, cache_get, cache_set, make_key
from core.constants import RedisKeys, TTL_ACCOUNT_SUMMARY


async def get_summary(account_id: str) -> Optional[dict]:
    """Read a single account's summary from cache."""
    key = make_key(RedisKeys.ACCOUNT_SUMMARY, account_id=account_id)
    return await cache_get(key)


async def set_summary(account_id: str, payload: dict[str, Any]) -> None:
    """Write a single account's summary to cache."""
    key = make_key(RedisKeys.ACCOUNT_SUMMARY, account_id=account_id)
    await cache_set(key, payload, ttl=TTL_ACCOUNT_SUMMARY)


async def invalidate_summary(account_id: str) -> None:
    """Remove a single account's summary cache."""
    key = make_key(RedisKeys.ACCOUNT_SUMMARY, account_id=account_id)
    await cache_delete(key)


async def get_page(user_id: int, page: int) -> Optional[dict]:
    """Read a paginated account list page from cache."""
    key = make_key(RedisKeys.ACCOUNT_LIST_PAGE, user_id=user_id, page=page)
    return await cache_get(key)


async def set_page(user_id: int, page: int, payload: dict[str, Any]) -> None:
    """Write a paginated account list page to cache."""
    key = make_key(RedisKeys.ACCOUNT_LIST_PAGE, user_id=user_id, page=page)
    await cache_set(key, payload, ttl=TTL_ACCOUNT_SUMMARY)


async def invalidate_list(user_id: int) -> int:
    """Remove all paginated account list pages for a user."""
    pattern = make_key(RedisKeys.ACCOUNT_LIST_PAGE, user_id=user_id, page="*")
    return await cache_delete_pattern(pattern)
