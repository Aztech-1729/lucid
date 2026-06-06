"""
Groups repository — CRUD operations for the groups collection.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from bson import ObjectId

from database import collections
from database.mongo import get_db
from models.group import Group


def _coll():
    return get_db()[collections.GROUPS]


async def create(
    owner_id: int,
    group_id: int,
    title: str,
    username: Optional[str] = None,
    topic_id: Optional[int] = None,
) -> Group:
    """Create a new group record."""
    now = datetime.utcnow()
    doc = {
        "owner_id": owner_id,
        "group_id": group_id,
        "title": title,
        "username": username,
        "topic_id": topic_id,
        "is_active": True,
        "member_count": None,
        "added_at": now,
        "updated_at": now,
    }
    result = await _coll().insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    return Group.model_validate(doc)


async def get(group_id_str: str) -> Optional[Group]:
    """Get a group by document ID."""
    doc = await _coll().find_one({"_id": ObjectId(group_id_str)})
    if doc is None:
        return None
    doc["_id"] = str(doc["_id"])
    return Group.model_validate(doc)


async def get_by_telegram_id(group_id: int) -> Optional[Group]:
    """Get a group by Telegram group/chat ID."""
    doc = await _coll().find_one({"group_id": group_id})
    if doc is None:
        return None
    doc["_id"] = str(doc["_id"])
    return Group.model_validate(doc)


async def list_by_owner(owner_id: int) -> list[Group]:
    """Get all groups for a user."""
    cursor = _coll().find({"owner_id": owner_id}).sort("added_at", -1)
    groups = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        groups.append(Group.model_validate(doc))
    return groups


async def list_by_ids(group_ids: list[str]) -> list[Group]:
    """Get groups by a list of document IDs."""
    oids = [ObjectId(gid) for gid in group_ids]
    cursor = _coll().find({"_id": {"$in": oids}})
    groups = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        groups.append(Group.model_validate(doc))
    return groups


async def count_by_owner(owner_id: int) -> int:
    """Count groups owned by a user."""
    return await _coll().count_documents({"owner_id": owner_id})


async def delete(group_id_str: str) -> bool:
    """Delete a group."""
    result = await _coll().delete_one({"_id": ObjectId(group_id_str)})
    return result.deleted_count > 0


async def bulk_upsert(owner_id: int, groups: list[dict]) -> int:
    """Upsert multiple groups. Returns count of upserted/modified docs."""
    if not groups:
        return 0
    from pymongo import UpdateOne

    ops = []
    now = datetime.utcnow()
    for g in groups:
        ops.append(
            UpdateOne(
                {"owner_id": owner_id, "group_id": g["group_id"]},
                {"$set": {**g, "updated_at": now}, "$setOnInsert": {"added_at": now}},
                upsert=True,
            )
        )
    result = await _coll().bulk_write(ops)
    return result.upserted_count + result.modified_count
