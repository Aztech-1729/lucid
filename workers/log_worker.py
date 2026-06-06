"""
Log Worker — Background task to process buffered logs, batch them, and send to the user safely.
"""

import asyncio
import json
import uuid
from typing import Dict, List

from core.logging import get_logger
from services import log_queue
from cache.redis_client import get_redis
from telegram.logs_bot import send_batch_summary

log = get_logger("log_worker")

async def run(stop_event: asyncio.Event = None):
    """
    Infinite loop that pulls logs from the queue every 5 seconds,
    batches them into Redis, and sends a single summary message per campaign.
    """
    log.info("log_worker.started")
    while not (stop_event and stop_event.is_set()):
        try:
            # 1. Pull all logs
            logs_by_owner = await log_queue.extract_all_success_logs()
            
            if logs_by_owner:
                redis = get_redis()
                
                # 2. Process logs per owner
                for owner_id, logs in logs_by_owner.items():
                    # Group by campaign_name
                    campaigns: Dict[str, List[dict]] = {}
                    for entry in logs:
                        c_name = entry["campaign_name"]
                        if c_name not in campaigns:
                            campaigns[c_name] = []
                        campaigns[c_name].append(entry)
                    
                    # 3. Save batch and send summary
                    for c_name, campaign_logs in campaigns.items():
                        batch_id = str(uuid.uuid4())
                        redis_key = f"lucidads:logs_batch:{batch_id}"
                        
                        # Store in Redis for 24 hours (86400 seconds)
                        await redis.setex(
                            redis_key,
                            86400,
                            json.dumps(campaign_logs)
                        )
                        
                        total_count = len(campaign_logs)
                        
                        # Send summary to user
                        try:
                            await send_batch_summary(owner_id, c_name, batch_id, total_count)
                        except Exception as e:
                            log.error("log_worker.send_failed", owner_id=owner_id, error=str(e))
                            
                        # 4. Stagger sends by 0.5s to absolutely ensure we don't hit FloodWait globally
                        await asyncio.sleep(0.5)
                        
        except Exception as e:
            log.error("log_worker.error", error=str(e))
            
        await asyncio.sleep(5.0)
