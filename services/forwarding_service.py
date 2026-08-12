"""
Forwarding service — Message forwarding orchestration.

Uses ClientPool for all Telegram API calls.
Handles FloodWait, retries, topic support, and result logging.
"""

from __future__ import annotations

import typing
from typing import Any, Callable, Coroutine, cast, Optional
import asyncio
import random

from telethon.errors import (
    ChatAdminRequiredError,
    ChatWriteForbiddenError,
    ChannelPrivateError,
    FloodWaitError,
    UserBannedInChannelError,
    UserDeactivatedError,
    AuthKeyUnregisteredError,
)

try:
    from telethon.errors import PeerIdInvalidError
except ImportError:
    PeerIdInvalidError = None  # Older Telethon versions
from telethon.errors.common import TypeNotFoundError

from core.config import get_settings
from core.logging import get_logger
from repositories import accounts_repo, analytics_repo
from utils.metrics import FLOOD_WAITS, MESSAGES_FAILED, MESSAGES_SENT, metrics

log = get_logger("forwarding_service")


async def safe_forward(
    client: Any,
    account_id: str,
    campaign_id: str,
    group_id: str,
    owner_id: int,
    message: Any,
    target: Any,
    topic_id: int | None = None,
    access_hash: int = 0,
    retries: int = 3,
    campaign_name: str = "",
    account_phone: str = "",
) -> bool:
    """
    Forward a message with FloodWait handling and retry logic.

    This is the core forwarding function used by the forwarding worker.
    """
    for attempt in range(retries):
        try:
            sent_msgs = None
            
            # Keep the raw target (telegram id like "-100...") — after entity
            # resolution `target` becomes an InputPeer whose str() is
            # "InputPeerChannel(...)", which never matches is_toxic() lookups.
            raw_target = str(target)
            
            # Resolve target entity
            if isinstance(target, (int, str)):
                resolved = False
                
                # Fast path: Construct InputPeer directly if we have the access hash
                if access_hash != 0:
                    try:
                        from telethon.tl.types import InputPeerChannel, InputPeerChat
                        
                        target_id = target if isinstance(target, int) else int(target)
                        
                        # Telethon needs the stripped ID for InputPeerChannel
                        if str(target_id).startswith("-100"):
                            real_id = abs(target_id) - 1000000000000
                            target = InputPeerChannel(real_id, access_hash)
                        elif target_id < 0:
                            target = InputPeerChat(abs(target_id))
                        resolved = True
                    except Exception:
                        pass
                
                # Step 1: Try cached lookup (fast path if already in session)
                if not resolved:
                    try:
                        target = await client.get_input_entity(target)
                        resolved = True
                    except Exception:
                        pass

                # Step 2: Try get_entity with -100 prefix for channels
                if not resolved and isinstance(target, int) and target > 0:
                    try:
                        target = await client.get_entity(int(f"-100{target}"))
                        resolved = True
                    except Exception:
                        pass

                # Step 3: Try get_entity with the raw ID
                if not resolved:
                    try:
                        target = await client.get_entity(target)
                        resolved = True
                    except Exception:
                        pass

                # Step 4: Last resort — populate cache via get_dialogs (AVOID if possible)
                if not resolved:
                    try:
                        # Stagger the get_dialogs so multiple workers don't flood the network concurrently
                        await asyncio.sleep(random.uniform(0.5, 2.0))
                        await client.get_dialogs()
                        target = await client.get_input_entity(target)
                        resolved = True
                    except Exception:
                        pass  # Fallback to using the raw ID if all resolution fails

                # If still not resolved after all steps, skip this group
                if not resolved:
                    await log.awarning("forward.target_resolution_failed", target=str(target), account_id=account_id)
                    return False

            # Logic: If it's a string, we MUST use send_message.
            # If it's a message object AND there's a topic, we use send_message (resends the object).
            # If it's a message object AND NO topic, we use forward_messages (preserves "Forwarded from").
            if isinstance(message, str) or topic_id:
                sent_msgs = await client.send_message(
                    target,
                    message,
                    reply_to=topic_id,
                )
            else:
                try:
                    sent_msgs = await client.forward_messages(target, message)
                except ChatAdminRequiredError:
                    # Group restricts forwarding — fall back to send_message
                    await log.ainfo(
                        "forward.fallback_to_send",
                        account_id=account_id,
                        group_id=group_id,
                    )
                    sent_msgs = await client.send_message(target, message)

            # Extract message link if possible
            msg_link = ""
            if sent_msgs:
                if isinstance(sent_msgs, list) and len(sent_msgs) > 0:
                    first_msg = sent_msgs[0]
                    # telethon Message object has no built-in link property, but we can construct it if it's a channel/megagroup
                    # Actually, Telethon Message sometimes has `.message_link` or we can just try to get it.
                    if hasattr(first_msg, 'chat') and getattr(first_msg.chat, 'username', None):
                        msg_link = f"https://t.me/{first_msg.chat.username}/{first_msg.id}"
                elif hasattr(sent_msgs, 'chat') and getattr(sent_msgs.chat, 'username', None):  # type: ignore[attr-defined]
                    msg_link = f"https://t.me/{getattr(sent_msgs.chat, 'username')}/{sent_msgs.id}"  # type: ignore[attr-defined]

            # Success
            await accounts_repo.increment_counters(account_id, success=1)
            await analytics_repo.log_forward(
                campaign_id=campaign_id,
                account_id=account_id,
                group_id=group_id,
                owner_id=owner_id,
                success=True,
                campaign_name=campaign_name,
                account_phone=account_phone,
            )
            await metrics.increment(MESSAGES_SENT)
            
            try:
                from telegram.logs_bot import send_ad_success_log
                await send_ad_success_log(
                    owner_id,
                    campaign_name or "Unknown",
                    account_phone or "Unknown",
                    group_id,
                    msg_link,
                )
            except Exception as log_err:
                await log.awarning("forward.log_bot_error", error=str(log_err), account_id=account_id)
                
            return True

        except FloodWaitError as e:
            await metrics.increment(FLOOD_WAITS)
            await accounts_repo.add_flood_event(account_id, e.seconds)
            
            # Log Flood to Group Health
            try:
                from repositories import group_health_repo
                await group_health_repo.log_interaction(str(target), success=False, is_flood=True)
            except Exception:
                pass

            await analytics_repo.log_forward(
                campaign_id=campaign_id,
                account_id=account_id,
                group_id=group_id,
                owner_id=owner_id,
                success=False,
                error_message=f"FloodWait: {e.seconds}s",
                flood_wait_seconds=e.seconds,
                campaign_name=campaign_name,
                account_phone=account_phone,
            )

            wait_time = e.seconds + random.uniform(1, 5)
            
            # Global FloodWait Tracking
            try:
                from cache.redis_client import cache_set
                await cache_set(f"floodwait:{account_id}", {"wait": wait_time}, ttl=int(wait_time))
            except Exception:
                pass

            settings = get_settings()
            if wait_time > settings.max_flood_wait_seconds:
                await log.awarning(
                    "forward.flood_wait_too_long_quarantined",
                    account_id=account_id,
                    wait_seconds=e.seconds,
                )
                # Immediately limit the account
                from core.constants import AccountStatus
                await accounts_repo.update_health(account_id, 0, AccountStatus.LIMITED)
                
                await log.awarning(
                    "forward.account_limited_due_to_flood",
                    account_id=account_id,
                    seconds=e.seconds
                )
                from core.exceptions import AccountLimitedError
                raise AccountLimitedError(f"Limited due to excessive FloodWait ({e.seconds}s)")


            await log.awarning(
                "forward.flood_wait",
                account_id=account_id,
                wait_seconds=round(wait_time, 1),
                attempt=attempt + 1,
            )
            await asyncio.sleep(wait_time)

        except (UserBannedInChannelError, ChannelPrivateError) as e:
            # Permanent failures — don't retry, mark group as restricted
            await accounts_repo.increment_counters(account_id, failure=1)
            await analytics_repo.log_forward(
                campaign_id=campaign_id,
                account_id=account_id,
                group_id=group_id,
                owner_id=owner_id,
                success=False,
                error_message=str(e),
                campaign_name=campaign_name,
                account_phone=account_phone,
            )
            await metrics.increment(MESSAGES_FAILED)
            
            # Mark this group as permanently restricted so we never try again
            try:
                from repositories import group_health_repo
                await group_health_repo.mark_restricted(raw_target, reason=type(e).__name__)
            except Exception:
                pass
            return False

        except ChatAdminRequiredError as e:
            # ChatAdminRequiredError is common for topic groups — log and skip, don't permanently restrict
            await accounts_repo.increment_counters(account_id, failure=1)
            await analytics_repo.log_forward(
                campaign_id=campaign_id,
                account_id=account_id,
                group_id=group_id,
                owner_id=owner_id,
                success=False,
                error_message=str(e),
                campaign_name=campaign_name,
                account_phone=account_phone,
            )
            await metrics.increment(MESSAGES_FAILED)
            # Don't mark_restricted — this is often a topic/permission issue, not permanent
            return False

        except ChatWriteForbiddenError as e:
            # ChatWriteForbiddenError often means banned in this group — skip immediately, don't retry
            await accounts_repo.increment_counters(account_id, failure=1)
            await analytics_repo.log_forward(
                campaign_id=campaign_id,
                account_id=account_id,
                group_id=group_id,
                owner_id=owner_id,
                success=False,
                error_message=str(e),
                campaign_name=campaign_name,
                account_phone=account_phone,
            )
            await metrics.increment(MESSAGES_FAILED)
            # Don't mark permanently restricted — might work from another account
            return False

        except (UserDeactivatedError, AuthKeyUnregisteredError) as e:
            # Account is gone or session revoked
            await log.aerror("forward.account_invalid", account_id=account_id, error=str(e))
            from services import account_service
            await account_service.handle_unauthorized_account(account_id)
            return False

        except TypeNotFoundError as e:
            # Telegram sent a TL object with a constructor ID not recognized
            # by this Telethon version. Log and skip — don't crash or retry.
            await log.awarning(
                "forward.type_not_found",
                account_id=account_id,
                error=str(e),
                attempt=attempt + 1,
            )
            # Wait briefly and retry — often the next attempt succeeds
            if attempt < retries - 1:
                await asyncio.sleep(2 + random.uniform(0, 1))
            else:
                return False

        except Exception as e:
            await accounts_repo.increment_counters(account_id, failure=1)
            await analytics_repo.log_forward(
                campaign_id=campaign_id,
                account_id=account_id,
                group_id=group_id,
                owner_id=owner_id,
                success=False,
                error_message=str(e),
                campaign_name=campaign_name,
                account_phone=account_phone,
            )
            await metrics.increment(MESSAGES_FAILED)
            
            # Detect permanent peer/entity errors and mark as restricted
            err_str = str(e).lower()
            is_permanent = any(keyword in err_str for keyword in [
                "invalid peer", "not found",
                "channel private", "payment required",
                "banned from sending messages",
                "you can't write in this chat",
            ])
            if is_permanent:
                try:
                    from repositories import group_health_repo
                    await group_health_repo.mark_restricted(raw_target, reason=str(e)[:200])
                except Exception:
                    pass
                return False
            
            # Session invalidated from another IP — remove account
            if "wrong session id" in err_str:
                await log.aerror("forward.wrong_session_id", account_id=account_id, error=str(e))
                from services import account_service
                await account_service.handle_unauthorized_account(account_id)
                return False
            
            await log.awarning(
                "forward.error",
                account_id=account_id,
                error=str(e),
                attempt=attempt + 1,
            )
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt + random.uniform(0, 1))
            else:
                return False

    return False


async def forward_to_groups(
    client: Any,
    account_id: str,
    campaign: Any,
    groups: list[dict[str, Any]],
    delay: float = 2.0,
    health_score: int = 100,
) -> dict[str, Any]:
    """
    Forward a message to multiple groups with delay between sends.

    Returns summary stats: {success: int, failed: int, total: int}.
    """
    success = 0
    failed = 0
    skipped = 0

    # Safety: default delay if campaign has None/null
    if delay is None:
        delay = get_settings().default_forward_delay_seconds

    # Dynamic Usage Reduction based on account health
    # Full health (100) -> 1.0x delay
    # Low health (50) -> 2.0x delay
    # Critical health (30) -> 3.3x delay
    health_multiplier = 1.0
    if health_score < 100:
        health_multiplier = max(1.0, 100 / max(health_score, 10))

    # Per-group timeout: one slow/hung group must not kill the whole round
    # (a cancelled round loses already-counted successes). Bounded per send.
    per_group_timeout = max(90.0, float(delay) * health_multiplier + 60.0)

    message_obj = campaign.message
    # If ad_type is forward, resolve the link to get the message to forward
    if getattr(campaign, "ad_type", "custom") == "forward" and getattr(campaign, "forward_link", None):
        try:
            # Parse t.me/channel/123 or t.me/c/12345/123
            link = campaign.forward_link.strip().rstrip("/")
            parts = link.split("/")
            msg_id = int(parts[-1])
            
            if len(parts) >= 3 and parts[-3] == "c":
                # Private channel
                channel_entity = int("-100" + parts[-2])
            else:
                # Public channel
                channel_entity = parts[-2]
            
            # Fetch the message to use it as the source for forward_messages
            message_obj = await client.get_messages(channel_entity, ids=msg_id)
            if not message_obj:
                raise ValueError("Message not found from link")
        except Exception as e:
            await log.aerror("forward.link_resolution_failed", link=getattr(campaign, "forward_link", ""), error=str(e))
            return {"success": 0, "failed": len(groups), "total": len(groups)}

    # Cache campaign name and account phone once (avoid DB lookups per message)
    campaign_name = getattr(campaign, 'name', '') or ''
    account_phone = ''
    try:
        from repositories import accounts_repo as _acc_repo
        _acc = await _acc_repo.get(account_id)
        account_phone = getattr(_acc, 'phone', None) or getattr(_acc, 'phone_number', None) or ''
    except Exception:
        pass

    for group in groups:
        # Check if task was cancelled (campaign paused)
        try:
            await asyncio.sleep(0) # Yield control to check for cancellation
        except asyncio.CancelledError:
            await log.ainfo("forward.cancelled_mid_execution", account_id=account_id)
            raise

        target = group.get("group_id")
        if target is None:
            failed += 1
            continue
        group_id = group.get("_id", str(target))
        topic_id = group.get("topic_id")

        # Check Group Health — Skip Toxic Groups
        from repositories import group_health_repo
        if await group_health_repo.is_toxic(str(target)):
            await log.awarning("forward.skipping_toxic_group", group_id=target)
            skipped += 1
            continue

        try:
            async with asyncio.timeout(per_group_timeout):
                result = await safe_forward(
                    client=client,
                    account_id=account_id,
                    campaign_id=campaign.id,
                    group_id=group_id,
                    owner_id=campaign.owner_id,
                    message=message_obj,
                    target=target,
                    topic_id=topic_id,
                    access_hash=group.get("access_hash", 0),
                    campaign_name=campaign_name,
                    account_phone=account_phone,
                )
        except asyncio.TimeoutError:
            await log.awarning(
                "forward.group_timeout",
                group_id=str(target),
                account_id=account_id,
            )
            result = False
        except asyncio.CancelledError:
            raise

        if result:
            success += 1
        else:
            failed += 1
            
        # Log to Group Health
        try:
            await group_health_repo.log_interaction(str(target), success=result)
        except Exception:
            pass

        # Inter-message delay
        if delay > 0:
            safe_delay = delay * health_multiplier
            # Base delay + random jitter between 0 and 0.2s for human-like pattern
            await asyncio.sleep(safe_delay + random.uniform(0, 0.2))

    return {"success": success, "failed": failed, "skipped": skipped, "total": len(groups)}
