"""
Log Queue service — Buffers logging events to prevent Telegram API FloodWaits.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import TypedDict, Dict, List

class SuccessLogEntry(TypedDict):
    campaign_name: str
    account_phone: str
    group_id: int
    message_link: str

# Queue: owner_id -> list of SuccessLogEntry
_success_logs: Dict[int, List[SuccessLogEntry]] = defaultdict(list)
_lock = asyncio.Lock()

async def add_success_log(owner_id: int, campaign_name: str, account_phone: str, group_id: int, message_link: str) -> None:
    """Safely append a success log to the queue."""
    entry: SuccessLogEntry = {
        "campaign_name": campaign_name,
        "account_phone": account_phone,
        "group_id": group_id,
        "message_link": message_link
    }
    async with _lock:
        _success_logs[owner_id].append(entry)

async def extract_all_success_logs() -> Dict[int, List[SuccessLogEntry]]:
    """Pull all logs out of the queue and clear it."""
    async with _lock:
        if not _success_logs:
            return {}
            
        # Copy and clear
        data = dict(_success_logs)
        _success_logs.clear()
        return data
