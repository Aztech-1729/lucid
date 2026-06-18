"""
Account Groups repository — handles groups fetched specifically for an account's ad forwarding.
"""

from __future__ import annotations

from database.mongo import get_db
from pymongo import UpdateOne

GROUPS_COL = "account_groups"

def _coll():
    return get_db()[GROUPS_COL]


async def save_groups(account_id: str, groups: list[dict]) -> None:
    """Bulk upsert groups for an account."""
    if not groups:
        return
        
    ops = []
    for g in groups:
        set_doc = {"title": g["title"]}
        if "access_hash" in g:
            set_doc["access_hash"] = g["access_hash"]
            
        ops.append(
            UpdateOne(
                {"account_id": account_id, "group_id": g["id"]},
                {
                    "$set": set_doc,
                    "$setOnInsert": {"is_selected": g.get("is_selected", False)}
                },
                upsert=True
            )
        )
        
    if ops:
        await _coll().bulk_write(ops)


async def sync_groups_from_telegram(account_id: str) -> None:
    """Fetch all groups from Telegram and upsert them, preserving selections."""
    try:
        from telegram.client_pool import client_pool
        async with client_pool.acquire(account_id) as client:
            dialogs = await client.get_dialogs()
            groups = []
            for d in dialogs:
                if d.is_group and not getattr(d.entity, "broadcast", False):
                    access_hash = getattr(d.entity, "access_hash", 0) if d.entity else 0
                    groups.append({
                        "id": d.id, 
                        "title": d.title, 
                        "access_hash": access_hash,
                        "is_selected": False
                    })
            await save_groups(account_id, groups)
            
            # Remove stale groups (like broadcast channels) that were previously synced
            fetched_ids = [g["id"] for g in groups]
            await _coll().delete_many({"account_id": account_id, "group_id": {"$nin": fetched_ids}})
    except Exception as e:
        import logging
        logging.getLogger("account_groups_repo").error(f"Failed to sync groups: {e}")


async def get_groups_paginated(account_id: str, page: int = 1, limit: int = 10) -> tuple[list[dict], dict]:
    """Get groups for an account with pagination."""
    skip = (page - 1) * limit
    
    cursor = _coll().find({"account_id": account_id}).sort("title", 1)
    
    total = await _coll().count_documents({"account_id": account_id})
    items = [doc async for doc in cursor.skip(skip).limit(limit)]
    
    pagination = {
        "page": page,
        "limit": limit,
        "total": total,
        "total_pages": max(1, (total + limit - 1) // limit),
    }
    return items, pagination


async def toggle_group(account_id: str, group_id: int) -> bool:
    """Toggle the selection status of a group. Returns the new status."""
    doc = await _coll().find_one({"account_id": account_id, "group_id": group_id})
    if doc:
        new_status = not doc.get("is_selected", False)
        await _coll().update_one(
            {"_id": doc["_id"]},
            {"$set": {"is_selected": new_status}}
        )
        return new_status
    return False


async def select_all_groups(account_id: str) -> None:
    """Select all groups for an account."""
    await _coll().update_many(
        {"account_id": account_id},
        {"$set": {"is_selected": True}}
    )


async def get_selected_group_ids(account_id: str) -> list[int]:
    """Get all selected group IDs for an account."""
    cursor = _coll().find({"account_id": account_id, "is_selected": True}, {"group_id": 1})
    return [doc["group_id"] async for doc in cursor]


async def count_selected(account_id: str) -> int:
    """Count how many groups are selected."""
    return await _coll().count_documents({"account_id": account_id, "is_selected": True})


async def list_by_ids(object_ids: list[str]) -> list[dict]:
    """Get account groups by their MongoDB ObjectIds."""
    from bson import ObjectId
    oids = []
    for oid in object_ids:
        try:
            oids.append(ObjectId(oid))
        except:
            pass
            
    if not oids:
        return []
        
    cursor = _coll().find({"_id": {"$in": oids}})
    return [doc async for doc in cursor]


async def get_all_group_ids(account_id: str) -> list[str]:
    """Get all ObjectIds (as strings) for groups of an account."""
    cursor = _coll().find({"account_id": account_id}, {"_id": 1})
    return [str(doc["_id"]) async for doc in cursor]


async def delete_by_account(account_id: str) -> bool:
    """Delete all groups belonging to an account."""
    result = await _coll().delete_many({"account_id": account_id})
    return result.deleted_count > 0


async def fetch_groups_if_missing(account_id: str) -> None:
    """Check if groups exist in DB, and if not, fetch them from Telegram."""
    total = await _coll().count_documents({"account_id": account_id})
    if total > 0:
        return
        
    try:
        from telegram.client_pool import client_pool
        async with client_pool.acquire(account_id) as client:
            dialogs = await client.get_dialogs()
            groups = []
            for d in dialogs:
                if d.is_group and not getattr(d.entity, "broadcast", False):
                    access_hash = getattr(d.entity, "access_hash", 0) if d.entity else 0
                    groups.append({
                        "id": d.id, 
                        "title": d.title, 
                        "access_hash": access_hash,
                        "is_selected": False
                    })
            await save_groups(account_id, groups)
    except Exception:
        pass
