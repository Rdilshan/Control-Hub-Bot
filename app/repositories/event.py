"""Bot Event Repository."""

from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import BotEventType
from app.core.utils import utc_now
from app.db.models.bot_event import BotEvent
from app.repositories.base import BaseRepository


class BotEventRepository(BaseRepository[BotEvent]):
    def __init__(self, session: AsyncSession):
        super().__init__(BotEvent, session)

    async def record_event(
        self,
        client_bot_id: int,
        event_type: BotEventType,
        telegram_user_id: Optional[int] = None,
        related_video_id: Optional[int] = None,
        related_broadcast_id: Optional[int] = None,
        metadata_json: Optional[Dict[str, Any]] = None,
    ) -> BotEvent:
        event = BotEvent(
            client_bot_id=client_bot_id,
            event_type=event_type,
            telegram_user_id=telegram_user_id,
            related_video_id=related_video_id,
            related_broadcast_id=related_broadcast_id,
            metadata_json=metadata_json or {},
            created_at=utc_now(),
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def list_by_bot(
        self,
        client_bot_id: int,
        limit: int = 50,
        offset: int = 0,
    ) -> List[BotEvent]:
        stmt = (
            select(BotEvent)
            .where(BotEvent.client_bot_id == client_bot_id)
            .order_by(BotEvent.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
