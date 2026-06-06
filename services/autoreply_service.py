"""
Auto-reply service to handle incoming private messages.
"""

from __future__ import annotations

import asyncio
from telethon import events
from core.logging import get_logger
from repositories import users_repo
from database.mongo import get_db
from database import collections

log = get_logger("autoreply")


async def handle_incoming_message(event: events.NewMessage.Event) -> None:
    """Handle incoming private messages for auto-reply."""
    # Only reply to private user messages (not groups, channels, or bots)
    if not event.is_private:
        return
        
    sender = await event.get_sender()
    if not sender or getattr(sender, 'bot', False):
        return

    client = event.client
    account_id = getattr(client, "account_id", None)
    if not account_id:
        return

    try:
        # Lookup account to find owner
        from repositories import accounts_repo
        account = await accounts_repo.get(account_id)
        if not account:
            return
            
        owner_id = account.owner_id
        if not owner_id:
            return
            
        # Get owner settings
        user = await users_repo.get(owner_id)
        if not user or not user.autoreply_enabled or not user.autoreply_text:
            return

        # Slight delay to look human
        await asyncio.sleep(1.5)
        
        # Send reply
        await event.respond(user.autoreply_text)
        await log.adebug("autoreply.sent", account=str(account_id), to=sender.id)
        
    except Exception as exc:
        await log.aerror("autoreply.error", error=str(exc))


async def ensure_autoreply_clients() -> None:
    """Connect all accounts belonging to users with Auto Reply enabled."""
    db = get_db()
    
    # 1. Find users with autoreply_enabled = True
    cursor = db[collections.USERS].find({"autoreply_enabled": True}, {"user_id": 1})
    user_ids = [doc["user_id"] async for doc in cursor]
    if not user_ids:
        return

    # 2. Find all accounts belonging to these users
    cursor = db[collections.ACCOUNTS].find({"owner_id": {"$in": user_ids}}, {"_id": 1})
    account_ids = [str(doc["_id"]) async for doc in cursor]
    
    if not account_ids:
        return

    from telegram.client_pool import client_pool
    
    # 3. Mark them as keep-alive in the pool and acquire them once to connect
    for acc_id in account_ids:
        client_pool.keep_alive_accounts.add(acc_id)
        try:
            # Acquiring it creates the client, connects it, and adds the event handler
            # because _get_or_create_slot handles the connection and handler attachment.
            async with client_pool.acquire(acc_id) as _:
                pass
        except Exception as exc:
            await log.aerror("autoreply.connect_error", account_id=acc_id, error=str(exc))
            
    await log.ainfo("autoreply.connected", count=len(account_ids))
