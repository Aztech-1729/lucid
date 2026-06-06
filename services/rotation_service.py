"""
Rotation service — Smart account rotation scoring.

Computes rotation weights used by the forwarding worker to
distribute traffic across accounts proportionally.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from cache.redis_client import get_redis, make_key
from core.constants import AccountStatus, RedisKeys, ROTATION_WEIGHT_FLOOD, ROTATION_WEIGHT_HEALTH, ROTATION_WEIGHT_SUCCESS
from core.logging import get_logger
from models.account import Account
from repositories import accounts_repo

log = get_logger("rotation_service")


def compute_flood_penalty(flood_history: list) -> float:
    """
    Compute a penalty factor based on recent FloodWait events.

    More recent / more frequent floods → lower score.
    """
    if not flood_history:
        return 1.0

    recent_cutoff = datetime.utcnow() - timedelta(days=7)
    recent = [
        f for f in flood_history
        if hasattr(f, "occurred_at") and f.occurred_at > recent_cutoff
    ]

    if not recent:
        return 1.0

    # Penalty increases with number and severity of floods
    count_penalty = max(0.0, 1.0 - (len(recent) * 0.12))
    avg_seconds = sum(f.seconds for f in recent) / len(recent)
    severity_penalty = max(0.0, 1.0 - (avg_seconds / 300))

    return (count_penalty + severity_penalty) / 2


def compute_rotation_weight(account: Account) -> float:
    """
    Compute the rotation weight for an account.

    Accounts with higher weights receive proportionally more forwarding traffic.
    """
    if account.status in (
        AccountStatus.QUARANTINED,
        AccountStatus.BANNED,
        AccountStatus.DISABLED,
    ):
        return 0.0

    if account.status == AccountStatus.PAUSED:
        return 0.0

    health_factor = account.health_score / 100

    total_ops = account.success_count + account.failure_count
    if total_ops > 0:
        success_factor = account.success_count / total_ops
    else:
        success_factor = 1.0  # New accounts get full benefit

    flood_penalty = compute_flood_penalty(account.flood_wait_history)

    weight = round(
        health_factor * ROTATION_WEIGHT_HEALTH
        + success_factor * ROTATION_WEIGHT_SUCCESS
        + flood_penalty * ROTATION_WEIGHT_FLOOD,
        4,
    )
    return max(0.0, weight)


async def update_all_weights(owner_id: int | None = None) -> int:
    """
    Recompute rotation weights for all active accounts.

    If owner_id is provided, only recomputes for that user's accounts.
    """
    if owner_id:
        accounts = await accounts_repo.list_by_owner(owner_id)
    else:
        accounts = await accounts_repo.get_all_active()

    r = get_redis()
    key = make_key(RedisKeys.ACCOUNT_ROTATION_WEIGHTS)
    updated = 0

    for account in accounts:
        weight = compute_rotation_weight(account)
        await accounts_repo.update_rotation_score(account.id, weight)
        await r.hset(key, account.id, str(weight))
        updated += 1

    return updated


async def select_accounts(
    account_ids: list[str],
    count: int = 1,
) -> list[str]:
    """
    Select accounts using weighted random selection.

    Accounts with higher rotation weights are more likely to be selected.
    """
    if not account_ids:
        return []

    r = get_redis()
    key = make_key(RedisKeys.ACCOUNT_ROTATION_WEIGHTS)

    # Get weights from Redis
    weights: dict[str, float] = {}
    for aid in account_ids:
        raw = await r.hget(key, aid)
        weights[aid] = float(raw) if raw else 0.5

    # Filter out zero-weight accounts
    eligible = {aid: w for aid, w in weights.items() if w > 0}
    if not eligible:
        return []

    # Weighted random selection
    ids = list(eligible.keys())
    count = min(count, len(ids))

    # If we are selecting all eligible accounts, just return them
    if count == len(ids):
        return ids

    # Weighted random selection WITHOUT replacement
    selected = []
    current_eligible = eligible.copy()
    for _ in range(count):
        curr_ids = list(current_eligible.keys())
        curr_w = list(current_eligible.values())
        choice = random.choices(curr_ids, weights=curr_w, k=1)[0]
        selected.append(choice)
        del current_eligible[choice]
        
    return selected
