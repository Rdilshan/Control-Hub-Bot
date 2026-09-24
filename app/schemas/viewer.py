"""Viewer Pydantic Schemas."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict
from app.core.enums import ViewerStatus


class ViewerBase(BaseModel):
    telegram_user_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    language_code: Optional[str] = None


class ViewerCreate(ViewerBase):
    client_bot_id: int


class ViewerRead(ViewerBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_bot_id: int
    status: ViewerStatus
    first_started_at: datetime
    last_started_at: datetime
    last_seen_at: datetime
    blocked_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
