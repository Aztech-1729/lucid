import asyncio
import random
import re
from typing import List, Any
import math

from telethon import functions, types
from telethon.errors import (
    FloodWaitError,
    UserAlreadyParticipantError,
    ChatWriteForbiddenError,
    InviteRequestSentError
)

from core.logging import get_logger
from telegram.client_pool import client_pool
from repositories import accounts_repo
from services import account_service

log = get_logger("factory_worker")

async def run_factory(user_id: int, links: List[str]) -> None:
    """
    Background worker that takes a massive list of links and available burner accounts,
    distributes 200 links to each account, slowly joins them, builds 100-link folders,
    and returns the exported t.me/addlist/... links to the user.
    """
    burners = await accounts_repo.list_burner_accounts(user_id)
    if not burners:
        await _notify(user_id, "❌ Factory Failed: No burner accounts were successfully imported.")
        return

    # Clean the links first to avoid resolving garbage
    clean_links = []
    for link in links:
        match = re.search(r"t\.me/(?:joinchat/|addlist/|(?:\+))?([\w\d\-_]+)", link)
        if match:
            clean_links.append(match.group(1))
            
    if not clean_links:
        await _notify(user_id, "❌ Factory Failed: No valid Telegram links could be parsed.")
        return

    # A burner can hold 2 shared folders max (200 links total).
    links_per_burner = 200
    links_per_folder = 100
    
    # We assign chunks of 200 links to each burner
    tasks = []
    
    for i, burner in enumerate(burners):
        if not burner.id:
            continue
        start_idx = i * links_per_burner
        end_idx = start_idx + links_per_burner
        chunk = clean_links[start_idx:end_idx]
        
        if not chunk:
            break
            
        tasks.append(_process_burner_chunk(user_id, burner.id, chunk, links_per_folder))
        
    await _notify(user_id, f"🏭 Factory is now running {len(tasks)} burner instances in parallel...")
    await asyncio.gather(*tasks, return_exceptions=True)
    
    # Clean up burner accounts when done to not bloat DB
    for burner in burners:
        if burner.id:
            await account_service.delete_account(burner.id, user_id)
        
    await _notify(user_id, "🏁 <b>Addlist Factory Finished!</b>\nAll burners have been deleted and temporary files cleared.")

async def _process_burner_chunk(user_id: int, account_id: str, links: List[str], folder_size: int) -> None:
    """Makes a burner join groups and build folders of size `folder_size`."""
    try:
        async with client_pool.acquire(account_id) as client:
            if not client or not client.is_connected():
                return
                
            folder_count = 1
            current_folder_peers: list[Any] = []
            
            for i, link in enumerate(links):
                try:
                    # 1. Join Group
                    entity = await client.get_entity(link)
                    
                    is_group = False
                    if isinstance(entity, (types.Chat, types.ChatForbidden)):
                        is_group = True
                    elif isinstance(entity, types.Channel):
                        if not getattr(entity, "broadcast", False):
                            is_group = True
                            
                    if is_group:
                        await client(functions.channels.JoinChannelRequest(channel=entity)) # type: ignore
                        current_folder_peers.append(entity)
                        
                except UserAlreadyParticipantError:
                    try:
                        entity = await client.get_entity(link)
                        current_folder_peers.append(entity)
                    except Exception:
                        pass
                except FloodWaitError as e:
                    await log.awarning("factory.flood_wait", account_id=account_id, seconds=e.seconds)
                    await asyncio.sleep(min(e.seconds, 30))
                except Exception as e:
                    await log.aerror("factory.join_error", account_id=account_id, link=link, error=str(e))
                
                # Slowly join (avoid massive instant flood waits)
                await asyncio.sleep(random.uniform(5, 12))
                
                # 2. Package Folder if full OR if it's the last link
                if len(current_folder_peers) >= folder_size or i == len(links) - 1:
                    if current_folder_peers:
                        try:
                            # Use random filter ID between 100-200 to avoid collisions
                            filter_id = random.randint(100, 250)
                            
                            # Create Folder
                            await client(functions.messages.UpdateDialogFilterRequest(
                                id=filter_id,
                                filter=types.DialogFilter(
                                    id=filter_id,
                                    title=types.TextWithEntities(text=f"AutoList {folder_count}", entities=[]),
                                    include_peers=current_folder_peers,
                                    exclude_peers=[],
                                    pinned_peers=[],
                                    contacts=False,
                                    non_contacts=False,
                                    groups=False,
                                    broadcasts=False,
                                    bots=False,
                                    exclude_muted=False,
                                    exclude_read=False,
                                    exclude_archived=False
                                )
                            ))
                            
                            # Export Link
                            result = await client(functions.chatlists.ExportChatlistInviteRequest(
                                chatlist=types.InputChatlistDialogFilter(filter_id=filter_id),
                                title=f"Bulk List {folder_count}",
                                peers=current_folder_peers
                            ))
                            
                            invite = getattr(result, "invite", result)
                            invite_url = getattr(invite, "url", None)
                            
                            if invite_url:
                                await _notify(user_id, f"🎉 <b>New Folder Generated!</b>\n\nLink: <code>{invite_url}</code>\nGroups included: {len(current_folder_peers)}")
                            
                        except Exception as e:
                            await log.aerror("factory.folder_error", account_id=account_id, error=str(e))
                        
                        # Reset for next folder
                        folder_count += 1
                        current_folder_peers: list[Any] = []
                        
    except Exception as e:
        await log.aerror("factory.critical_error", account_id=account_id, error=str(e))

async def _notify(user_id: int, text: str) -> None:
    from telegram.bot import get_bot
    bot = get_bot()
    try:
        await bot.send_message(user_id, text, parse_mode="html")
    except Exception:
        pass
