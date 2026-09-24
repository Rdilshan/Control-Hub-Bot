"""Viewer Repository with strict bot isolation."""

from datetime import datetime
from typing import List, Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import BotEventType, ViewerStatus
from app.core.utils import utc_now
from app.db.models.bot_event import BotEvent
from app.db.models.client_bot import ClientBot
from app.db.models.viewer import Viewer
from app.repositories.base import BaseRepository


class ViewerRepository(BaseRepository[Viewer]):
    def __init__(self, session: AsyncSession):
        super().__init__(Viewer, session)

    async def get_by_bot_and_telegram_user(
        self,
        client_bot_id: int,
        telegram_user_id: int,
    ) -> Optional[Viewer]:
        stmt = select(Viewer).where(
            Viewer.client_bot_id == client_bot_id,
            Viewer.telegram_user_id == telegram_user_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create_viewer(
        self,
        client_bot_id: int,
        telegram_user_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        language_code: Optional[str] = None,
    ) -> tuple[Viewer, bool]:
        """Gets existing viewer or creates new. Returns (viewer, is_new)."""
        existing = await self.get_by_bot_and_telegram_user(client_bot_id, telegram_user_id)
        if existing:
            existing.last_started_at = utc_now()
            existing.last_seen_at = utc_now()
            if existing.status == ViewerStatus.BLOCKED:
                existing.status = ViewerStatus.ACTIVE
                existing.blocked_at = None
            if username:
                existing.username = username
            if first_name:
                existing.first_name = first_name
            if last_name:
                existing.last_name = last_name
            if language_code:
                existing.language_code = language_code
            await self.session.flush()
            return existing, False

        now = utc_now()
        new_viewer = Viewer(
            client_bot_id=client_bot_id,
            telegram_user_id=telegram_user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            language_code=language_code,
            status=ViewerStatus.ACTIVE,
            first_started_at=now,
            last_started_at=now,
            last_seen_at=now,
        )
        self.session.add(new_viewer)

        # Log viewer started event
        event = BotEvent(
            client_bot_id=client_bot_id,
            event_type=BotEventType.VIEWER_STARTED,
            telegram_user_id=telegram_user_id,
            metadata_json={"username": username},
        )
        self.session.add(event)

        await self.session.flush()
        return new_viewer, True

    async def mark_blocked(self, client_bot_id: int, telegram_user_id: int) -> Optional[Viewer]:
        viewer = await self.get_by_bot_and_telegram_user(client_bot_id, telegram_user_id)
        if viewer:
            viewer.status = ViewerStatus.BLOCKED
            viewer.blocked_at = utc_now()
            await self.session.flush()
        return viewer

    async def list_active_viewers(
        self,
        client_bot_id: int,
        limit: int = 500,
        offset: int = 0,
    ) -> List[Viewer]:
        stmt = (
            select(Viewer)
            .where(
                Viewer.client_bot_id == client_bot_id,
                Viewer.status == ViewerStatus.ACTIVE,
            )
            .order_by(Viewer.id.asc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_bot(self, client_bot_id: int, status: Optional[ViewerStatus] = None) -> int:
        stmt = select(func.count(Viewer.id)).where(Viewer.client_bot_id == client_bot_id)
        if status:
            stmt = stmt.where(Viewer.status == status)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def count_platform_total(self) -> int:
        stmt = select(func.count(Viewer.id))
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def count_created_since(self, since: datetime) -> int:
        stmt = select(func.count(Viewer.id)).where(Viewer.created_at >= since)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def count_by_client(self, client_id: int) -> int:
        stmt = (
            select(func.count(Viewer.id))
            .join(ClientBot, Viewer.client_bot_id == ClientBot.id)
            .where(ClientBot.client_id == client_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0
