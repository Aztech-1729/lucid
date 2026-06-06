"""
Retry utilities with exponential backoff and FloodWait awareness.
"""

from __future__ import annotations

import asyncio
import functools
import random
from typing import Any, Callable, TypeVar

from telethon.errors import FloodWaitError

from core.logging import get_logger

log = get_logger("retry")

F = TypeVar("F", bound=Callable[..., Any])


def with_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    flood_wait_handler: Callable | None = None,
):
    """
    Decorator for exponential backoff with FloodWait support.

    Args:
        max_attempts: Maximum retry attempts.
        base_delay: Initial delay in seconds.
        max_delay: Maximum delay cap in seconds.
        flood_wait_handler: Optional async callback(account_id, seconds) on FloodWait.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error: Exception | None = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except FloodWaitError as e:
                    wait_seconds = e.seconds + random.uniform(1, 5)
                    await log.awarning(
                        "retry.flood_wait",
                        function=func.__name__,
                        attempt=attempt,
                        wait_seconds=round(wait_seconds, 1),
                    )
                    if flood_wait_handler:
                        try:
                            await flood_wait_handler(kwargs.get("account_id"), e.seconds)
                        except Exception:
                            pass
                    await asyncio.sleep(wait_seconds)
                    last_error = e
                except Exception as e:
                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    jitter = random.uniform(0, delay * 0.1)
                    wait = delay + jitter

                    await log.awarning(
                        "retry.attempt",
                        function=func.__name__,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        delay=round(wait, 2),
                        error=str(e),
                    )
                    last_error = e

                    if attempt < max_attempts:
                        await asyncio.sleep(wait)

            await log.aerror(
                "retry.exhausted",
                function=func.__name__,
                max_attempts=max_attempts,
                error=str(last_error),
            )
            raise last_error  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator


async def safe_sleep(seconds: float, max_sleep: float = 300.0) -> float:
    """
    Sleep for the given seconds, clamped to max_sleep.
    Returns the actual sleep duration.
    """
    actual = min(seconds, max_sleep)
    await asyncio.sleep(actual)
    return actual
