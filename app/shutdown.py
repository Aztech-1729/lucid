"""
Graceful shutdown handler.

Stops all systems in reverse startup order to ensure clean teardown.
"""

from __future__ import annotations

from core.logging import get_logger

log = get_logger("shutdown")


async def shutdown() -> None:
    """
    Execute graceful shutdown in reverse startup order.

    Order:
    1. Stop bot
    2. Stop workers
    3. Drain client pool
    4. Close Redis
    5. Close MongoDB
    """
    await log.ainfo("shutdown.begin")

    # 1. Stop bots
    try:
        from telegram.bot import stop_bot
        from telegram.logs_bot import get_logs_bot
        await stop_bot()
        logs_bot = get_logs_bot()
        if logs_bot:
            await logs_bot.disconnect()
        await log.ainfo("shutdown.bots_stopped")
    except Exception as exc:
        await log.awarning("shutdown.bots_error", error=str(exc))

    # 2. Stop workers
    try:
        from workers.scheduler_worker import worker_manager
        await worker_manager.stop_all()
        await log.ainfo("shutdown.workers_stopped")
    except Exception as exc:
        await log.awarning("shutdown.workers_error", error=str(exc))

    # 3. Drain client pool
    try:
        from telegram.client_pool import client_pool
        await client_pool.stop()
        await log.ainfo("shutdown.pool_drained")
    except Exception as exc:
        await log.awarning("shutdown.pool_error", error=str(exc))

    # 4. Close Redis
    try:
        from cache.redis_client import close_redis
        await close_redis()
        await log.ainfo("shutdown.redis_closed")
    except Exception as exc:
        await log.awarning("shutdown.redis_error", error=str(exc))

    # 5. Close MongoDB
    try:
        from database.mongo import close_mongo
        await close_mongo()
        await log.ainfo("shutdown.mongo_closed")
    except Exception as exc:
        await log.awarning("shutdown.mongo_error", error=str(exc))

    await log.ainfo("shutdown.complete", status="Clean shutdown ✅")
