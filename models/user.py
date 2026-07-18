"""
User data model.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from utils.helpers import now_utc_naive

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
    plan_type: str = "NONE"           # NONE, WEEKLY, MONTHLY, YEARLY
    subscription_ends_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=now_utc_naive)
    updated_at: datetime = Field(default_factory=now_utc_naive)

    def is_active(self, admin_user_ids: list[int] = None, admin_username: str = None) -> bool:
        """Check if user has an active subscription or trial. Admins are always active."""
        if admin_user_ids and self.user_id in admin_user_ids:
            return True
        if admin_username and self.username and self.username.lower() == admin_username.lower().replace("@", ""):
            return True
            
        if not self.subscription_ends_at:
            return False
            
        return now_utc_naive() < self.subscription_ends_at

    model_config = {"populate_by_name": True}

