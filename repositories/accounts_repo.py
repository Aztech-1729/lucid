"""
Accounts repository — CRUD operations for the accounts collection.

Field names match existing DB schema: name, session, added_at, etc.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from bson import ObjectId

from core.constants import AccountStatus
from database import collections
from database.mongo import get_db
from models.account import Account


def _coll():
    return get_db()[collections.ACCOUNTS]


async def create(
    owner_id: int,
    phone: str,
    session: str,
    name: str = "",
    telegram_id: Optional[int] = None,
) -> Account:
    """Create a new account record (matches existing DB schema)."""
    now = datetime.utcnow()
    doc = {
        "owner_id": owner_id,
        "phone": phone,
        "name": name,
        "session": session,
        "telegram_id": telegram_id,
        "is_forwarding": False,
        "two_fa_password": "",
        "added_at": now,
        "round_num": 0,
        # New fields
        "status": AccountStatus.ACTIVE,
        "health_score": 100,
        "rotation_score": 1.0,
        "flood_wait_history": [],
        "success_count": 0,
        "failure_count": 0,
        "last_used_at": None,
        "next_check_at": now,
        "notes": None,
        "tags": [],
    }
    result = await _coll().insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    return Account.model_validate(doc)


async def get(account_id: str) -> Optional[Account]:
    """Get an account by ID."""
    doc = await _coll().find_one({"_id": ObjectId(account_id)})
    if doc is None:
        return None
    doc["_id"] = str(doc["_id"])
    return Account.model_validate(doc)


async def list_by_owner(owner_id: int) -> list[Account]:
    """Get all accounts for a user."""
    cursor = _coll().find({"owner_id": owner_id}).sort("added_at", -1)
    accounts = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        accounts.append(Account.model_validate(doc))
    return accounts


async def count_by_owner(owner_id: int) -> int:
    """Count accounts owned by a user."""
    return await _coll().count_documents({
        "$or": [
            {"owner_id": int(owner_id)},
            {"owner_id": str(owner_id)},
        ]
    })


async def update_status(account_id: str, status: str) -> bool:
    """Update account status."""
    result = await _coll().update_one(
        {"_id": ObjectId(account_id)},
        {"$set": {"status": status, "updated_at": datetime.utcnow()}},
    )
    return result.modified_count > 0


async def update_health(
    account_id: str,
    health_score: int,
    status: Optional[str] = None,
) -> bool:
    """Update health score and optionally status."""
    update_doc: dict = {
        "health_score": health_score,
        "last_checked_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    if status is not None:
        update_doc["status"] = status
    result = await _coll().update_one(
        {"_id": ObjectId(account_id)},
        {"$set": update_doc},
    )
    return result.modified_count > 0


async def update_name(account_id: str, name: str) -> bool:
    """Update account display name."""
    result = await _coll().update_one(
        {"_id": ObjectId(account_id)},
        {"$set": {"name": name, "updated_at": datetime.utcnow()}},
    )
    return result.modified_count > 0


async def update_rotation_score(account_id: str, score: float) -> bool:
    """Update rotation weight."""
    result = await _coll().update_one(
        {"_id": ObjectId(account_id)},
        {"$set": {"rotation_score": score}},
    )
    return result.modified_count > 0


async def increment_counters(
    account_id: str,
    success: int = 0,
    failure: int = 0,
) -> None:
    """Atomically increment success/failure counters."""
    update_doc: dict = {"$set": {"last_used_at": datetime.utcnow()}}
    inc_doc: dict = {}
    if success:
        inc_doc["success_count"] = success
    if failure:
        inc_doc["failure_count"] = failure
    if inc_doc:
        update_doc["$inc"] = inc_doc
    await _coll().update_one({"_id": ObjectId(account_id)}, update_doc)


async def add_flood_event(account_id: str, seconds: int) -> None:
    """Push a flood event to history."""
    event = {"seconds": seconds, "occurred_at": datetime.utcnow()}
    await _coll().update_one(
        {"_id": ObjectId(account_id)},
        {"$push": {"flood_wait_history": {"$each": [event], "$slice": -50}}},
    )


async def update_notes(account_id: str, notes: str) -> bool:
    """Update account notes."""
    result = await _coll().update_one(
        {"_id": ObjectId(account_id)},
        {"$set": {"notes": notes}},
    )
    return result.modified_count > 0


async def set_forwarding(account_id: str, is_forwarding: bool) -> None:
    """Update the is_forwarding flag."""
    await _coll().update_one(
        {"_id": ObjectId(account_id)},
        {"$set": {"is_forwarding": is_forwarding}},
    )


async def delete(account_id: str) -> bool:
    """Delete an account."""
    result = await _coll().delete_one({"_id": ObjectId(account_id)})
    return result.deleted_count > 0


async def get_all_active() -> list[Account]:
    """Get all active accounts (for workers)."""
    # Old accounts won't have 'status' field, so also include docs without it
    cursor = _coll().find({
        "$or": [
            {"status": AccountStatus.ACTIVE},
            {"status": {"$exists": False}},  # Old accounts without status field
        ]
    })
    accounts = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        accounts.append(Account.model_validate(doc))
    return accounts


async def get_due_for_check(limit: int = 50) -> list[Account]:
    """Get accounts due for a health check, ordered by next_check_at."""
    now = datetime.utcnow()
    cursor = (
        _coll()
        .find({
            "$or": [
                {"next_check_at": {"$lte": now}},
                {"next_check_at": {"$exists": False}},  # Old accounts
            ],
            "status": {"$nin": [AccountStatus.BANNED, AccountStatus.DISABLED]},
        })
        .sort("next_check_at", 1)
        .limit(limit)
    )
    accounts = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        accounts.append(Account.model_validate(doc))
    return accounts


async def set_next_check(account_id: str, next_check_at: datetime) -> None:
    """Set the next health check time for an account."""
    await _coll().update_one(
        {"_id": ObjectId(account_id)},
        {"$set": {"next_check_at": next_check_at}},
    )


async def get_by_phone(owner_id: int, phone: str) -> Optional[Account]:
    """Get an account by exact phone number for a specific owner."""
    doc = await _coll().find_one({
        "$or": [
            {"owner_id": int(owner_id)},
            {"owner_id": str(owner_id)}
        ],
        "phone": phone
    })
    if doc is None:
        return None
    doc["_id"] = str(doc["_id"])
    return Account.model_validate(doc)


async def get_by_telegram_id(owner_id: int, telegram_id: int) -> Optional[Account]:
    """Get an account by exact telegram_id for a specific owner."""
    doc = await _coll().find_one({
        "$or": [
            {"owner_id": int(owner_id)},
            {"owner_id": str(owner_id)}
        ],
        "telegram_id": telegram_id
    })
    if doc is None:
        return None
    doc["_id"] = str(doc["_id"])
    return Account.model_validate(doc)
