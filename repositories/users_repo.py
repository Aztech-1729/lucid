"""
Users repository — CRUD operations for the users collection.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from utils.helpers import now_utc_naive

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
        if doc.get("username") != username or doc.get("first_name") != first_name:
            await _coll().update_one(
                {"user_id": user_id},
                {"$set": {"username": username, "first_name": first_name}}
            )
            doc["username"] = username
            doc["first_name"] = first_name
        doc["_id"] = str(doc["_id"])
        return User.model_validate(doc)

    now = now_utc_naive()
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
    data["updated_at"] = now_utc_naive()
    result = await _coll().update_one(
        {"user_id": user_id},
        {"$set": data},
    )
    return result.matched_count > 0


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


async def get_stats() -> dict:
    """Return stats for the Admin panel."""
    total_users = await _coll().count_documents({})
    now = now_utc_naive()
    active_subs = await _coll().count_documents({"subscription_ends_at": {"$gt": now}})
    return {
        "total_users": total_users,
        "active_subscriptions": active_subs
    }

async def get_active_subscribers() -> list[User]:
    """Return a list of all users with active subscriptions."""
    now = now_utc_naive()
    cursor = _coll().find({"subscription_ends_at": {"$gt": now}})
    users = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        users.append(User.model_validate(doc))
    return users
