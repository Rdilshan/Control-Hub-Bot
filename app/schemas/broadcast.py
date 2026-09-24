"""Broadcast Pydantic Schemas."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict
from app.core.enums import BroadcastStatus


class BroadcastBase(BaseModel):
    client_bot_id: int
    video_id: int
    target_type: str = "ALL_ACTIVE_VIEWERS"


class BroadcastCreate(BroadcastBase):
    created_by_admin_id: Optional[int] = None


class BroadcastRead(BroadcastBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_by_admin_id: Optional[int] = None
    status: BroadcastStatus
    total_targets: int
    sent_count: int
    failed_count: int
    blocked_count: int
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
