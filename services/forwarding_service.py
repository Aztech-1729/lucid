"""
Forwarding service — Message forwarding orchestration.

Uses ClientPool for all Telegram API calls.
Handles FloodWait, retries, topic support, and result logging.
"""

from __future__ import annotations

import asyncio
import random
from typing import Optional

from telethon.errors import (
    ChatAdminRequiredError,
    ChatWriteForbiddenError,
    FloodWaitError,
    UserBannedInChannelError,
    SlowModeWaitError,
    UserDeactivatedError,
    AuthKeyUnregisteredError,
)
from telethon.errors.common import TypeNotFoundError

from core.config import get_settings
from core.logging import get_logger
from repositories import accounts_repo, analytics_repo
from utils.metrics import FLOOD_WAITS, MESSAGES_FAILED, MESSAGES_SENT, metrics

log = get_logger("forwarding_service")


async def safe_forward(
    client,
    account_id: str,
    campaign_id: str,
    group_id: str,
    owner_id: int,
    message,
    target,
    topic_id: int | None = None,
    access_hash: int = 0,
    retries: int = 3,
) -> bool:
    """
    Forward a message with FloodWait handling and retry logic.

    This is the core forwarding function used by the forwarding worker.
    """
    for attempt in range(retries):
        try:
            sent_msgs = None
            
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
                    except Exception:
                        pass  # Fallback to using the raw ID if all resolution fails

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
                elif hasattr(sent_msgs, 'chat') and getattr(sent_msgs.chat, 'username', None):
                    msg_link = f"https://t.me/{sent_msgs.chat.username}/{sent_msgs.id}"

            # Success
            await accounts_repo.increment_counters(account_id, success=1)
            await analytics_repo.log_forward(
                campaign_id=campaign_id,
                account_id=account_id,
                group_id=group_id,
                owner_id=owner_id,
                success=True,
            )
            await metrics.increment(MESSAGES_SENT)
            
            try:
                from telegram.logs_bot import send_ad_success_log
                from repositories import campaigns_repo, accounts_repo as acc_repo
                camp = await campaigns_repo.get(campaign_id)
                acc = await acc_repo.get(account_id)
                if camp and acc:
                    await send_ad_success_log(owner_id, camp.name, acc.phone, group_id, msg_link)
                else:
                    await log.awarning("forward.log_failed", reason="Campaign or Account not found", campaign_id=campaign_id, account_id=account_id)
            except Exception as e:
                await log.aerror("forward.log_error", error=str(e), account_id=account_id)
                
            return True

        except FloodWaitError as e:
            await metrics.increment(FLOOD_WAITS)
            await accounts_repo.add_flood_event(account_id, e.seconds)
            
            # Log Flood to Group Health
            try:
                from repositories import group_health_repo
                await group_health_repo.log_interaction(str(target), success=False, is_flood=True)
            except:
                pass

            await analytics_repo.log_forward(
                campaign_id=campaign_id,
                account_id=account_id,
                group_id=group_id,
                owner_id=owner_id,
                success=False,
                error_message=f"FloodWait: {e.seconds}s",
                flood_wait_seconds=e.seconds,
            )

            wait_time = e.seconds + random.uniform(1, 5)
            settings = get_settings()
            if wait_time > settings.max_flood_wait_seconds:
                await log.awarning(
                    "forward.flood_wait_too_long_quarantined",
                    account_id=account_id,
                    wait_seconds=e.seconds,
                )
                # Immediately Quarantine Account
                from core.constants import AccountStatus
                await accounts_repo.update_health(account_id, 0, AccountStatus.QUARANTINED)
                
                # Force disconnect from pool to clear any internal flood locks
                from telegram.client_pool import client_pool
                await client_pool.evict(account_id)
                
                # Bubble up exception to stop forwarding for this account this round
                from core.exceptions import AccountQuarantinedError
                raise AccountQuarantinedError(f"Quarantined due to excessive FloodWait ({e.seconds}s)")


            await log.awarning(
                "forward.flood_wait",
                account_id=account_id,
                wait_seconds=round(wait_time, 1),
                attempt=attempt + 1,
            )
            await asyncio.sleep(wait_time)

        except (ChatWriteForbiddenError, UserBannedInChannelError, ChatAdminRequiredError) as e:
            # Permanent failures — don't retry
            await accounts_repo.increment_counters(account_id, failure=1)
            await analytics_repo.log_forward(
                campaign_id=campaign_id,
                account_id=account_id,
                group_id=group_id,
                owner_id=owner_id,
                success=False,
                error_message=str(e),
            )
            await metrics.increment(MESSAGES_FAILED)
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
            )
            await metrics.increment(MESSAGES_FAILED)
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
    client,
    account_id: str,
    campaign,
    groups: list[dict],
    delay: float = 2.0,
    health_score: int = 100,
) -> dict:
    """
    Forward a message to multiple groups with delay between sends.

    Returns summary stats: {success: int, failed: int, total: int}.
    """
    success = 0
    failed = 0

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

    for group in groups:
        # Check if task was cancelled (campaign paused)
        try:
            await asyncio.sleep(0) # Yield control to check for cancellation
        except asyncio.CancelledError:
            await log.ainfo("forward.cancelled_mid_execution", account_id=account_id)
            raise

        target = group.get("group_id")
        group_id = group.get("_id", str(target))
        topic_id = group.get("topic_id")

        # Check Group Health — Skip Toxic Groups
        from repositories import group_health_repo
        if await group_health_repo.is_toxic(str(target)):
            await log.awarning("forward.skipping_toxic_group", group_id=target)
            failed += 1
            continue

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
        )

        if result:
            success += 1
        else:
            failed += 1
            
        # Log to Group Health
        await group_health_repo.log_interaction(str(target), success=result)

        # Inter-message delay
        if delay > 0:
            # Calculate Dynamic Usage Reduction based on account health
            # Full health (100) -> 1.0x delay
            # Low health (50) -> 2.0x delay
            # Critical health (30) -> 3.3x delay
            health_multiplier = 1.0
            if health_score < 100:
                health_multiplier = max(1.0, 100 / max(health_score, 10))
            
            safe_delay = delay * health_multiplier
            # Base delay + random jitter between 0 and 0.2s for human-like pattern
            await asyncio.sleep(safe_delay + random.uniform(0, 0.2))

    return {"success": success, "failed": failed, "total": len(groups)}
