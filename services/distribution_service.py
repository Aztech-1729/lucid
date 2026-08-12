"""
Distribution service — Automatically distributes Telegram groups across campaigns and accounts
to completely eliminate redundant forwards and toxic flags.
"""

from __future__ import annotations

import typing
from typing import Any
import random

from core.logging import get_logger
from repositories import accounts_repo, campaigns_repo, account_groups_repo

log = get_logger("distribution_service")


async def auto_distribute_all_groups(user_id: int) -> dict[str, int]:
    """
    Distribute all available groups across all campaigns for a user.
    Ensures that a specific Telegram group ID is only assigned to ONE account in ONE campaign.
    
    Returns a dict mapping campaign names to the number of groups assigned.
    """
    # 1. Fetch all accounts for user
    accounts = await accounts_repo.list_by_owner(user_id)
    if not accounts:
        return {}
    
    account_ids = [str(acc.id) for acc in accounts if acc.id]
    
    # 2. Fetch all account_groups for these accounts
    cursor = account_groups_repo._coll().find({"account_id": {"$in": account_ids}})
    all_docs = [doc async for doc in cursor]
    
    # Group by Telegram group_id
    unique_groups: dict[int, list[dict[str, Any]]] = {}
    for doc in all_docs:
        gid = doc.get("group_id")
        if gid:
            unique_groups.setdefault(gid, []).append(doc)
            
    # 3. Fetch all campaigns
    campaigns = await campaigns_repo.list_by_owner(user_id)
    if not campaigns:
        return {}
        
    campaign_assignments: dict[str, list[str]] = {str(c.id): [] for c in campaigns if c.id}
    campaign_counts: dict[str, int] = {str(c.id): 0 for c in campaigns if c.id}
    
    # 4. Distribute
    for gid, docs in unique_groups.items():
        valid_options: list[tuple[str, dict[str, Any]]] = []
        
        for c in campaigns:
            if not c.id:
                continue
            c_id = str(c.id)
            # Find docs that belong to an account assigned to this campaign
            for doc in docs:
                if doc.get("account_id") in c.account_ids:
                    valid_options.append((c_id, doc))
                    
        if not valid_options:
            continue
            
        # Pick the campaign that currently has the fewest groups
        # To handle ties fairly, we shuffle valid_options first
        random.shuffle(valid_options)
        best_option = min(valid_options, key=lambda opt: campaign_counts[opt[0]])
        
        c_id, chosen_doc = best_option
        campaign_assignments[c_id].append(str(chosen_doc["_id"]))
        campaign_counts[c_id] += 1
        
    # 5. Save updates
    results = {}
    from bson import ObjectId
    for c in campaigns:
        if not c.id:
            continue
        c_id = str(c.id)
        new_groups = campaign_assignments[c_id]
        
        await campaigns_repo._coll().update_one(
            {"_id": ObjectId(c.id)},
            {"$set": {"group_ids": new_groups}}
        )
        results[c.name] = len(new_groups)
        
    from services.campaign_service import _invalidate_caches
    await _invalidate_caches(user_id)
        
    await log.ainfo("distribution.completed", user_id=user_id, total_unique=len(unique_groups), distributions=results)
    return results
