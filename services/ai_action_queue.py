"""
AI Action Queue.

Holds pending DANGEROUS or WRITE actions proposed by the AI in Redis.
These actions require explicit user confirmation via inline buttons before execution.
"""

import json
import uuid
from typing import Optional, Dict, Any

from cache.redis_client import cache_get, cache_set, cache_delete, make_key
from core.constants import RedisKeys

async def enqueue_action(user_id: int, action_data: str) -> Optional[str]:
    """
    Takes the JSON string returned by a dangerous tool, generates a unique ID,
    saves the payload to Redis, and returns the action_id.
    """
    try:
        data = json.loads(action_data)
        if not data.get("_action_request"):
            return None
            
        action_id = str(uuid.uuid4())[:8]
        key = make_key(RedisKeys.AI_ACTION_QUEUE, action_id=action_id)
        
        # Add user_id to the payload to ensure only the owner can confirm it
        data["user_id"] = user_id
        
        # Save to redis, expire in 15 minutes (900 seconds)
        await cache_set(key, data, ttl=900)
        
        return action_id
    except Exception:
        return None
        
async def get_action(action_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a pending action from the queue."""
    key = make_key(RedisKeys.AI_ACTION_QUEUE, action_id=action_id)
    return await cache_get(key)
    
async def clear_action(action_id: str) -> None:
    """Remove a pending action from the queue (after confirm or cancel)."""
    key = make_key(RedisKeys.AI_ACTION_QUEUE, action_id=action_id)
    await cache_delete(key)
