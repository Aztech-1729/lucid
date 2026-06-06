"""
Analytics repository — Forwarding log insertion and aggregation queries.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from bson import ObjectId

from database import collections
from database.mongo import get_db
from models.analytics import AnalyticsDaily, AnalyticsWeekly, ForwardingLog


def _logs():
    return get_db()[collections.FORWARDING_LOGS]


def _daily():
    return get_db()[collections.ANALYTICS_DAILY]


def _weekly():
    return get_db()[collections.ANALYTICS_WEEKLY]


# ── Forwarding Logs ─────────────────────────────────────────

async def log_forward(
    campaign_id: str,
    account_id: str,
    group_id: str,
    owner_id: int,
    success: bool,
    error_message: Optional[str] = None,
    flood_wait_seconds: Optional[int] = None,
) -> None:
    """Insert a forwarding attempt log."""
    doc = {
        "campaign_id": campaign_id,
        "account_id": account_id,
        "group_id": group_id,
        "owner_id": owner_id,
        "success": success,
        "error_message": error_message,
        "flood_wait_seconds": flood_wait_seconds,
        "sent_at": datetime.utcnow(),
    }
    await _logs().insert_one(doc)


async def get_all_time_stats(owner_id: int) -> dict:
    """Get aggregated stats for all time."""
    pipeline = [
        {"$match": {"owner_id": int(owner_id)}},
        {"$group": {
            "_id": None,
            "total_sent": {"$sum": 1},
            "total_success": {"$sum": {"$cond": [{"$eq": ["$success", True]}, 1, 0]}},
            "total_failed": {"$sum": {"$cond": [{"$eq": ["$success", False]}, 1, 0]}},
            "flood_events": {
                "$sum": {"$cond": [{"$and": [{"$ne": ["$flood_wait_seconds", None]}, {"$gt": ["$flood_wait_seconds", 0]}]}, 1, 0]},
            },
            "unique_accounts": {"$addToSet": "$account_id"},
            "unique_campaigns": {"$addToSet": "$campaign_id"},
        }},
    ]
    cursor = await _logs().aggregate(pipeline)
    async for doc in cursor:
        return {
            "total_sent": doc["total_sent"],
            "total_success": doc["total_success"],
            "total_failed": doc["total_failed"],
            "flood_events": doc["flood_events"],
            "active_accounts": len(doc["unique_accounts"]),
            "active_campaigns": len(doc["unique_campaigns"]),
        }
    return {
        "total_sent": 0, "total_success": 0, "total_failed": 0,
        "flood_events": 0, "active_accounts": 0, "active_campaigns": 0,
    }


async def get_daily_stats(owner_id: int, date_str: str) -> dict:
    """Get aggregated stats for a specific day."""
    pipeline = [
        {"$match": {
            "owner_id": int(owner_id),
            "sent_at": {
                "$gte": datetime.strptime(date_str, "%Y%m%d"),
                "$lt": datetime.strptime(date_str, "%Y%m%d") + timedelta(days=1),
            },
        }},
        {"$group": {
            "_id": None,
            "total_sent": {"$sum": 1},
            "total_success": {"$sum": {"$cond": [{"$eq": ["$success", True]}, 1, 0]}},
            "total_failed": {"$sum": {"$cond": [{"$eq": ["$success", False]}, 1, 0]}},
            "flood_events": {
                "$sum": {"$cond": [{"$and": [{"$ne": ["$flood_wait_seconds", None]}, {"$gt": ["$flood_wait_seconds", 0]}]}, 1, 0]},
            },
            "unique_accounts": {"$addToSet": "$account_id"},
            "unique_campaigns": {"$addToSet": "$campaign_id"},
        }},
    ]
    cursor = await _logs().aggregate(pipeline)
    async for doc in cursor:
        return {
            "total_sent": doc["total_sent"],
            "total_success": doc["total_success"],
            "total_failed": doc["total_failed"],
            "flood_events": doc["flood_events"],
            "active_accounts": len(doc["unique_accounts"]),
            "active_campaigns": len(doc["unique_campaigns"]),
        }
    return {
        "total_sent": 0, "total_success": 0, "total_failed": 0,
        "flood_events": 0, "active_accounts": 0, "active_campaigns": 0,
    }


async def get_account_stats(account_id: str, days: int = 30) -> dict:
    """Get aggregated stats for an account over N days."""
    since = datetime.utcnow() - timedelta(days=days)
    pipeline = [
        {"$match": {"account_id": account_id, "sent_at": {"$gte": since}}},
        {"$group": {
            "_id": None,
            "total_sent": {"$sum": 1},
            "total_success": {"$sum": {"$cond": ["$success", 1, 0]}},
            "total_failed": {"$sum": {"$cond": ["$success", 0, 1]}},
            "flood_events": {
                "$sum": {"$cond": [{"$ne": ["$flood_wait_seconds", None]}, 1, 0]},
            },
        }},
    ]
    cursor = await _logs().aggregate(pipeline)
    async for doc in cursor:
        return {
            "total_sent": doc["total_sent"],
            "total_success": doc["total_success"],
            "total_failed": doc["total_failed"],
            "flood_events": doc["flood_events"],
        }
    return {"total_sent": 0, "total_success": 0, "total_failed": 0, "flood_events": 0}


async def get_campaign_stats(campaign_id: str) -> dict:
    """Get aggregated stats for a campaign."""
    pipeline = [
        {"$match": {"campaign_id": campaign_id}},
        {"$group": {
            "_id": None,
            "total_sent": {"$sum": 1},
            "total_success": {"$sum": {"$cond": ["$success", 1, 0]}},
            "total_failed": {"$sum": {"$cond": ["$success", 0, 1]}},
            "unique_groups": {"$addToSet": "$group_id"},
        }},
    ]
    cursor = await _logs().aggregate(pipeline)
    async for doc in cursor:
        return {
            "total_sent": doc["total_sent"],
            "total_success": doc["total_success"],
            "total_failed": doc["total_failed"],
            "unique_groups_reached": len(doc["unique_groups"]),
        }
    return {"total_sent": 0, "total_success": 0, "total_failed": 0, "unique_groups_reached": 0}


async def get_top_accounts(owner_id: int, limit: int = 10) -> list[dict]:
    """Get top performing accounts by success rate."""
    since = datetime.utcnow() - timedelta(days=30)
    pipeline = [
        {"$match": {"owner_id": owner_id, "sent_at": {"$gte": since}}},
        {"$group": {
            "_id": "$account_id",
            "total": {"$sum": 1},
            "success": {"$sum": {"$cond": ["$success", 1, 0]}},
        }},
        {"$addFields": {"rate": {"$divide": ["$success", "$total"]}}},
        {"$sort": {"rate": -1}},
        {"$limit": limit},
    ]
    cursor = await _logs().aggregate(pipeline)
    return [doc async for doc in cursor]


async def get_top_campaigns(owner_id: int, limit: int = 10) -> list[dict]:
    """Get top campaigns by message count."""
    pipeline = [
        {"$match": {"owner_id": owner_id}},
        {"$group": {
            "_id": "$campaign_id",
            "total_sent": {"$sum": 1},
            "success": {"$sum": {"$cond": ["$success", 1, 0]}},
        }},
        {"$sort": {"total_sent": -1}},
        {"$limit": limit},
    ]
    cursor = await _logs().aggregate(pipeline)
    return [doc async for doc in cursor]


# ── Daily / Weekly Rollups ──────────────────────────────────

async def upsert_daily(owner_id: int, date_str: str, data: dict) -> None:
    """Upsert a daily analytics rollup."""
    await _daily().update_one(
        {"owner_id": owner_id, "date": date_str},
        {"$set": {**data, "owner_id": owner_id, "date": date_str}},
        upsert=True,
    )


async def upsert_weekly(owner_id: int, week_str: str, data: dict) -> None:
    """Upsert a weekly analytics rollup."""
    await _weekly().update_one(
        {"owner_id": owner_id, "week": week_str},
        {"$set": {**data, "owner_id": owner_id, "week": week_str}},
        upsert=True,
    )


async def cleanup_old_logs(days: int = 90) -> int:
    """Delete forwarding logs older than N days."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    result = await _logs().delete_many({"sent_at": {"$lt": cutoff}})
    return result.deleted_count
