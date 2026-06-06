"""
MongoDB connection pool and client singleton.

Uses pymongo.AsyncMongoClient (Motor is deprecated).
"""

from __future__ import annotations

from typing import Optional

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from core.logging import get_logger

log = get_logger("mongo")

# ── Module-level singleton ──────────────────────────────────

_client: Optional[AsyncMongoClient] = None
_db: Optional[AsyncDatabase] = None


async def init_mongo(uri: str, db_name: str) -> None:
    """
    Initialize the MongoDB async client and database reference.

    Must be called once at startup before any repo is used.
    """
    global _client, _db

    _client = AsyncMongoClient(
        uri,
        maxPoolSize=50,
        minPoolSize=10,
        connectTimeoutMS=10_000,
        serverSelectionTimeoutMS=10_000,
        waitQueueTimeoutMS=5_000,
    )

    _db = _client[db_name]

    # Verify connectivity
    await _client.admin.command("ping")
    await log.ainfo("mongo.connected", db=db_name)


async def close_mongo() -> None:
    """Close the MongoDB client and release all connections."""
    global _client, _db

    if _client is not None:
        await _client.close()
        await log.ainfo("mongo.disconnected")
        _client = None
        _db = None


def get_db() -> AsyncDatabase:
    """Return the database instance. Raises if not initialized."""
    if _db is None:
        raise RuntimeError("MongoDB not initialized. Call init_mongo() first.")
    return _db


def get_client() -> AsyncMongoClient:
    """Return the raw client instance. Raises if not initialized."""
    if _client is None:
        raise RuntimeError("MongoDB not initialized. Call init_mongo() first.")
    return _client
