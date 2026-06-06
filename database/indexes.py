"""
MongoDB index definitions, auto-applied on startup.

All indexes use background creation to avoid blocking operations.
"""

from __future__ import annotations

from pymongo import ASCENDING, DESCENDING

from core.logging import get_logger
from database import collections
from database.mongo import get_db

log = get_logger("indexes")

# Index definitions: (collection_name, index_keys, optional kwargs)
INDEX_DEFINITIONS: list[tuple[str, list[tuple[str, int]], dict]] = [
    # ── users ───────────────────────────────────────────────
    (collections.USERS, [("user_id", ASCENDING)], {"unique": True}),

    # ── accounts ────────────────────────────────────────────
    (collections.ACCOUNTS, [("owner_id", ASCENDING)], {}),
    (collections.ACCOUNTS, [("status", ASCENDING)], {}),
    (collections.ACCOUNTS, [("health_score", ASCENDING)], {}),
    (collections.ACCOUNTS, [("next_check_at", ASCENDING)], {}),

    # ── groups ──────────────────────────────────────────────
    (collections.GROUPS, [("owner_id", ASCENDING)], {}),
    (collections.GROUPS, [("group_id", ASCENDING)], {}),

    # ── campaigns ───────────────────────────────────────────
    (collections.CAMPAIGNS, [("owner_id", ASCENDING)], {}),
    (collections.CAMPAIGNS, [("status", ASCENDING)], {}),

    # ── health_records ──────────────────────────────────────
    (collections.HEALTH_RECORDS, [("account_id", ASCENDING), ("checked_at", DESCENDING)], {}),
    (collections.HEALTH_RECORDS, [("owner_id", ASCENDING)], {}),

    # ── forwarding_logs ─────────────────────────────────────
    (collections.FORWARDING_LOGS, [("campaign_id", ASCENDING), ("sent_at", DESCENDING)], {}),
    (collections.FORWARDING_LOGS, [("account_id", ASCENDING), ("sent_at", DESCENDING)], {}),
    (collections.FORWARDING_LOGS, [("owner_id", ASCENDING), ("sent_at", DESCENDING)], {}),

    # ── analytics_daily ─────────────────────────────────────
    (collections.ANALYTICS_DAILY, [("date", ASCENDING)], {}),
    (collections.ANALYTICS_DAILY, [("owner_id", ASCENDING), ("date", DESCENDING)], {}),

    # ── analytics_weekly ────────────────────────────────────
    (collections.ANALYTICS_WEEKLY, [("week", ASCENDING)], {}),
    (collections.ANALYTICS_WEEKLY, [("owner_id", ASCENDING), ("week", DESCENDING)], {}),

    # ── worker_records ──────────────────────────────────────
    (collections.WORKER_RECORDS, [("worker_id", ASCENDING)], {}),
]


async def apply_indexes() -> None:
    """Create all indexes. Safe to call multiple times (idempotent)."""
    db = get_db()
    created = 0

    for coll_name, keys, kwargs in INDEX_DEFINITIONS:
        collection = db[coll_name]
        try:
            await collection.create_index(keys, **kwargs)
            created += 1
        except Exception as exc:
            await log.awarning(
                "index.create_failed",
                collection=coll_name,
                keys=str(keys),
                error=str(exc),
            )

    await log.ainfo("indexes.applied", count=created)
