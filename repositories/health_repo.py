"""
Health repository — CRUD operations for the health_records collection.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from bson import ObjectId

from database import collections
from database.mongo import get_db
from models.health import HealthRecord


def _coll():
    return get_db()[collections.HEALTH_RECORDS]


async def insert_record(record: dict) -> HealthRecord:
    """Insert a new health check record."""
    record.setdefault("checked_at", datetime.utcnow())
    result = await _coll().insert_one(record)
    record["_id"] = str(result.inserted_id)
    return HealthRecord.model_validate(record)


async def get_latest(account_id: str) -> Optional[HealthRecord]:
    """Get the most recent health record for an account."""
    doc = await _coll().find_one(
        {"account_id": account_id},
        sort=[("checked_at", -1)],
    )
    if doc is None:
        return None
    doc["_id"] = str(doc["_id"])
    return HealthRecord.model_validate(doc)


async def get_history(account_id: str, limit: int = 20) -> list[HealthRecord]:
    """Get health check history for an account, newest first."""
    cursor = (
        _coll()
        .find({"account_id": account_id})
        .sort("checked_at", -1)
        .limit(limit)
    )
    records = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        records.append(HealthRecord.model_validate(doc))
    return records


async def get_alerts(owner_id: int, limit: int = 10) -> list[HealthRecord]:
    """Get recent health alerts (state changes) for a user's accounts."""
    cursor = (
        _coll()
        .find({
            "owner_id": owner_id,
            "previous_state": {"$ne": None},
        })
        .sort("checked_at", -1)
        .limit(limit)
    )
    records = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        records.append(HealthRecord.model_validate(doc))
    return records


async def count_by_state(owner_id: int) -> dict[str, int]:
    """Count accounts by health state for a user (via latest records)."""
    pipeline = [
        {"$match": {"owner_id": owner_id}},
        {"$sort": {"checked_at": -1}},
        {"$group": {"_id": "$account_id", "state": {"$first": "$state"}}},
        {"$group": {"_id": "$state", "count": {"$sum": 1}}},
    ]
    counts: dict[str, int] = {}
    cursor = await _coll().aggregate(pipeline)
    async for doc in cursor:
        counts[doc["_id"]] = doc["count"]
    return counts


async def cleanup_old_records(days: int = 90) -> int:
    """Delete health records older than N days. Returns deleted count."""
    cutoff = datetime.utcnow()
    from datetime import timedelta
    cutoff = cutoff - timedelta(days=days)
    result = await _coll().delete_many({"checked_at": {"$lt": cutoff}})
    return result.deleted_count


async def delete_by_account(account_id: str) -> int:
    """Delete all health records for an account."""
    result = await _coll().delete_many({"account_id": account_id})
    return result.deleted_count


async def delete_by_owner(owner_id: int) -> int:
    """Delete all health records for a user."""
    result = await _coll().delete_many({"owner_id": owner_id})
    return result.deleted_count
