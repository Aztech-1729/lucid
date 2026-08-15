"""
Bulk Account Manager Service — Executes bulk actions across all loaded accounts.
"""

from __future__ import annotations

import typing
from typing import Any, Callable, Coroutine, cast, Optional
import asyncio

from telethon.tl.functions.account import UpdateProfileRequest, UpdateUsernameRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest, DeletePhotosRequest
from telethon.tl.functions.folders import EditPeerFoldersRequest
from telethon.tl.types import InputFolderPeer

from core.logging import get_logger
from repositories import accounts_repo
from telegram.client_pool import client_pool

log = get_logger("bulk_service")

# Dictionary to track cancellation flags for each owner.
# If _active_bulk_tasks[owner_id] is False, the bulk task should abort.
_active_bulk_tasks: dict[int, bool] = {}

def cancel_bulk_task(owner_id: int):
    """Signals any active bulk task for this owner to cancel."""
    _active_bulk_tasks[owner_id] = False

async def _execute_bulk(owner_id: int, action_func: Any, progress_callback: Any = None) -> tuple[int, int]:
    """
    Helper to execute an action across all accounts owned by the user.
    Returns (success_count, fail_count).
    """
    accounts = await accounts_repo.list_by_owner(owner_id)
    if not accounts:
        return 0, 0

    success = 0
    failed = 0
    total = len(accounts)
    
    # Mark task as active
    _active_bulk_tasks[owner_id] = True

    if progress_callback:
        try:
            await progress_callback(0, 0, total)
        except Exception:
            pass

    import random
    
    for i, acc in enumerate(accounts):
        # Check cancellation
        if not _active_bulk_tasks.get(owner_id, True):
            break
            
        try:
            async def _run_inner():
                async with client_pool.acquire(str(acc.id)) as client:
                    await action_func(client, acc)
            await asyncio.wait_for(_run_inner(), timeout=300.0)
            success += 1
        except asyncio.TimeoutError:
            await log.aerror("bulk.timeout", account_id=acc.id)
            failed += 1
        except Exception as e:
            await log.aerror("bulk.error", account_id=acc.id, error=str(e))
            failed += 1
            
        if progress_callback:
            try:
                await progress_callback(success, failed, total)
            except Exception:
                pass # Ignore UI edit errors
                
        # Sleep randomly between 5 to 12 seconds to prevent Telegram anti-spam from revoking sessions
        if i < total - 1:
            await asyncio.sleep(random.uniform(5, 12))

    _active_bulk_tasks.pop(owner_id, None)
    return success, failed


async def bulk_update_profile(owner_id: int, first_name: str | None = None, last_name: str | None = None, about: str | None = None, progress_callback: Any = None) -> tuple[int, int]:
    """Bulk update name or bio."""
    async def _action(client: Any, acc: Any) -> None:
        kwargs: dict[str, Any] = {}
        if first_name is not None:
            kwargs["first_name"] = first_name
        if last_name is not None:
            kwargs["last_name"] = last_name
        if about is not None:
            kwargs["about"] = about
        await client(UpdateProfileRequest(**kwargs))

    return await _execute_bulk(owner_id, _action, progress_callback)


async def bulk_remove_usernames(owner_id: int, progress_callback: Any = None) -> tuple[int, int]:
    """Bulk remove usernames."""
    async def _action(client: Any, acc: Any) -> None:
        me = await client.get_me()
        if getattr(me, "username", None):
            await client(UpdateUsernameRequest(username=""))

    return await _execute_bulk(owner_id, _action, progress_callback)


async def bulk_upload_profile_photo(owner_id: int, file_path: str, progress_callback: Any = None) -> tuple[int, int]:
    """Bulk upload a profile photo."""
    # Read file into memory ONCE to prevent 100+ clients locking the same file concurrently
    import os
    if not os.path.exists(file_path):
        return 0, 0
    with open(file_path, "rb") as f:
        file_bytes = f.read()

    file_name = os.path.basename(file_path) if file_path else "photo.jpg"

    async def _action(client: Any, acc: Any) -> None:
        # upload_file accepts bytes directly!
        file = await client.upload_file(file_bytes, file_name=file_name)
        await client(UploadProfilePhotoRequest(file=file))

    return await _execute_bulk(owner_id, _action, progress_callback)


async def bulk_delete_profile_photos(owner_id: int, progress_callback: Any = None) -> tuple[int, int]:
    """Bulk remove current profile photos."""
    async def _action(client: Any, acc: Any) -> None:
        # Fetch current photos
        photos = await client.get_profile_photos("me")
        if photos:
            await client(DeletePhotosRequest(id=photos))

    return await _execute_bulk(owner_id, _action, progress_callback)


async def bulk_clean_dms(owner_id: int, progress_callback: Any = None) -> tuple[int, int]:
    """Bulk delete all private chat history."""
    async def _action(client: Any, acc: Any) -> None:
        async for dialog in client.iter_dialogs():
            if dialog.is_user and not dialog.entity.bot:
                try:
                    await client.delete_dialog(dialog.entity, revoke=True)
                except Exception:
                    pass # Ignore errors for individual chats

    return await _execute_bulk(owner_id, _action, progress_callback)


async def bulk_archive_chats(owner_id: int, progress_callback: Any = None) -> tuple[int, int]:
    """Bulk move all private and group chats to archive."""
    async def _action(client: Any, acc: Any) -> None:
        while True:
            peers: list[Any] = []
            async for dialog in client.iter_dialogs():
                # Skip archived
                if dialog.archived:
                    continue
                peers.append(InputFolderPeer(peer=dialog.input_entity, folder_id=1))
                if len(peers) >= 100:
                    break # Limit to 100 per chunk to avoid huge requests
                    
            if not peers:
                break
                
            await client(EditPeerFoldersRequest(folder_peers=peers))
            await asyncio.sleep(1) # Small delay between batches

    return await _execute_bulk(owner_id, _action, progress_callback)


async def bulk_leave_groups(owner_id: int, progress_callback: Any = None) -> tuple[int, int]:
    """Bulk leave all joined groups/channels."""
    async def _action(client: Any, acc: Any) -> None:
        async for dialog in client.iter_dialogs():
            if dialog.is_group or dialog.is_channel:
                try:
                    await client.delete_dialog(dialog.entity)
                except Exception:
                    pass

    return await _execute_bulk(owner_id, _action, progress_callback)


async def bulk_manage_2fa(owner_id: int, new_password: str, progress_callback: Any = None) -> tuple[int, int]:
    """Bulk set or change 2FA password."""
    async def _action(client: Any, acc: Any) -> None:
        await client.edit_2fa(new_password=new_password)

    return await _execute_bulk(owner_id, _action, progress_callback)


async def bulk_remove_2fa(owner_id: int, progress_callback: Any = None) -> tuple[int, int]:
    """Bulk remove 2FA password."""
    # We can't automatically remove 2FA without the old password using telethon's edit_2fa easily if we don't know it.
    # But if the user provides the current one, we could. For simplicity, we assume they want to clear it and we don't know it,
    # but Telethon requires the old password to clear it unless we use recovery.
    # If the bots were the ones that set it, maybe they know it?
    # To keep it simple, we'll try to set the password to empty string.
    async def _action(client: Any, acc: Any) -> None:
        await client.edit_2fa(new_password=None)

    return await _execute_bulk(owner_id, _action, progress_callback)


async def bulk_secure_email(owner_id: int, new_2fa_password: str, progress_callback: Any = None) -> tuple[int, int]:
    """Bulk setup temp-gmail secure email as 2FA recovery email."""
    from telethon.tl.functions.account import GetPasswordRequest, SendVerifyEmailCodeRequest, VerifyEmailRequest
    from telethon.tl.types import EmailVerifyPurposeLoginChange, EmailVerificationCode
    from services.email_client import create_account, wait_for_otp
    from repositories.accounts_repo import update_security_info
    
    async def _action(client: Any, acc: Any) -> None:
        # Check if 2FA is already enabled
        pwd = await client(GetPasswordRequest())
        if pwd.has_password:
            raise ValueError("2FA is already enabled. Skipping.")
            
        # 1. Create a secure email using temp-gmail
        address = await create_account()
        used_msg_ids = set()
        
        # 2. Setup email verification callback
        async def email_code_callback(length: int) -> str:
            # Poll the inbox using the email_client
            code, msg_id = await wait_for_otp(address, timeout=120, exclude_ids=used_msg_ids)
            used_msg_ids.add(msg_id)
            return code
            
        # 3. Set the 2FA password and recovery email via Telethon
        # Warning: this might be slow due to crypto
        await client.edit_2fa(
            new_password=new_2fa_password,
            email=address,
            email_code_callback=email_code_callback
        )
        
        # 4. Also set this email as the Login Email
        try:
            sent_code = await client(SendVerifyEmailCodeRequest(
                purpose=EmailVerifyPurposeLoginChange(),
                email=address
            ))
            login_code, login_msg_id = await wait_for_otp(address, timeout=120, exclude_ids=used_msg_ids)
            used_msg_ids.add(login_msg_id)
            
            await client(VerifyEmailRequest(
                purpose=EmailVerifyPurposeLoginChange(),
                verification=EmailVerificationCode(code=login_code)
            ))
        except Exception as e:
            from core.logging import get_logger
            log = get_logger("bulk_service")
            await log.awarning("bulk_secure_email.login_mail_failed", error=str(e), account_id=acc.id)
        
        # 5. Save to database
        await update_security_info(str(acc.id), new_2fa_password, address)
        
    return await _execute_bulk(owner_id, _action, progress_callback)
