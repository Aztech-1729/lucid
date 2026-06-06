"""
Health record data model.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from core.constants import HealthState


class HealthRecord(BaseModel):
    """A single health check result for an account."""

    id: Optional[str] = Field(None, alias="_id")
    account_id: str
    owner_id: int
    state: HealthState = HealthState.UNKNOWN
    score: int = 0                          # 0–100
    spambot_response: Optional[str] = None  # Raw response text from SpamBot
    previous_state: Optional[HealthState] = None
    details: Optional[str] = None           # Human-readable explanation
    checked_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"populate_by_name": True}

    @property
    def state_changed(self) -> bool:
        return self.previous_state is not None and self.previous_state != self.state
