"""
Ordered startup sequence.

Each step depends on the previous one. No worker starts before
MongoDB and Redis are ready. No bot starts before workers are running.
"""

from __future__ import annotations

from core.config import get_settings
from core.logging import get_logger, setup_logging
from database.indexes import apply_indexes
from database.mongo import init_mongo
from cache.redis_client import init_redis

log = get_logger("startup")


async def startup() -> None:
    """
    Execute the ordered startup sequence.

    Order:
    1. Load settings & configure logging
    2. Connect to MongoDB + apply indexes
    3. Connect to Redis + verify ping
    4. Initialize client pool
    5. Pre-warm critical caches
    6. Launch all background workers
    7. Connect Telegram bot
    """
    # 1. Load settings & logging
    settings = get_settings()
    setup_logging(log_level=settings.log_level, log_format=settings.log_format)
    await log.ainfo("startup.begin")

    # 2. MongoDB
    await log.ainfo("startup.mongo_connecting")
    await init_mongo(settings.mongo_uri, settings.mongo_db)
    await apply_indexes()
    await log.ainfo("startup.mongo_ready")

    # 3. Redis
    await log.ainfo("startup.redis_connecting")
    await init_redis(settings.redis_uri, settings.redis_prefix)
    await log.ainfo("startup.redis_ready")

    # 4. Client pool
    await log.ainfo("startup.pool_init")
    from telegram.client_pool import client_pool
    await client_pool.start()
    await log.ainfo("startup.pool_ready")

    # 5. Pre-warm caches
    await log.ainfo("startup.cache_warming")
    try:
        from workers.cache_worker import run_cache_cycle
        await run_cache_cycle()
        await log.ainfo("startup.cache_warmed")
    except Exception as exc:
        await log.awarning("startup.cache_warm_failed", error=str(exc))
    
    await log.ainfo("startup.autoreply_connecting")
    from services.autoreply_service import ensure_autoreply_clients
    await ensure_autoreply_clients()
    await log.ainfo("startup.autoreply_ready")

    # 6. Launch workers
    await log.ainfo("startup.workers_launching")
    from workers.scheduler_worker import worker_manager
    await worker_manager.start_all()
    await log.ainfo("startup.workers_running")

    # 7. Start bot
    await log.ainfo("startup.bot_connecting")
    try:
        from telegram.bot import init_bot
        from telegram.logs_bot import init_logs_bot
        await init_bot()
        await init_logs_bot()
        await log.ainfo("startup.bot_ready")
    except Exception as e:
        await log.aerror("startup.bot_failed", error=str(e))
        raise

    await log.ainfo("startup.complete", status="ALL SYSTEMS GO 🚀")
