"""
Joiner service — Handles automated group joining across accounts.
"""

from __future__ import annotations

import asyncio
import random
import re
from typing import Dict, List, Optional

from telethon import TelegramClient, functions, types
from telethon.errors import (
    FloodWaitError, 
    InviteRequestSentError, 
    UserAlreadyParticipantError,
    ChatWriteForbiddenError
)

from core.logging import get_logger
from repositories import accounts_repo, account_groups_repo
from telegram.client_pool import client_pool

log = get_logger("joiner_service")

# Global state to track if joiner is running per user
_active_joiners: Dict[int, asyncio.Task] = {}

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

async def start_auto_join(user_id: int, links: List[str], update_callback) -> None:
    """Start the auto-join background task."""
    if is_joiner_running(user_id):
        return

    task = asyncio.create_task(_run_joiner_task(user_id, links, update_callback))
    _active_joiners[user_id] = task

async def _run_joiner_task(user_id: int, links: List[str], update_callback) -> None:
    """The background task that executes the joining logic for all accounts in parallel."""
    try:
        accounts = await accounts_repo.list_by_owner(user_id)
        if not accounts:
            await update_callback(0, 0, len(links), "❌ No accounts found.")
            return

        total_joins = len(accounts) * len(links)
        
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
                
        async def _account_worker(account) -> None:
            account_id = str(account.id)
            for i, link in enumerate(links):
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
                            await client(functions.channels.JoinChannelRequest(channel=entity))
                            
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
                    await log.awarning("joiner.flood_wait", seconds=e.seconds)
                    failed_inc = 1
                    await asyncio.sleep(min(e.seconds, 10))
                except Exception as e:
                    await log.aerror("joiner.error", error=str(e), link=link)
                    failed_inc = 1
                
                await _safe_update(joined_inc=joined_inc, failed_inc=failed_inc)
                
                # Delay for each account independently (stay under 200/hour = 18s minimum)
                if i < len(links) - 1:
                    await asyncio.sleep(random.uniform(18, 25))

        # Run all account workers concurrently
        tasks = [_account_worker(account) for account in accounts]
        await asyncio.gather(*tasks)
        
        await _safe_update(status="✅ Process Complete")

    except asyncio.CancelledError:
        await log.ainfo("joiner.cancelled", user_id=user_id)
        if 'state' in locals():
            async with state["lock"]:
                await update_callback(state["joined"], state["failed"], total_joins, "🛑 Process Cancelled")
    except Exception as e:
        await log.aerror("joiner.fatal_error", error=str(e))
        if 'state' in locals():
            async with state["lock"]:
                await update_callback(state["joined"], state["failed"], total_joins, f"❌ Error: {str(e)[:20]}")
    finally:
        _active_joiners.pop(user_id, None)

def _sanitize_link(link: str) -> Optional[str]:
    """Extract username or hash from various link formats."""
    link = link.strip()
    if not link: return None
    
    # https://t.me/username
    # @username
    # t.me/joinchat/HASH
    
    if link.startswith("@"):
        return link[1:]
    
    match = re.search(r"t\.me/(?:joinchat/|addlist/|(?:\+))?([\w\d\-_]+)", link)
    if match:
        return match.group(1)
        
    return link
