"""
Group data model.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Group(BaseModel):
    """Represents a target Telegram group/channel for forwarding."""

    id: Optional[str] = Field(None, alias="_id")
    owner_id: int                           # Bot user who added this group
    group_id: int                           # Telegram chat/channel ID
    title: str
    username: Optional[str] = None
    topic_id: Optional[int] = None          # Forum topic ID (for topic-based sends)
    is_active: bool = True
    member_count: Optional[int] = None
    added_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"populate_by_name": True}

    @property
    def display_name(self) -> str:
        if self.username:
            return f"@{self.username}"
        return self.title
