"""
Health service — Health evaluation logic.

Computes health scores, parses SpamBot responses, and triggers
automatic actions based on thresholds.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from cache import health_cache
from core.config import get_settings
from core.constants import (
    AccountStatus,
    HEALTH_WEIGHT_AGE,
    HEALTH_WEIGHT_FLOOD,
    HEALTH_WEIGHT_RESTRICTIONS,
    HEALTH_WEIGHT_SPAMBOT,
    HEALTH_WEIGHT_SUCCESS_RATIO,
    HealthState,
)
from core.logging import get_logger
from models.account import Account
from models.health import HealthRecord
from repositories import accounts_repo, health_repo

log = get_logger("health_service")


def parse_spambot_response(response_text: str) -> HealthState:
    """
    Parse SpamBot's response text to determine health state.
    """
    text = response_text.lower()

    if "no limits" in text or "good news" in text or "no restrictions" in text:
        return HealthState.HEALTHY
    if "limited" in text or "restrict" in text:
        return HealthState.LIMITED
    if "ban" in text or "permanently" in text:
        return HealthState.BANNED
    if "warn" in text or "caution" in text:
        return HealthState.WARNING

    return HealthState.UNKNOWN


def compute_health_score(
    spambot_state: HealthState,
    account: Account,
) -> int:
    """
    Compute health score (0–100) using weighted factors.

    Factors:
    - SpamBot status: 40%
    - Recent FloodWait frequency: 20%
    - Success/failure ratio (30 days): 20%
    - Account age: 10%
    - Recent manual restrictions: 10%
    """
    # SpamBot factor (0.0 – 1.0)
    spambot_scores = {
        HealthState.HEALTHY: 1.0,
        HealthState.WARNING: 0.6,
        HealthState.LIMITED: 0.3,
        HealthState.QUARANTINED: 0.1,
        HealthState.BANNED: 0.0,
        HealthState.UNKNOWN: 0.5,
    }
    spambot_factor = spambot_scores.get(spambot_state, 0.5)

    # FloodWait frequency factor — more floods = lower score
    recent_floods = sum(
        1 for f in account.flood_wait_history
        if f.occurred_at > datetime.utcnow() - timedelta(days=7)
    )
    flood_factor = max(0.0, 1.0 - (recent_floods * 0.15))

    # Success/failure ratio factor
    total_ops = account.success_count + account.failure_count
    if total_ops > 0:
        success_factor = account.success_count / total_ops
    else:
        success_factor = 1.0  # New account gets full score

    # Account age factor (older = more trusted)
    age_days = (datetime.utcnow() - account.created_at).days
    if age_days > 365:
        age_factor = 1.0
    elif age_days > 90:
        age_factor = 0.8
    elif age_days > 30:
        age_factor = 0.6
    elif age_days > 7:
        age_factor = 0.4
    else:
        age_factor = 0.2

    # Restrictions factor (based on status)
    restriction_factor = 1.0
    if account.status == AccountStatus.QUARANTINED:
        restriction_factor = 0.1
    elif account.status == AccountStatus.PAUSED:
        restriction_factor = 0.7

    # Weighted score
    raw_score = (
        spambot_factor * HEALTH_WEIGHT_SPAMBOT
        + flood_factor * HEALTH_WEIGHT_FLOOD
        + success_factor * HEALTH_WEIGHT_SUCCESS_RATIO
        + age_factor * HEALTH_WEIGHT_AGE
        + restriction_factor * HEALTH_WEIGHT_RESTRICTIONS
    )

    return round(raw_score * 100)


async def evaluate_account(
    account: Account,
    spambot_response: str,
) -> HealthRecord:
    """
    Evaluate an account's health based on a SpamBot response.

    Computes score, stores record, and triggers threshold actions.
    """
    settings = get_settings()

    # Parse response
    state = parse_spambot_response(spambot_response)

    # Get previous state for change detection
    previous_record = await health_repo.get_latest(account.id)
    previous_state = previous_record.state if previous_record else None

    # Compute score
    score = compute_health_score(state, account)

    # Store record
    record = await health_repo.insert_record({
        "account_id": account.id,
        "owner_id": account.owner_id,
        "state": state,
        "score": score,
        "spambot_response": spambot_response,
        "previous_state": previous_state,
    })

    # Update account health score
    new_status = None
    if state == HealthState.BANNED:
        new_status = AccountStatus.BANNED
    elif score < settings.health_quarantine_threshold:
        new_status = AccountStatus.QUARANTINED
    elif score < settings.health_pause_threshold:
        new_status = AccountStatus.PAUSED

    await accounts_repo.update_health(account.id, score, new_status)

    # Invalidate account caches so dashboard updates immediately
    from cache import account_cache, dashboard_cache
    await account_cache.invalidate_summary(account.id)
    await account_cache.invalidate_list(account.owner_id)
    await dashboard_cache.invalidate(account.owner_id)

    # Schedule next check
    interval = settings.health_check_interval_seconds
    next_check = datetime.utcnow() + timedelta(seconds=interval)
    await accounts_repo.set_next_check(account.id, next_check)

    # Log state changes
    if previous_state and previous_state != state:
        await log.ainfo(
            "account.health_changed",
            account_id=account.id,
            old_status=previous_state,
            new_status=state,
            health_score=score,
        )

    # Update health cache
    await health_cache.set_account(account.id, {
        "state": state,
        "score": score,
        "checked_at": record.checked_at.isoformat(),
        "previous_state": previous_state,
    })

    return record


async def get_health_summary(owner_id: int) -> dict:
    """
    Build a health summary for a user's accounts.

    Returns counts by state and overall health percentage.
    """
    counts = await health_repo.count_by_state(owner_id)
    alerts = await health_repo.get_alerts(owner_id, limit=5)

    total = sum(counts.values())
    healthy = counts.get(HealthState.HEALTHY, 0)
    overall_pct = round((healthy / total) * 100) if total > 0 else 0

    return {
        "counts": {
            HealthState.HEALTHY: counts.get(HealthState.HEALTHY, 0),
            HealthState.WARNING: counts.get(HealthState.WARNING, 0),
            HealthState.LIMITED: counts.get(HealthState.LIMITED, 0),
            HealthState.QUARANTINED: counts.get(HealthState.QUARANTINED, 0),
            HealthState.BANNED: counts.get(HealthState.BANNED, 0),
            HealthState.UNKNOWN: counts.get(HealthState.UNKNOWN, 0),
        },
        "total_accounts": total,
        "overall_health_pct": overall_pct,
        "alerts": [
            {
                "account_id": a.account_id,
                "state": a.state,
                "previous_state": a.previous_state,
                "checked_at": a.checked_at.isoformat(),
            }
            for a in alerts
        ],
    }
