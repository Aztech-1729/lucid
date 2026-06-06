"""
Health worker — Polls SpamBot for every managed account on a rolling schedule.

Parses responses, computes health scores, triggers threshold actions,
and writes to health cache.
"""

from __future__ import annotations

import asyncio

from cache import health_cache
from core.config import get_settings
from core.constants import HealthState
from core.logging import get_logger
from repositories import accounts_repo
from services import health_service, notification_service
from telegram.client_pool import client_pool
from utils.metrics import HEALTH_CHECKS, metrics

log = get_logger("health_worker")


async def run_health_check_cycle() -> None:
    """
    Run a single health check cycle.

    Picks accounts due for check, contacts SpamBot for each,
    evaluates health, and updates caches.
    """
    accounts = await accounts_repo.get_due_for_check(limit=10)

    if not accounts:
        return

    await log.ainfo("health_worker.cycle_start", accounts=len(accounts))

    for account in accounts:
        try:
            await check_single_account(account)
            await metrics.increment(HEALTH_CHECKS)
        except Exception as exc:
            await log.awarning(
                "health_worker.check_failed",
                account_id=account.id,
                error=str(exc),
            )

        # Stagger checks to avoid burst
        await asyncio.sleep(2)

    await log.ainfo("health_worker.cycle_complete", checked=len(accounts))


async def check_single_account(account) -> None:
    """
    Check a single account against SpamBot.
    """
    try:
        async with client_pool.acquire(account.id) as client:
            # Refresh name from Telegram (to catch external changes)
            me = await client.get_me()
            if not me:
                await log.awarning("health_worker.auth_failed", account_id=account.id)
                from services import account_service
                await account_service.handle_unauthorized_account(account.id)
                return

            new_name = f"{me.first_name} {me.last_name or ''}".strip() or me.username or account.phone
            if new_name != account.name:
                await accounts_repo.update_name(account.id, new_name)
                account.name = new_name # Update local object for evaluate_account notifications
                
            # Send /start to SpamBot
            await client.send_message("SpamBot", "/start")

            # Wait a moment for response
            await asyncio.sleep(3)

            # Get latest response
            messages = await client.get_messages("SpamBot", limit=1)
            if not messages or messages[0].out:
                await log.awarning(
                    "health_worker.no_response",
                    account_id=account.id,
                )
                return

            response_text = messages[0].text or ""

    except Exception as exc:
        await log.awarning(
            "health_worker.spambot_error",
            account_id=account.id,
            error=str(exc),
        )
        return  # Skip evaluation — don't mark as UNKNOWN due to transient errors

    # Evaluate health
    record = await health_service.evaluate_account(account, response_text)

    # Send notifications on state changes
    if record.state_changed:
        if record.state == HealthState.BANNED:
            await notification_service.notify_account_banned(
                account.owner_id,
                account.display_name,
            )
        else:
            await notification_service.notify_health_change(
                user_id=account.owner_id,
                account_name=account.display_name,
                old_state=record.previous_state,
                new_state=record.state,
                score=record.score,
            )

    # Update health summary cache for owner
    summary = await health_service.get_health_summary(account.owner_id)
    await health_cache.set_summary(account.owner_id, summary)


async def run(stop_event: asyncio.Event | None = None) -> None:
    """
    Main worker loop. Runs health checks on schedule.
    """
    settings = get_settings()
    interval = settings.health_check_interval_seconds

    await log.ainfo("health_worker.started", interval=interval)

    while True:
        if stop_event and stop_event.is_set():
            break

        try:
            await run_health_check_cycle()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            await log.aerror("health_worker.error", error=str(exc))

        await asyncio.sleep(interval)
