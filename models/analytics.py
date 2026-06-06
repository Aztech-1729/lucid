"""
Analytics data models.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ForwardingLog(BaseModel):
    """A single forwarding attempt record."""

    id: Optional[str] = Field(None, alias="_id")
    campaign_id: str
    account_id: str
    group_id: str
    owner_id: int
    success: bool
    error_message: Optional[str] = None
    flood_wait_seconds: Optional[int] = None
    sent_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"populate_by_name": True}


class AccountStats(BaseModel):
    """Per-account aggregated statistics."""

    account_id: str
    total_sent: int = 0
    total_success: int = 0
    total_failed: int = 0
    flood_events: int = 0
    success_rate: float = 0.0


class CampaignAnalytics(BaseModel):
    """Per-campaign aggregated statistics."""

    campaign_id: str
    total_sent: int = 0
    total_success: int = 0
    total_failed: int = 0
    unique_groups_reached: int = 0
    success_rate: float = 0.0


class AnalyticsDaily(BaseModel):
    """Daily analytics rollup."""

    id: Optional[str] = Field(None, alias="_id")
    date: str                               # YYYYMMDD
    owner_id: int
    total_sent: int = 0
    total_success: int = 0
    total_failed: int = 0
    flood_events: int = 0
    active_accounts: int = 0
    active_campaigns: int = 0
    top_account_id: Optional[str] = None
    top_campaign_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"populate_by_name": True}

    @property
    def success_rate(self) -> float:
        if self.total_sent == 0:
            return 0.0
        return self.total_success / self.total_sent


class AnalyticsWeekly(BaseModel):
    """Weekly analytics rollup."""

    id: Optional[str] = Field(None, alias="_id")
    week: str                               # YYYYWW
    owner_id: int
    total_sent: int = 0
    total_success: int = 0
    total_failed: int = 0
    flood_events: int = 0
    active_accounts: int = 0
    active_campaigns: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"populate_by_name": True}

    @property
    def success_rate(self) -> float:
        if self.total_sent == 0:
            return 0.0
        return self.total_success / self.total_sent
