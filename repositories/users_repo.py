"""
Users repository — CRUD operations for the users collection.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from bson import ObjectId

from database import collections
from database.mongo import get_db
from models.user import User

def _coll():

    return get_db()[collections.USERS]


async def get_or_create(
    user_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
) -> User:
    """Get an existing user or create a new one with default plan."""
    doc = await _coll().find_one({"user_id": user_id})
    if doc:
        doc["_id"] = str(doc["_id"])
        return User.model_validate(doc)

    now = datetime.utcnow()
    new_doc = {
        "user_id": user_id,
        "username": username,
        "first_name": first_name,
        "is_admin": False,
        "is_blocked": False,
        "autoreply_enabled": False,
        "autoreply_text": None,
        "created_at": now,
        "updated_at": now,
    }
    result = await _coll().insert_one(new_doc)
    new_doc["_id"] = str(result.inserted_id)
    return User.model_validate(new_doc)


async def get(user_id: int) -> Optional[User]:
    """Get a user by Telegram user ID."""
    doc = await _coll().find_one({"user_id": user_id})
    if doc is None:
        return None
    doc["_id"] = str(doc["_id"])
    return User.model_validate(doc)


async def update(user_id: int, data: dict) -> bool:
    """Update user fields. Returns True if a document was modified."""
    data["updated_at"] = datetime.utcnow()
    result = await _coll().update_one(
        {"user_id": user_id},
        {"$set": data},
    )
    return result.modified_count > 0


async def set_admin(user_id: int, is_admin: bool = True) -> bool:
    """Set or revoke admin status."""
    return await update(user_id, {"is_admin": is_admin})


async def get_all_active_user_ids() -> list[int]:
    """Return all non-blocked user IDs (for cache warming)."""
    cursor = _coll().find(
        {"is_blocked": {"$ne": True}},
        {"user_id": 1, "_id": 0},
    )
    return [doc["user_id"] async for doc in cursor]
