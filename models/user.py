"""
User data model.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class User(BaseModel):
    """Represents a bot user in the system."""

    id: Optional[str] = Field(None, alias="_id")
    user_id: int                            # Telegram user ID
    username: Optional[str] = None          # Telegram username (without @)
    first_name: Optional[str] = None
    is_admin: bool = False
    is_blocked: bool = False
    autoreply_enabled: bool = False
    autoreply_text: Optional[str] = None
    health_auto_pause: bool = True
    has_started_logs_bot: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"populate_by_name": True}

