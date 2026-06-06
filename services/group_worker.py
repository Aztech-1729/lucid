"""
Group worker — handles folder actions and bulk joining logic.
"""

from __future__ import annotations

import asyncio
from typing import Callable, Coroutine, List

from telethon import functions, types
from core.logging import get_logger
from repositories import accounts_repo
from telegram.client_pool import client_pool
from services.joiner_service import start_auto_join

log = get_logger("group_worker")

async def bulk_remove_folders(user_id: int, progress_callback: Callable[[int, int, int], Coroutine]) -> tuple[int, int]:
    """
    Remove all custom dialog filters (chat folders) from all accounts.
    """
    accounts = await accounts_repo.list_by_owner(user_id)
    if not accounts:
        return 0, 0
        
    total_accounts = len(accounts)
    success = 0
    failed = 0
    
    await progress_callback(0, 0, total_accounts)
    
    for account in accounts:
        try:
            async with client_pool.acquire(account.id) as client:
                if not client or not client.is_connected():
                    failed += 1
                    await progress_callback(success, failed, total_accounts)
                    continue
                
                # Fetch all existing dialog filters
                result = await client(functions.messages.GetDialogFiltersRequest())
                
                # Delete all custom filters
                for f in result.filters:
                    if isinstance(f, types.DialogFilterDefault) or not hasattr(f, 'id'):
                        continue  # Skip Default filter and any unexpected filter without ID
                    await client(functions.messages.UpdateDialogFilterRequest(
                        id=f.id,
                        filter=None  # Setting to None deletes the folder
                    ))
                    
                success += 1
        except Exception as e:
            log.warning("rm_folders_failed", account_id=account.id, error=str(e))
            failed += 1
            
        await progress_callback(success, failed, total_accounts)
        
    return success, failed


async def bulk_join_folder(user_id: int, slug: str, progress_callback: Callable[[str], Coroutine]) -> None:
    """
    Instantly join a chat folder for all connected accounts, then delete the folder.
    """
    accounts = await accounts_repo.list_by_owner(user_id)
    if not accounts:
        await progress_callback("❌ No accounts connected.")
        return
        
    total_accounts = len(accounts)
    success = 0
    failed = 0
    from telegram.menus import render_autojoin_progress
    await progress_callback(render_autojoin_progress(0, 0, total_accounts, "Joining folder...", 0, total_accounts))
    
    for account in accounts:
        try:
            async with client_pool.acquire(account.id) as client:
                if not client or not client.is_connected():
                    await progress_callback(render_autojoin_progress(success, failed, total_accounts, "Processing", 0, total_accounts))
                    continue
                
                # 1. Check the invite link to get the peers
                invite = await client(functions.chatlists.CheckChatlistInviteRequest(slug=slug))
                
                # 2. Join the chatlist if not already joined
                if not isinstance(invite, types.chatlists.ChatlistInviteAlready):
                    peers_to_join = getattr(invite, 'peers', [])
                    if peers_to_join:
                        # Instantly join all groups in the folder
                        await client(functions.chatlists.JoinChatlistInviteRequest(
                            slug=slug,
                            peers=peers_to_join
                        ))
                
                # 3. Clean up the folder interface immediately
                result = await client(functions.messages.GetDialogFiltersRequest())
                for f in result.filters:
                    if isinstance(f, types.DialogFilterDefault) or not hasattr(f, 'id'): continue
                    await client(functions.messages.UpdateDialogFilterRequest(id=f.id, filter=None))
                    
                success += 1
        except Exception as e:
            log.warning("bulk_join_folder_failed", account_id=account.id, error=str(e))
            failed += 1
            
        await progress_callback(render_autojoin_progress(success, failed, total_accounts, "Processing", 0, total_accounts))
        
    await progress_callback(render_autojoin_progress(success, failed, total_accounts, "✅ Folder joined completely!", 0, total_accounts))


async def bulk_join_links(user_id: int, links: List[str], progress_callback: Callable[[str], Coroutine]) -> None:
    """
    Wrapper for joining links via txt file using the existing auto-join service.
    """
    accounts = await accounts_repo.list_by_owner(user_id)
    if not accounts:
        await progress_callback("❌ No accounts connected.")
        return
        
    total_joins = len(accounts) * len(links)
    
    async def legacy_callback(joined: int, failed: int, total: int, status: str = "Processing") -> None:
        from telegram.menus import render_autojoin_progress
        text = render_autojoin_progress(
            joined=joined, 
            failed=failed, 
            total=total_joins, 
            status=status,
            groups_count=len(links),
            accounts_count=len(accounts)
        )
        await progress_callback(text)

    await start_auto_join(user_id, links, legacy_callback)

