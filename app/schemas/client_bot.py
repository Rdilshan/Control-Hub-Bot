"""Client Bot Pydantic Schemas."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict
from app.core.enums import ClientBotStatus


class ClientBotCreate(BaseModel):
    token: str
    username: Optional[str] = None
    display_name: Optional[str] = None


class ClientBotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_id: int
    telegram_bot_id: int
    username: Optional[str] = None
    display_name: Optional[str] = None
    status: ClientBotStatus
    connected_at: datetime
    paused_at: Optional[datetime] = None
    disconnected_at: Optional[datetime] = None
    last_verified_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
