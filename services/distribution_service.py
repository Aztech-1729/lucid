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
    
    results = {}
    from bson import ObjectId
    
    # 3. Fetch all campaigns
    campaigns = await campaigns_repo.list_by_owner(user_id)
    if not campaigns:
        return {}
    
    # Process each campaign independently
    for c in campaigns:
        if not c.id or not c.account_ids:
            continue
            
        c_id = str(c.id)
        
        # 1. Fetch account_groups ONLY for the accounts in this campaign
        cursor = account_groups_repo._coll().find({"account_id": {"$in": c.account_ids}})
        camp_docs = [doc async for doc in cursor]
        
        # 2. Group by Telegram group_id
        unique_groups: dict[int, list[dict[str, Any]]] = {}
        for doc in camp_docs:
            gid = doc.get("group_id")
            if gid:
                unique_groups.setdefault(gid, []).append(doc)
                
        # 3. Distribute these unique groups evenly among the accounts in this campaign
        account_counts: dict[str, int] = {acc_id: 0 for acc_id in c.account_ids}
        new_group_ids: list[str] = []
        
        for gid, docs in unique_groups.items():
            valid_options = []
            for doc in docs:
                acc_id = doc.get("account_id")
                if acc_id in c.account_ids:
                    valid_options.append((acc_id, doc))
                    
            if not valid_options:
                continue
                
            # Pick the account in this campaign with the fewest groups assigned so far
            random.shuffle(valid_options)
            best_option = min(valid_options, key=lambda opt: account_counts[opt[0]])
            
            acc_id, chosen_doc = best_option
            new_group_ids.append(str(chosen_doc["_id"]))
            account_counts[acc_id] += 1
            
        # 4. Save to campaign
        await campaigns_repo._coll().update_one(
            {"_id": ObjectId(c.id)},
            {"$set": {"group_ids": new_group_ids}}
        )
        results[c.name] = len(new_group_ids)
        
    from services.campaign_service import _invalidate_caches
    await _invalidate_caches(user_id)
        
    await log.ainfo("distribution.completed", user_id=user_id, total_unique=len(unique_groups), distributions=results)
    return results
