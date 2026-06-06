"""
Campaigns repository — CRUD operations for the campaigns collection.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from bson import ObjectId

from core.constants import CampaignStatus
from database import collections
from database.mongo import get_db
from models.campaign import Campaign


def _coll():
    return get_db()[collections.CAMPAIGNS]


async def create(data: dict) -> Campaign:
    """Create a new campaign."""
    owner_id = data.get("owner_id")
    name = data.get("name")
    
    if owner_id and name:
        import re
        existing = await _coll().find_one({
            "owner_id": owner_id,
            "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}
        })
        if existing:
            raise ValueError(f"You already have a campaign named '{existing['name']}'. Please choose a different name.")

    now = datetime.utcnow()
    data.setdefault("status", CampaignStatus.DRAFT)
    data.setdefault("stats", {})
    data.setdefault("created_at", now)
    data.setdefault("updated_at", now)
    result = await _coll().insert_one(data)
    data["_id"] = str(result.inserted_id)
    return Campaign.model_validate(data)


async def get(campaign_id: str) -> Optional[Campaign]:
    """Get a campaign by ID."""
    doc = await _coll().find_one({"_id": ObjectId(campaign_id)})
    if doc is None:
        return None
    doc["_id"] = str(doc["_id"])
    return Campaign.model_validate(doc)


async def list_by_owner(owner_id: int) -> list[Campaign]:
    """Get all campaigns for a user."""
    cursor = _coll().find({
        "$or": [
            {"owner_id": int(owner_id)},
            {"owner_id": str(owner_id)},
        ]
    }).sort("created_at", -1)
    campaigns = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        campaigns.append(Campaign.model_validate(doc))
    return campaigns


async def count_by_owner(owner_id: int) -> int:
    """Count campaigns owned by a user."""
    return await _coll().count_documents({"owner_id": owner_id})


async def get_active() -> list[Campaign]:
    """Get all active campaigns (for forwarding worker)."""
    cursor = _coll().find({"status": CampaignStatus.ACTIVE})
    campaigns = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        campaigns.append(Campaign.model_validate(doc))
    return campaigns


async def update_status(campaign_id: str, status: CampaignStatus) -> bool:
    """Update campaign status."""
    result = await _coll().update_one(
        {"_id": ObjectId(campaign_id)},
        {"$set": {"status": status, "updated_at": datetime.utcnow()}},
    )
    return result.modified_count > 0


async def update_stats(campaign_id: str, stats: dict) -> bool:
    """Update cached campaign stats."""
    result = await _coll().update_one(
        {"_id": ObjectId(campaign_id)},
        {"$set": {"stats": stats, "updated_at": datetime.utcnow()}},
    )
    return result.modified_count > 0


async def update_fields(campaign_id: str, data: dict) -> bool:
    """Update arbitrary campaign fields."""
    data["updated_at"] = datetime.utcnow()
    result = await _coll().update_one(
        {"_id": ObjectId(campaign_id)},
        {"$set": data},
    )
    return result.modified_count > 0


async def delete(campaign_id: str) -> bool:
    """Delete a campaign."""
    result = await _coll().delete_one({"_id": ObjectId(campaign_id)})
    return result.deleted_count > 0


async def duplicate(campaign_id: str, new_name: str) -> Optional[Campaign]:
    """Duplicate a campaign with a new name. Returns new campaign or None."""
    original = await get(campaign_id)
    if original is None:
        return None
    now = datetime.utcnow()
    new_doc = original.model_dump(by_alias=False, exclude={"id"})
    new_doc["name"] = new_name
    new_doc["status"] = CampaignStatus.DRAFT
    new_doc["stats"] = {}
    new_doc["created_at"] = now
    new_doc["updated_at"] = now
    return await create(new_doc)


async def remove_account_from_campaigns(account_id: str, group_ids: list[str]) -> bool:
    """Remove an account and its specific groups from all campaigns."""
    result = await _coll().update_many(
        {},
        {
            "$pull": {
                "account_ids": account_id,
                "group_ids": {"$in": group_ids}
            }
        }
    )
    return result.modified_count > 0
