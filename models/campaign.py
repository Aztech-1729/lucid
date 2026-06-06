"""
Campaign data model and related sub-models.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from core.constants import CampaignStatus


class CampaignSchedule(BaseModel):
    """Defines when a campaign runs."""

    cron_expression: Optional[str] = None       # e.g. "*/30 * * * *"
    interval_seconds: Optional[int] = None      # Alternative: run every N seconds
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    timezone: str = "UTC"


class CampaignStats(BaseModel):
    """Cached statistics for a campaign."""

    total_sent: int = 0
    total_success: int = 0
    total_failed: int = 0
    last_run_at: Optional[datetime] = None
    last_error: Optional[str] = None

    @property
    def success_rate(self) -> float:
        if self.total_sent == 0:
            return 0.0
        return self.total_success / self.total_sent


class Campaign(BaseModel):
    """Represents an advertising campaign."""

    id: Optional[str] = Field(None, alias="_id")
    owner_id: int                               # Telegram user ID
    name: str
    message: str = ""                           # Message content (if ad_type is custom)
    ad_type: str = "custom"                     # "custom" or "forward"
    forward_link: Optional[str] = None          # Link to post (if ad_type is forward)
    source_chat_id: Optional[int] = None        # Chat to forward FROM
    source_message_id: Optional[int] = None     # Message ID to forward
    account_ids: list[str] = Field(default_factory=list)   # Assigned accounts
    group_ids: list[str] = Field(default_factory=list)     # Target groups
    schedule: CampaignSchedule = Field(default_factory=CampaignSchedule)
    status: CampaignStatus = CampaignStatus.DRAFT
    stats: CampaignStats = Field(default_factory=CampaignStats)
    group_delay_seconds: int = 15                   # Delay between sending to groups
    round_delay_seconds: int = 600                  # Delay after one full rotation
    max_rounds: int = 0                             # 0 = infinite/24-7
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"populate_by_name": True}
