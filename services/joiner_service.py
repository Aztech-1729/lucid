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
        _assigned: Dict[Any, List[str]] = {account: [ln for ln in links[i::_n]] for i, account in enumerate(accounts)}
        
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
            my_links = _assigned[account]
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

            for i, link in enumerate(my_links):
                clean_link = _sanitize_link(link)
                if not clean_link:
                    await _safe_update(failed_inc=1)
                    continue
                
                joined_inc = 0
                failed_inc = 0
                
                try:
                    async with client_pool.acquire(account_id) as client:
                        entity = await client.get_entity(clean_link)
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
                            
                            # Refresh groups
                            dialogs = await client.get_dialogs()
                            new_groups = [
                                {"id": d.id, "title": d.title, "is_selected": False}
                                for d in dialogs if d.is_group or d.is_channel
                            ]
                            await account_groups_repo.save_groups(account_id, new_groups)
                            joined_inc = 1
                            
                except UserAlreadyParticipantError:
                    joined_inc = 1
                except (ChatWriteForbiddenError, InviteRequestSentError):
                    joined_inc = 1
                except FloodWaitError as e:
                    # Register the flood but KEEP trying the remaining links.
                    # A single failure must not stop the whole batch — attempt all links.
                    await mark_flood(account_id, e.seconds)
                    await log.awarning("joiner.flood_wait", seconds=e.seconds, account_id=account_id)
                    failed_inc = 1
                except CircuitOpenError:
                    await log.ainfo("joiner.skipping_circuit_open", account_id=account_id)
                    failed_inc = 1
                except Exception as e:
                    await log.aerror("joiner.error", error=str(e), link=link, account_id=account_id)
                    failed_inc = 1
                
                await _safe_update(joined_inc=joined_inc, failed_inc=failed_inc)
                
                # Delay for each account independently (stay under 200/hour = 18s minimum)
                if i < len(my_links) - 1:
                    await asyncio.sleep(random.uniform(18, 25))

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
