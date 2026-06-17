"""
MongoDB Index Setup
"""

from typing import Any
from pymongo.asynchronous.database import AsyncDatabase
import pymongo
from core.logging import get_logger

log = get_logger("mongo.indexes")


async def setup_indexes(db: AsyncDatabase) -> None:
    """
    Create necessary indexes for performance.
    """
    try:
        # 1. users
        await db.users.create_index([("user_id", pymongo.ASCENDING)], unique=True)
        await db.users.create_index([("subscription_ends_at", pymongo.ASCENDING)])

        # 2. accounts
        await db.accounts.create_index([("owner_id", pymongo.ASCENDING)])
        await db.accounts.create_index([("phone", pymongo.ASCENDING)])
        await db.accounts.create_index([("is_active", pymongo.ASCENDING)])

        # 3. campaigns
        await db.campaigns.create_index([("owner_id", pymongo.ASCENDING)])
        await db.campaigns.create_index([("status", pymongo.ASCENDING)])

        # 4. account_groups
        await db.account_groups.create_index([("account_id", pymongo.ASCENDING)])
        await db.account_groups.create_index([("account_id", pymongo.ASCENDING), ("group_id", pymongo.ASCENDING)], unique=True)

        # 5. health & group_health
        await db.health.create_index([("account_id", pymongo.ASCENDING)], unique=True)
        await db.group_health.create_index([("group_id", pymongo.ASCENDING)], unique=True)

        # 6. analytics
        await db.analytics.create_index([("owner_id", pymongo.ASCENDING)])
        await db.analytics.create_index([("date", pymongo.DESCENDING)])

        await log.ainfo("mongo.indexes.setup_complete")
    except Exception as e:
        await log.aerror("mongo.indexes.setup_failed", error=str(e))
