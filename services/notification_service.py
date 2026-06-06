"""
Notification service — User alerts and push events.

Sends notifications via the bot client for health changes,
bans, campaign completions, and other events.
"""

from __future__ import annotations

from typing import Optional

from core.constants import HEALTH_EMOJI, HealthState
from core.logging import get_logger

log = get_logger("notification_service")

# Module-level bot client reference (set during startup)
_bot = None


def set_bot(bot) -> None:
    """Set the bot client for sending notifications."""
    global _bot
    _bot = bot


async def notify_user(user_id: int, message: str) -> bool:
    """
    Send a notification message to a user.

    Returns True if sent successfully.
    """
    if _bot is None:
        await log.awarning("notification.no_bot", user_id=user_id)
        return False

    try:
        await _bot.send_message(user_id, message, parse_mode="html")
        return True
    except Exception as exc:
        await log.awarning(
            "notification.send_failed",
            user_id=user_id,
            error=str(exc),
        )
        return False


async def notify_health_change(
    user_id: int,
    account_name: str,
    old_state: HealthState,
    new_state: HealthState,
    score: int,
) -> None:
    """Notify user of an account health state change."""
    old_emoji = HEALTH_EMOJI.get(old_state, "❓")
    new_emoji = HEALTH_EMOJI.get(new_state, "❓")

    message = (
        f"🩺 <b>Health Alert</b>\n\n"
        f"Account: <b>{account_name}</b>\n"
        f"Status: {old_emoji} {old_state.value} → {new_emoji} {new_state.value}\n"
        f"Health Score: <b>{score}/100</b>"
    )
    await notify_user(user_id, message)


async def notify_account_banned(
    user_id: int,
    account_name: str,
) -> None:
    """Notify user that an account has been banned."""
    message = (
        f"⛔ <b>Account Banned</b>\n\n"
        f"Account <b>{account_name}</b> has been detected as banned by Telegram.\n"
        f"The account has been disabled automatically.\n\n"
        f"Please check your accounts for more details."
    )
    await notify_user(user_id, message)


async def notify_account_removed(
    user_id: int,
    account_name: str,
    reason: str = "Unauthorized or Session Expired",
) -> None:
    """Notify user that an account has been removed automatically."""
    message = (
        f"🗑️ <b>Account Auto-Removed</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Account: <b>{account_name}</b>\n"
        f"Reason: <b>{reason}</b>\n\n"
        f"<i>This account has been removed from the bot for your safety. "
        f"Please re-add it if needed.</i>"
    )
    await notify_user(user_id, message)


async def notify_campaign_completed(
    user_id: int,
    campaign_name: str,
    stats: dict,
) -> None:
    """Notify user of campaign completion."""
    success = stats.get("total_success", 0)
    failed = stats.get("total_failed", 0)
    total = success + failed

    message = (
        f"📢 <b>Campaign Completed</b>\n\n"
        f"Campaign: <b>{campaign_name}</b>\n"
        f"Messages Sent: <b>{total}</b>\n"
        f"✅ Success: <b>{success}</b>\n"
        f"❌ Failed: <b>{failed}</b>"
    )
    await notify_user(user_id, message)


async def notify_plan_upgraded(
    user_id: int,
    new_plan: str,
) -> None:
    """Notify user of plan upgrade."""
    message = (
        f"🎉 <b>Plan Upgraded!</b>\n\n"
        f"Your plan has been upgraded to <b>{new_plan}</b>.\n"
        f"Enjoy your new features!"
    )
    await notify_user(user_id, message)


async def notify_flood_warning(
    user_id: int,
    account_name: str,
    wait_seconds: int,
) -> None:
    """Notify user of significant FloodWait on an account."""
    message = (
        f"⚠️ <b>FloodWait Warning</b>\n\n"
        f"Account <b>{account_name}</b> received a "
        f"<b>{wait_seconds}s</b> flood wait from Telegram.\n"
        f"Forwarding has been temporarily paused for this account."
    )
    await notify_user(user_id, message)
