"""
MongoDB Index Setup
"""

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

        # 5. health_records (collection name per database/collections.py)
        await db.health_records.create_index([("account_id", pymongo.ASCENDING)])
        await db.health_records.create_index([("account_id", pymongo.ASCENDING), ("checked_at", pymongo.DESCENDING)])
        await db.health_records.create_index([("owner_id", pymongo.ASCENDING)])

        # 6. forwarding_logs
        await db.forwarding_logs.create_index([("owner_id", pymongo.ASCENDING)])
        await db.forwarding_logs.create_index([("sent_at", pymongo.DESCENDING)])
        await db.forwarding_logs.create_index([("campaign_id", pymongo.ASCENDING)])

        # 7. analytics_daily
        await db.analytics_daily.create_index([("owner_id", pymongo.ASCENDING)])
        await db.analytics_daily.create_index([("date", pymongo.DESCENDING)])

        # ── owner_id type migration (run once to normalize all collections) ──
        # Existing records may have owner_id as str or int. Run this migration once
        # to convert all to int, then remove the $or: [int, str] fallback from repos.
        try:
            for coll_name in ["accounts", "campaigns", "health_records", "forwarding_logs", "worker_records"]:
                coll = db[coll_name]
                result = await coll.update_many(
                    {"owner_id": {"$type": "string"}},
                    [{"$set": {"owner_id": {"$toInt": "$owner_id"}}}]
                )
                if result.modified_count > 0:
                    await log.ainfo("mongo.migrated_owner_id", collection=coll_name, count=result.modified_count)
        except Exception as mig_err:
            await log.awarning("mongo.owner_id_migration_skipped", error=str(mig_err))

        await log.ainfo("mongo.indexes.setup_complete")
    except Exception as e:
        await log.aerror("mongo.indexes.setup_failed", error=str(e))
