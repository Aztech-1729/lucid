"""
Redis connection pool and client singleton.

Uses redis.asyncio (the successor to aioredis).
"""

from __future__ import annotations

import json
from typing import Any, Optional

import redis.asyncio as redis

from core.logging import get_logger

log = get_logger("redis")

# ── Module-level singleton ──────────────────────────────────

_client: Optional[redis.Redis] = None
_prefix: str = "lucidads"


async def init_redis(uri: str, prefix: str = "lucidads") -> None:
    """
    Initialize the Redis async client.

    Uses redis.from_url() which handles rediss:// (TLS) URIs automatically.
    Must be called once at startup before any cache module is used.
    """
    global _client, _prefix
    _prefix = prefix

    _client = redis.from_url(
        uri,
        decode_responses=True,
    )

    # Verify connectivity
    res = await _client.ping()
    await log.ainfo("redis.connected", prefix=prefix)


async def close_redis() -> None:
    """Close the Redis client and release all connections."""
    global _client

    if _client is not None:
        await _client.aclose()
        await log.ainfo("redis.disconnected")
        _client = None


def get_redis() -> redis.Redis:
    """Return the Redis client instance. Raises if not initialized."""
    if _client is None:
        raise RuntimeError("Redis not initialized. Call init_redis() first.")
    return _client


def make_key(template: str, **kwargs: Any) -> str:
    """
    Build a prefixed Redis key from a template.

    Example:
        make_key(RedisKeys.DASHBOARD, user_id=12345)
        → "lucidads:dashboard:12345"
    """
    key = template.format(**kwargs)
    return f"{_prefix}:{key}"


# ── Convenience helpers ─────────────────────────────────────

async def cache_get(key: str) -> Optional[dict]:
    """Get a JSON-serialized value from Redis, returning parsed dict or None."""
    raw = await get_redis().get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


async def cache_set(key: str, value: Any, ttl: int | None = None) -> None:
    """Set a JSON-serialized value in Redis with optional TTL."""
    raw = json.dumps(value, default=str)
    if ttl:
        await get_redis().setex(key, ttl, raw)
    else:
        await get_redis().set(key, raw)


async def cache_delete(key: str) -> None:
    """Delete a key from Redis."""
    await get_redis().delete(key)


async def cache_delete_pattern(pattern: str) -> int:
    """Delete all keys matching a pattern. Returns count deleted."""
    r = get_redis()
    count = 0
    async for key in r.scan_iter(match=pattern, count=100):
        await r.delete(key)
        count += 1
    return count
