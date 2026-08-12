"""
Flood guard — shared flood-wait registry.

Telegram flood-waits are per-account. All workers (joiner, health,
forwarding) consult this guard before touching an account, so a
flood-waited account is left alone until its cooldown expires
instead of being hammered every few seconds.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from cache.redis_client import cache_delete, cache_get, cache_set
from core.logging import get_logger

log = get_logger("flood_guard")

# Same key namespace used by forwarding_service ("floodwait:{account_id}")
_FLOOD_KEY = "floodwait:{account_id}"

# Telegram spam-limitation flag ("limited:{account_id}")
_LIMITED_KEY = "limited:{account_id}"


async def mark_flood(account_id: str, seconds: float) -> None:
    """Record that an account is flood-waited until now + seconds."""
    until = time.time() + float(seconds)
    try:
        await cache_set(
            _FLOOD_KEY.format(account_id=account_id),
            {"until": until},
            ttl=int(seconds) + 30,
        )
    except Exception:
        pass


async def flood_remaining(account_id: str) -> float:
    """Seconds until the account's flood wait expires (0 = not flooded)."""
    try:
        data = await cache_get(_FLOOD_KEY.format(account_id=account_id))
    except Exception:
        return 0.0
    if not data:
        return 0.0
    if isinstance(data, dict):
        if "until" in data:
            return max(0.0, float(data["until"]) - time.time())
        if "wait" in data:  # legacy shape from forwarding_service
            return max(0.0, float(data["wait"]))
    return 0.0


async def is_flooded(account_id: str) -> bool:
    """True if the account is currently in a Telegram flood wait."""
    return await flood_remaining(account_id) > 0


async def mark_limited(account_id: str, ttl: int = 43200) -> None:
    """Record that Telegram has spam-limited this account (SpamBot LIMITED).

    A limited account gets "banned from sending messages in supergroups/channels"
    on every send and every join — hammering it only piles up failures.
    """
    try:
        await cache_set(
            _LIMITED_KEY.format(account_id=account_id),
            {"limited": True},
            ttl=ttl,
        )
    except Exception:
        pass


async def clear_limited(account_id: str) -> None:
    """Remove the limited flag once SpamBot reports the account healthy again."""
    try:
        await cache_delete(_LIMITED_KEY.format(account_id=account_id))
    except Exception:
        pass


async def is_limited(account_id: str) -> bool:
    """True if Telegram has spam-limited this account."""
    try:
        data = await cache_get(_LIMITED_KEY.format(account_id=account_id))
    except Exception:
        return False
    return bool(data)