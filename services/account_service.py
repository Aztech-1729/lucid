"""
Account service — Account CRUD, validation, and lifecycle management.
"""

from __future__ import annotations

from typing import Optional

from cache import account_cache, dashboard_cache
from core.constants import AccountStatus
from core.exceptions import AccountBannedError, AccountNotFoundError
from core.logging import get_logger
from models.account import Account
from repositories import accounts_repo
from utils.pagination import Paginator

log = get_logger("account_service")


async def add_account(owner_id: int, raw_session: str) -> Account:
    """
    Add a new account for a user.
    """

    # Import via session manager (handles encryption + validation)
    from services.session_manager import import_session
    account = await import_session(owner_id, raw_session)

    # Invalidate caches
    await account_cache.invalidate_list(owner_id)
    await dashboard_cache.invalidate(owner_id)
    from cache import health_cache
    await health_cache.invalidate_summary(owner_id)

    await log.ainfo(
        "account.added",
        account_id=account.id,
        owner_id=owner_id,
    )
    return account


async def get_account(account_id: str) -> Account:
    """Get an account by ID. Raises AccountNotFoundError if not found."""
    account = await accounts_repo.get(account_id)
    if account is None:
        raise AccountNotFoundError(f"Account {account_id} not found")
    return account


async def list_accounts(owner_id: int, page: int = 1) -> tuple[list[Account], Paginator]:
    """List accounts for a user with pagination."""
    accounts = await accounts_repo.list_by_owner(owner_id)
    paginator = Paginator(accounts, page=page)
    return paginator.current_page, paginator


async def pause_account(account_id: str, owner_id: int) -> None:
    """Pause an account (stops it from being used in forwarding)."""
    account = await get_account(account_id)
    if account.owner_id != owner_id:
        raise AccountNotFoundError("Not authorized")

    await accounts_repo.update_status(account_id, AccountStatus.PAUSED)
    await _invalidate_caches(account_id, owner_id)
    await log.ainfo("account.paused", account_id=account_id)


async def resume_account(account_id: str, owner_id: int) -> None:
    """Resume a paused account."""
    account = await get_account(account_id)
    if account.owner_id != owner_id:
        raise AccountNotFoundError("Not authorized")
    if account.status == AccountStatus.BANNED:
        raise AccountBannedError("Cannot resume a banned account")

    await accounts_repo.update_status(account_id, AccountStatus.ACTIVE)
    await _invalidate_caches(account_id, owner_id)
    await log.ainfo("account.resumed", account_id=account_id)


async def delete_account(account_id: str, owner_id: int) -> None:
    """Delete an account and clean up."""
    account = await get_account(account_id)
    if account.owner_id != owner_id:
        raise AccountNotFoundError("Not authorized")

    await accounts_repo.delete(account_id)
    # Also delete associated groups and health records
    from repositories import account_groups_repo, health_repo, campaigns_repo
    
    # Get all group IDs for this account before deleting them
    group_ids = await account_groups_repo.get_all_group_ids(account_id)
    
    await account_groups_repo.delete_by_account(account_id)
    await health_repo.delete_by_account(account_id)
    
    # Clean up campaigns
    await campaigns_repo.remove_account_from_campaigns(account_id, group_ids)
    
    await _invalidate_caches(account_id, owner_id)
    await log.ainfo("account.deleted", account_id=account_id)


async def delete_all_accounts(owner_id: int) -> int:
    """Delete all accounts for a specific user."""
    from repositories import accounts_repo, account_groups_repo, health_repo
    
    # Get all accounts first
    accounts = await accounts_repo.list_by_owner(owner_id)
    count = 0
    for acc in accounts:
        acc_id = str(acc.id)
        
        # Get groups before deleting
        group_ids = await account_groups_repo.get_all_group_ids(acc_id)
        
        await accounts_repo.delete(acc_id)
        await account_groups_repo.delete_by_account(acc_id)
        await account_cache.invalidate_summary(acc_id)
        
        # Clean up campaigns
        from repositories import campaigns_repo
        await campaigns_repo.remove_account_from_campaigns(acc_id, group_ids)
        
        count += 1
        
    await health_repo.delete_by_owner(owner_id)
        
    await account_cache.invalidate_list(owner_id)
    await dashboard_cache.invalidate(owner_id)
    from cache import health_cache
    await health_cache.invalidate_summary(owner_id)
    
    await log.ainfo("account.deleted_all", owner_id=owner_id, count=count)
    return count


async def delete_limited_accounts(owner_id: int) -> int:
    """Delete all accounts with health score below 50."""
    from repositories import accounts_repo, account_groups_repo, health_repo
    
    accounts = await accounts_repo.list_by_owner(owner_id)
    count = 0
    for acc in accounts:
        # Limited status or low health score
        if acc.health_score < 50:
            acc_id = str(acc.id)
            group_ids = await account_groups_repo.get_all_group_ids(acc_id)
            
            await accounts_repo.delete(acc_id)
            await account_groups_repo.delete_by_account(acc_id)
            await health_repo.delete_by_account(acc_id)
            await account_cache.invalidate_summary(acc_id)
            
            from repositories import campaigns_repo
            await campaigns_repo.remove_account_from_campaigns(acc_id, group_ids)
            
            count += 1
            
    await account_cache.invalidate_list(owner_id)
    await dashboard_cache.invalidate(owner_id)
    from cache import health_cache
    await health_cache.invalidate_summary(owner_id)
    
    await log.ainfo("account.deleted_limited", owner_id=owner_id, count=count)
    return count


async def handle_unauthorized_account(account_id: str) -> None:
    """Permanently remove an account that is no longer authorized and notify owner."""
    try:
        from repositories import accounts_repo, account_groups_repo, health_repo
        from services import notification_service
        
        account = await accounts_repo.get(account_id)
        if not account:
            return

        owner_id = account.owner_id
        account_name = account.display_name

        # 1. Delete from DB
        group_ids = await account_groups_repo.get_all_group_ids(account_id)
        
        await accounts_repo.delete(account_id)
        await account_groups_repo.delete_by_account(account_id)
        await health_repo.delete_by_account(account_id)
        
        from repositories import campaigns_repo
        await campaigns_repo.remove_account_from_campaigns(account_id, group_ids)

        # 2. Evict from Pool
        from telegram.client_pool import client_pool
        await client_pool.evict(account_id)

        # 3. Cleanup Caches
        await _invalidate_caches(account_id, owner_id)
        from cache import health_cache
        await health_cache.invalidate_summary(owner_id)

        # 3. Notify User
        await notification_service.notify_account_removed(owner_id, account_name)
        
        await log.ainfo("account.auto_removed", account_id=account_id, owner_id=owner_id, reason="unauthorized")
        
    except Exception as e:
        await log.aerror("account.auto_remove_failed", account_id=account_id, error=str(e))


async def update_notes(account_id: str, owner_id: int, notes: str) -> None:
    """Update notes for an account."""
    account = await get_account(account_id)
    if account.owner_id != owner_id:
        raise AccountNotFoundError("Not authorized")
    await accounts_repo.update_notes(account_id, notes)


async def get_account_count(owner_id: int) -> int:
    """Get the number of accounts owned by a user."""
    return await accounts_repo.count_by_owner(owner_id)


async def _invalidate_caches(account_id: str, owner_id: int) -> None:
    """Invalidate all caches related to an account change."""
    await account_cache.invalidate_summary(account_id)
    await account_cache.invalidate_list(owner_id)
    await dashboard_cache.invalidate(owner_id)
    from cache import health_cache
    await health_cache.invalidate_summary(owner_id)
