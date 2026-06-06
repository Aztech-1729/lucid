"""
Group Health repository — Tracks performance and safety of target groups.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from database.mongo import get_db
from pymongo import UpdateOne

COLLECTION = "group_health"

def _coll():
    return get_db()[COLLECTION]

async def log_interaction(group_id: str, success: bool, is_flood: bool = False) -> None:
    """Record an interaction with a group and update its health metrics."""
    now = datetime.utcnow()
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

async def get_health_score(group_id: str) -> int:
    """
    Calculate health score (0-100) for a group.
    
    Factors:
    - Success rate (70%)
    - Flood rate penalty (30%)
    """
    doc = await _coll().find_one({"group_id": group_id})
    if not doc or doc.get("total_attempts", 0) < 10:
        return 100 # Default to safe until we have enough data (min 10)
        
    total = doc["total_attempts"]
    success_rate = doc["success_count"] / total
    flood_rate = doc["flood_count"] / total
    
    # Calculate score
    # High success = high score
    # Flood penalty reduced to 150 (max 30% impact)
    base_score = success_rate * 100
    flood_penalty = flood_rate * 150 
    
    final_score = max(0, min(100, round(base_score - flood_penalty)))
    return final_score

async def is_toxic(group_id: str, threshold: int = 30) -> bool:
    """Check if a group should be avoided."""
    score = await get_health_score(group_id)
    return score < threshold

async def get_toxic_groups() -> list[str]:
    """Get list of group_ids that are considered toxic."""
    # This is a bit expensive, so we might want to cache this in Redis later
    cursor = _coll().find({"total_attempts": {"$gte": 10}})
    toxic = []
    async for doc in cursor:
        score = await get_health_score(doc["group_id"])
        if score < 30:
            toxic.append(doc["group_id"])
    return toxic
