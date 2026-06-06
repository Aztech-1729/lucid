"""
Miscellaneous helper functions.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Sequence, TypeVar

T = TypeVar("T")


def generate_id() -> str:
    """Generate a unique string ID."""
    return uuid.uuid4().hex


def now_utc() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(timezone.utc)


def chunk_list(items: Sequence[T], chunk_size: int) -> list[list[T]]:
    """Split a list into chunks of the given size."""
    return [list(items[i : i + chunk_size]) for i in range(0, len(items), chunk_size)]


def safe_json_loads(raw: str | bytes | None) -> Any | None:
    """Parse JSON safely, returning None on failure."""
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def safe_int(value: Any, default: int = 0) -> int:
    """Convert to int safely, returning default on failure."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp a value between min and max."""
    return max(min_val, min(value, max_val))


def ellipsis_id(oid: str, length: int = 8) -> str:
    """Shorten an ObjectId for display: 'abc12345...'."""
    if len(oid) <= length:
        return oid
    return oid[:length] + "…"
