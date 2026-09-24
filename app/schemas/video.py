"""Video Pydantic Schemas."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict
from app.core.enums import VideoStatus


class VideoBase(BaseModel):
    telegram_file_id: str
    telegram_file_unique_id: str
    file_name: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    duration_seconds: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    caption: Optional[str] = None


class VideoCreate(VideoBase):
    client_bot_id: int
    created_by_admin_id: Optional[int] = None
    telegram_message_id: Optional[int] = None
    source_chat_id: Optional[int] = None


class VideoRead(VideoBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_bot_id: int
    created_by_admin_id: Optional[int] = None
    status: VideoStatus
    published_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
