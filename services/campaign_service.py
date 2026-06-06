"""
Campaign service — Campaign lifecycle management.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from cache import campaign_cache, dashboard_cache
from core.constants import CampaignStatus
from core.exceptions import CampaignInactiveError, CampaignNotFoundError
from core.logging import get_logger
from models.campaign import Campaign
from repositories import campaigns_repo
from utils.pagination import Paginator
from utils.validators import sanitize_campaign_name, validate_campaign_name

log = get_logger("campaign_service")


async def create_campaign(
    owner_id: int,
    name: str,
    message: str,
    account_ids: list[str] | None = None,
    group_ids: list[str] | None = None,
) -> Campaign:
    """Create a new campaign (as DRAFT)."""

    # Validate name
    valid, error = validate_campaign_name(name)
    if not valid:
        raise ValueError(error)

    name = sanitize_campaign_name(name)

    # Validate group limits

    campaign = await campaigns_repo.create({
        "owner_id": owner_id,
        "name": name,
        "message": message,
        "account_ids": account_ids or [],
        "group_ids": group_ids or [],
    })

    await _invalidate_caches(owner_id)
    await log.ainfo("campaign.created", campaign_id=campaign.id, name=name)
    return campaign


async def get_campaign(campaign_id: str) -> Campaign:
    """Get a campaign. Raises CampaignNotFoundError if not found."""
    campaign = await campaigns_repo.get(campaign_id)
    if campaign is None:
        raise CampaignNotFoundError(f"Campaign {campaign_id} not found")
    return campaign


async def list_campaigns(owner_id: int, page: int = 1) -> tuple[list[Campaign], Paginator]:
    """List campaigns for a user with pagination."""
    campaigns = await campaigns_repo.list_by_owner(owner_id)
    paginator = Paginator(campaigns, page=page)
    return paginator.current_page, paginator


async def update_campaign(campaign_id: str, **kwargs) -> None:
    """Update arbitrary fields of a campaign."""
    campaign = await get_campaign(campaign_id)
    await campaigns_repo.update_fields(campaign_id, kwargs)
    await _invalidate_caches(campaign.owner_id, campaign_id)
    await log.ainfo("campaign.updated", campaign_id=campaign_id, fields=list(kwargs.keys()))


async def pause_campaign(campaign_id: str, owner_id: int) -> None:
    """Pause an active campaign."""
    campaign = await get_campaign(campaign_id)
    if campaign.owner_id != owner_id:
        raise CampaignNotFoundError("Not authorized")
    if campaign.status != CampaignStatus.ACTIVE:
        raise CampaignInactiveError("Campaign is not active")

    await campaigns_repo.update_status(campaign_id, CampaignStatus.PAUSED)
    
    # Immediately stop background tasks
    from services.task_manager import cancel_campaign_tasks
    await cancel_campaign_tasks(campaign_id)
    
    # Notify via Logs Bot
    try:
        from telegram.logs_bot import send_campaign_pause_log
        await send_campaign_pause_log(owner_id, campaign.name)
    except Exception as e:
        await log.aerror("campaign.pause.log_error", error=str(e))

    await _invalidate_caches(owner_id, campaign_id)
    await log.ainfo("campaign.paused", campaign_id=campaign_id)


async def resume_campaign(campaign_id: str, owner_id: int) -> None:
    """Resume a paused or draft campaign."""
    campaign = await get_campaign(campaign_id)
    if campaign.owner_id != owner_id:
        raise CampaignNotFoundError("Not authorized")
    if campaign.status not in (CampaignStatus.PAUSED, CampaignStatus.DRAFT):
        raise CampaignInactiveError("Campaign cannot be resumed from current state")

    await campaigns_repo.update_status(campaign_id, CampaignStatus.ACTIVE)
    
    # Notify via Logs Bot
    try:
        from telegram.logs_bot import send_campaign_start_log
        await send_campaign_start_log(owner_id, campaign)
    except Exception as e:
        await log.aerror("campaign.start.log_error", error=str(e))

    # Instant Wakeup: Trigger the forwarding worker
    from services.forwarding_trigger import trigger_forwarding
    trigger_forwarding()

    await _invalidate_caches(owner_id, campaign_id)
    await log.ainfo("campaign.resumed", campaign_id=campaign_id)


async def select_all_accounts(campaign_id: str, owner_id: int) -> None:
    """Add all of user's accounts to a campaign with all their groups selected."""
    from repositories import accounts_repo, account_groups_repo, campaigns_repo
    
    # 1. Get all accounts
    accounts = await accounts_repo.list_by_owner(owner_id)
    
    import asyncio
    import random
    
    # 2. Fetch groups sequentially to prevent Telegram anti-spam triggers
    for i, acc in enumerate(accounts):
        try:
            await account_groups_repo.fetch_groups_if_missing(str(acc.id))
        except Exception:
            pass # Skip on error
        if i < len(accounts) - 1:
            await asyncio.sleep(random.uniform(1, 3))
    
    # 3. Build account_ids list and flat group_ids list
    acc_ids = []
    all_group_ids = []
    
    for acc in accounts:
        acc_id_str = str(acc.id)
        acc_ids.append(acc_id_str)
        
        # Get all groups for this account
        group_ids = await account_groups_repo.get_all_group_ids(acc_id_str)
        for gid in group_ids:
            if gid not in all_group_ids:
                all_group_ids.append(gid)
        
    # 4. Update campaign
    await campaigns_repo.update_fields(campaign_id, {
        "account_ids": acc_ids,
        "group_ids": all_group_ids,
        "updated_at": datetime.utcnow()
    })
    
    await _invalidate_caches(owner_id, campaign_id)
    await log.ainfo("campaign.select_all_accounts", campaign_id=campaign_id, acc_count=len(acc_ids), grp_count=len(all_group_ids))

async def unselect_all_accounts(campaign_id: str, owner_id: int) -> None:
    """Remove all accounts and groups from a campaign."""
    from repositories import campaigns_repo
    
    # Empty out accounts and groups
    await campaigns_repo.update_fields(campaign_id, {
        "account_ids": [],
        "group_ids": [],
        "updated_at": datetime.utcnow()
    })
    
    await _invalidate_caches(owner_id, campaign_id)
    await log.ainfo("campaign.unselect_all_accounts", campaign_id=campaign_id)


async def delete_campaign(campaign_id: str, owner_id: int) -> None:
    """Delete a campaign."""
    campaign = await get_campaign(campaign_id)
    if campaign.owner_id != owner_id:
        raise CampaignNotFoundError("Not authorized")

    await campaigns_repo.delete(campaign_id)
    await _invalidate_caches(owner_id, campaign_id)
    await log.ainfo("campaign.deleted", campaign_id=campaign_id)


async def duplicate_campaign(campaign_id: str, owner_id: int, new_name: str) -> Campaign:
    """Duplicate a campaign with a new name."""
    campaign = await get_campaign(campaign_id)
    if campaign.owner_id != owner_id:
        raise CampaignNotFoundError("Not authorized")


    new_campaign = await campaigns_repo.duplicate(campaign_id, new_name)
    if new_campaign is None:
        raise CampaignNotFoundError("Failed to duplicate campaign")

    await _invalidate_caches(owner_id)
    await log.ainfo(
        "campaign.duplicated",
        original_id=campaign_id,
        new_id=new_campaign.id,
    )
    return new_campaign


async def get_campaign_count(owner_id: int) -> int:
    """Get the number of campaigns owned by a user."""
    return await campaigns_repo.count_by_owner(owner_id)


async def _invalidate_caches(
    owner_id: int,
    campaign_id: str | None = None,
) -> None:
    """Invalidate caches on campaign mutation."""
    await campaign_cache.invalidate_list(owner_id)
    await dashboard_cache.invalidate(owner_id)
    if campaign_id:
        await campaign_cache.invalidate_summary(campaign_id)
