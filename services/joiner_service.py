"""
Joiner service — Handles automated group joining across accounts.
"""

from __future__ import annotations

import typing
from typing import Any, Callable, Coroutine, cast, Optional
import asyncio
import random
import re
from typing import Dict, List, Optional

from telethon import functions, types
from telethon.errors import (
    FloodWaitError, 
    InviteRequestSentError, 
    UserAlreadyParticipantError,
    ChatWriteForbiddenError
)

from core.logging import get_logger
from core.exceptions import CircuitOpenError
from repositories import accounts_repo, account_groups_repo
from services.flood_guard import flood_remaining, is_flooded, is_limited, mark_flood
from telegram.client_pool import client_pool

log = get_logger("joiner_service")

# Global state to track if joiner is running per user
_active_joiners: Dict[int, asyncio.Task[Any]] = {}

def is_joiner_running(user_id: int) -> bool:
    """Check if an auto-join task is running for a user."""
    task = _active_joiners.get(user_id)
    return task is not None and not task.done()

async def cancel_joiner(user_id: int) -> bool:
    """Cancel a running joiner task."""
    task = _active_joiners.get(user_id)
    if task and not task.done():
        task.cancel()
        return True
    return False

async def start_auto_join(user_id: int, links: List[str], update_callback: Callable[..., Any]) -> None:
    """Start the auto-join background task."""
    if is_joiner_running(user_id):
        return

    task = asyncio.create_task(_run_joiner_task(user_id, links, update_callback))
    _active_joiners[user_id] = task

async def _run_joiner_task(user_id: int, links: List[str], update_callback: Callable[..., Any]) -> None:
    """The background task that executes the joining logic for all accounts in parallel."""
    state: dict[str, Any] = {}
    total_joins: int = 0
    try:
        accounts = await accounts_repo.list_by_owner(user_id)
        if not accounts:
            await update_callback(0, 0, len(links), "❌ No accounts found.")
            return

        total_joins = len(links)
        
        # Auto-split links across accounts (round-robin) so the whole batch is
        # covered in parallel: account i handles links[i::n]. With a single
        # account, all links go to it.
        _n = len(accounts)
        _assigned: Dict[str, List[str]] = {account.id: [ln for ln in links[i::_n]] for i, account in enumerate(accounts)}
        
        state = {
            "joined": 0,
            "failed": 0,
            "lock": asyncio.Lock()
        }
        
        async def _safe_update(joined_inc: int = 0, failed_inc: int = 0, status: str = "Processing") -> None:
            async with state["lock"]:
                state["joined"] += joined_inc
                state["failed"] += failed_inc
                await update_callback(state["joined"], state["failed"], total_joins, status)
                
        async def _account_worker(account: Any) -> None:
            account_id = str(account.id)
            my_links = _assigned[account_id]
            if not my_links:
                return
            # Skip accounts currently in Telegram flood-wait — don't hammer them
            if await is_flooded(account_id):
                remaining = await flood_remaining(account_id)
                await log.ainfo("joiner.skipping_flooded_account", account_id=account_id, wait_seconds=int(remaining))
                await _safe_update(failed_inc=len(my_links))
                return

            # Skip Telegram-limited accounts — joins will fail/risk the limitation
            if await is_limited(account_id):
                await log.ainfo("joiner.skipping_limited_account", account_id=account_id)
                await _safe_update(failed_inc=len(my_links))
                return

            # Cache for entity resolution to avoid duplicate get_entity calls
            entity_cache: Dict[str, Any] = {}
            join_count = 0
            pending_dialogs_refresh = False

            async def refresh_groups():
                nonlocal pending_dialogs_refresh
                try:
                    dialogs = await client.get_dialogs()
                    new_groups = [
                        {"id": d.id, "title": d.title, "is_selected": False}
                        for d in dialogs if d.is_group or d.is_channel
                    ]
                    await account_groups_repo.save_groups(account_id, new_groups)
                    pending_dialogs_refresh = False
                except Exception as e:
                    await log.aerror("joiner.save_groups_failed", account_id=account_id, error=str(e))

            for i, link in enumerate(my_links):
                clean_link = _sanitize_link(link)
                if not clean_link:
                    await _safe_update(failed_inc=1)
                    continue
                
                joined_inc = 0
                failed_inc = 0
                
                try:
                    async with client_pool.acquire(account_id) as client:
                        # Use cached entity if available
                        if clean_link in entity_cache:
                            entity = entity_cache[clean_link]
                        else:
                            entity = await client.get_entity(clean_link)
                            entity_cache[clean_link] = entity
                        
                        is_group = False
                        if isinstance(entity, (types.Chat, types.ChatForbidden)):
                            is_group = True
                        elif isinstance(entity, types.Channel):
                            if not entity.broadcast:
                                is_group = True
                        
                        if not is_group:
                            failed_inc = 1
                        else:
                            await client(functions.channels.JoinChannelRequest(channel=entity))  # type: ignore[arg-type]
                            joined_inc = 1
                            
                            # Batch group refresh - only every 10 joins
                            if (join_count + 1) % 10 == 0:
                                await refresh_groups()
                            else:
                                pending_dialogs_refresh = True
                            join_count += 1
                            
                except UserAlreadyParticipantError:
                    joined_inc = 1
                except (ChatWriteForbiddenError, InviteRequestSentError):
                    joined_inc = 1
                except FloodWaitError as e:
                    # Register the flood and WAIT for it to clear before continuing
                    await mark_flood(account_id, e.seconds)
                    await log.awarning("joiner.flood_wait", seconds=e.seconds, account_id=account_id)
                    # Wait for the flood to clear before continuing to next link
                    await asyncio.sleep(e.seconds + 2)
                    failed_inc = 1
                except CircuitOpenError:
                    await log.ainfo("joiner.skipping_circuit_open", account_id=account_id)
                    # Small delay before next link to allow circuit to potentially recover
                    await asyncio.sleep(5)
                    failed_inc = 1
                except Exception as e:
                    await log.aerror("joiner.error", error=str(e), link=link, account_id=account_id)
                    failed_inc = 1
                
                # Flush pending group refresh at end
                if pending_dialogs_refresh:
                    await refresh_groups()
                
                await _safe_update(joined_inc=joined_inc, failed_inc=failed_inc)
                
                # Adaptive delay - faster with more accounts, minimum 2s
                if i < len(my_links) - 1:
                    base_delay = max(2, 15 // max(1, len(accounts)))  # Faster with more accounts
                    await asyncio.sleep(random.uniform(base_delay, base_delay + 1))

        # Run all account workers concurrently
        tasks = [_account_worker(account) for account in accounts]
        await asyncio.gather(*tasks)
        
        await _safe_update(status="✅ Process Complete")

    except asyncio.CancelledError:
        await log.ainfo("joiner.cancelled", user_id=user_id)
        if state and "lock" in state:
            async with state["lock"]:
                await update_callback(state.get("joined", 0), state.get("failed", 0), total_joins, "🛑 Process Cancelled")
    except Exception as e:
        await log.aerror("joiner.fatal_error", error=str(e))
        if state and "lock" in state:
            async with state["lock"]:
                await update_callback(state.get("joined", 0), state.get("failed", 0), total_joins, f"❌ Error: {str(e)[:20]}")
    finally:
        _active_joiners.pop(user_id, None)

def _sanitize_link(link: str) -> Optional[str]:
    """Extract username or hash from various link formats."""
    link = link.strip()
    if not link:
        return None
    
    # https://t.me/username
    # @username
    # t.me/joinchat/HASH
    
    if link.startswith("@"):
        return link[1:]
    
    match = re.search(r"t\.me/(?:joinchat/|addlist/|(?:\+))?([\w\d\-_]+)", link)
    if match:
        return match.group(1)
        
    return link
