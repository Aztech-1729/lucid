"""
Group Health repository — Tracks performance and safety of target groups.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from utils.helpers import now_utc_naive

from database.mongo import get_db
from pymongo import UpdateOne

COLLECTION = "group_health"

def _coll():
    return get_db()[COLLECTION]

async def log_interaction(group_id: str, success: bool, is_flood: bool = False) -> None:
    """Record an interaction with a group and update its health metrics."""
    now = now_utc_naive()
    inc = {
        "total_attempts": 1,
        "success_count": 1 if success else 0,
        "failure_count": 0 if success else 1,
        "flood_count": 1 if is_flood else 0,
    }
    
    await _coll().update_one(
        {"group_id": group_id},
        {
            "$inc": inc,
            "$set": {"last_interaction_at": now},
            "$setOnInsert": {"created_at": now}
        },
        upsert=True
    )

async def mark_restricted(group_id: str, reason: str = "") -> None:
    """Permanently mark a group as restricted (messaging not allowed)."""
    now = now_utc_naive()
    await _coll().update_one(
        {"group_id": group_id},
        {
            "$set": {
                "restricted": True,
                "restricted_reason": reason,
                "restricted_at": now,
            },
            "$setOnInsert": {"created_at": now}
        },
        upsert=True
    )

async def get_health_score(group_id: str) -> int:
    """
    Calculate health score (0-100) for a group.
    
    Factors:
    - Success rate (70%)
    - Flood rate penalty (30%)
    """
    doc = await _coll().find_one({"group_id": group_id})
    if not doc or doc.get("total_attempts", 0) < 30:
        return 100  # Default to safe until we have enough data (min 30 attempts)
        
    total = doc["total_attempts"]
    success_rate = doc["success_count"] / total
    flood_rate = doc["flood_count"] / total
    
    # Calculate score
    # High success = high score
    # Flood penalty max 20% impact (down from 30%)
    base_score = success_rate * 100
    flood_penalty = flood_rate * 100 
    
    final_score = max(0, min(100, round(base_score - flood_penalty)))
    return final_score

async def is_toxic(group_id: str, threshold: int = 15) -> bool:
    """Check if a group is restricted or has a critically low health score."""
    # Fast path: check if group is permanently restricted
    doc = await _coll().find_one({"group_id": group_id})
    if doc and doc.get("restricted"):
        return True
    # Slow path: score-based check
    score = await get_health_score(group_id)
    return score < threshold

async def get_toxic_groups() -> list[str]:
    """Get list of group_ids that are considered toxic."""
    cursor = _coll().find({"total_attempts": {"$gte": 30}})
    toxic = []
    async for doc in cursor:
        score = await get_health_score(doc["group_id"])
        if score < 15:
            toxic.append(doc["group_id"])
    return toxic

