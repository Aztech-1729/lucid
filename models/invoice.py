from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class Invoice(BaseModel):
    """Tracks a payment invoice for a user plan."""
    order_id: str = Field(..., description="Unique order ID")
    user_id: int = Field(..., description="Telegram User ID")
    plan: str = Field(..., description="Plan type (WEEKLY, MONTHLY)")
    amount: str = Field(..., description="Amount charged (e.g., '25')")
    gateway: str = Field(..., description="Payment gateway (ZAPUPI or OXAPAY)")
    status: str = Field(default="pending", description="Status (pending, paid, cancelled)")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    paid_at: Optional[datetime] = None
