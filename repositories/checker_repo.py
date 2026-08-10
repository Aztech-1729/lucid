"""
Checker repository — stores dedicated group-checker accounts (Telethon sessions).

Separate from the accounts collection so checker accounts never appear in the
user's account list, campaigns, or forwarding workers.
"""

from __future__ import annotations

import typing
from typing import Any, Callable, Coroutine, cast, Optional
from typing import Optional

from bson import ObjectId

from database import collections
from database.mongo import get_db
from utils.helpers import now_utc_naive


def _coll():
    return get_db()[collections.CHECKER_ACCOUNTS]


async def add(
    session: str,
    phone: str = "",
    name: str = "",
    telegram_id: Optional[int] = None,
) -> bool:
    """Insert a checker session (idempotent by session string)."""
    existing = await _coll().find_one({"session": session})
    if existing:
        return False
    await _coll().insert_one(
        {
            "session": session,
            "phone": phone,
            "name": name,
            "telegram_id": telegram_id,
            "status": "active",
            "added_at": now_utc_naive(),
            "last_used_at": None,
            "total_checks": 0,
            "flood_until": None,
        }
    )
    return True


async def list_all() -> list[dict[str, Any]]:
    """All checker accounts, oldest first."""
    docs: list[Any] = []
    async for doc in _coll().find().sort("added_at", 1):
        doc["_id"] = str(doc["_id"])
        docs.append(doc)
    return docs


async def count() -> int:
    """Number of stored checker accounts."""
    return await _coll().count_documents({})


async def get_available() -> list[dict[str, Any]]:
    """Checker accounts usable right now (active, not flood-blocked)."""
    now = now_utc_naive()
    docs: list[Any] = []
    cursor = _coll().find(
        {
            "status": "active",
            "$or": [
                {"flood_until": {"$lte": now}},
                {"flood_until": {"$exists": False}},
                {"flood_until": None},
            ],
        }
    )
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        docs.append(doc)
    return docs


async def record_use(checker_id: str, checks: int = 1, flood_until: Any = None) -> None:
    """Update usage stats after using a checker account."""
    doc: dict[str, Any] = {
        "$set": {"last_used_at": now_utc_naive()},
        "$inc": {"total_checks": checks},
    }
    if flood_until is not None:
        doc["$set"]["flood_until"] = flood_until
    await _coll().update_one({"_id": ObjectId(checker_id)}, doc)


async def mark_broken(checker_id: str) -> None:
    """Mark a checker account as no longer usable (revoked session)."""
    await _coll().update_one(
        {"_id": ObjectId(checker_id)},
        {"$set": {"status": "broken", "last_used_at": now_utc_naive()}},
    )


async def delete(checker_id: str) -> bool:
    """Delete a checker account by id."""
    res = await _coll().delete_one({"_id": ObjectId(checker_id)})
    return res.deleted_count > 0