"""
Forwarding Trigger — Signal the worker to run immediately.
"""

from __future__ import annotations

import asyncio

# Global event to wake up the forwarding worker
_trigger = asyncio.Event()

def trigger_forwarding() -> None:
    """Signal the forwarding worker to run a cycle immediately."""
    _trigger.set()

async def wait_for_trigger(timeout: float | None = None) -> bool:
    """
    Wait for the trigger to be set or for the timeout.
    Returns True if triggered, False if timeout.
    """
    try:
        if timeout is not None:
            await asyncio.wait_for(_trigger.wait(), timeout=timeout)
        else:
            await _trigger.wait()
        
        _trigger.clear()
        return True
    except asyncio.TimeoutError:
        return False
