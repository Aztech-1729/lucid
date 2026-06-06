"""
Account data model and related sub-models.

Field names match the existing MongoDB schema:
  _id, owner_id, phone, name, session, is_forwarding, two_fa_password, added_at, round_num

New fields (status, health_score, etc.) have defaults so old docs load cleanly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from core.constants import AccountStatus


class FloodEvent(BaseModel):
    """Records a single FloodWait event."""

    seconds: int                            # Duration Telegram requested
    occurred_at: datetime = Field(default_factory=datetime.utcnow)


class Account(BaseModel):
    """Represents a managed Telegram account."""

    # ── Fields matching existing DB schema ───────────────────
    id: Optional[str] = Field(None, alias="_id")
    owner_id: int                           # Telegram user ID of the owner
    phone: str = ""
    name: str = ""                          # Display name (was 'Leopay001' etc.)
    session: str = ""                       # Fernet-encrypted session string
    is_forwarding: bool = False             # Currently forwarding?
    two_fa_password: str = ""               # 2FA password if set
    added_at: datetime = Field(default_factory=datetime.utcnow)
    round_num: int = 0                      # Forwarding round counter
    telegram_id: Optional[int] = None       # Telegram User ID

    # ── New fields (defaults so old docs load cleanly) ───────
    status: str = AccountStatus.ACTIVE
    health_score: int = 100                 # 0–100
    rotation_score: float = 1.0             # Computed by rotation_service
    flood_wait_history: list[FloodEvent] = Field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0
    last_used_at: Optional[datetime] = None
    last_checked_at: Optional[datetime] = None
    next_check_at: Optional[datetime] = None
    notes: Optional[str] = None
    tags: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

    @property
    def total_operations(self) -> int:
        return self.success_count + self.failure_count

    @property
    def success_rate(self) -> float:
        if self.total_operations == 0:
            return 0.0
        return self.success_count / self.total_operations

    @property
    def display_name(self) -> str:
        """Human-readable name — uses the 'name' field from DB."""
        if self.name:
            return self.name
        return self.phone or "Unknown"

    @property
    def created_at(self) -> datetime:
        """Alias for added_at for backward compat in services."""
        return self.added_at
