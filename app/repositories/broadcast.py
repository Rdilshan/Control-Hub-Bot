"""Broadcast Repository with strict bot isolation."""

from datetime import datetime
from typing import List, Optional, Tuple
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import BotEventType, BroadcastStatus
from app.core.utils import utc_now
from app.db.models.bot_event import BotEvent
from app.db.models.broadcast import Broadcast
from app.repositories.base import BaseRepository


class BroadcastRepository(BaseRepository[Broadcast]):
    def __init__(self, session: AsyncSession):
        super().__init__(Broadcast, session)

    async def get_by_id(self, broadcast_id: int) -> Optional[Broadcast]:
        stmt = select(Broadcast).where(Broadcast.id == broadcast_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_and_bot(self, broadcast_id: int, client_bot_id: int) -> Optional[Broadcast]:
        stmt = select(Broadcast).where(
            Broadcast.id == broadcast_id,
            Broadcast.client_bot_id == client_bot_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_video_id(self, video_id: int) -> Optional[Broadcast]:
        stmt = select(Broadcast).where(Broadcast.video_id == video_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_broadcast(
        self,
        client_bot_id: int,
        video_id: int,
        total_targets: int,
        created_by_admin_id: Optional[int] = None,
        target_type: str = "ALL_ACTIVE_VIEWERS",
    ) -> Broadcast:
        broadcast = Broadcast(
            client_bot_id=client_bot_id,
            video_id=video_id,
            created_by_admin_id=created_by_admin_id,
            target_type=target_type,
            total_targets=total_targets,
            status=BroadcastStatus.PENDING,
        )
        self.session.add(broadcast)
        await self.session.flush()

        event = BotEvent(
            client_bot_id=client_bot_id,
            event_type=BotEventType.BROADCAST_STARTED,
            related_broadcast_id=broadcast.id,
            related_video_id=video_id,
            metadata_json={"total_targets": total_targets},
        )
        self.session.add(event)

        await self.session.flush()
        return broadcast

    async def start_broadcast(self, broadcast_id: int) -> Optional[Broadcast]:
        stmt = select(Broadcast).where(Broadcast.id == broadcast_id)
        result = await self.session.execute(stmt)
        broadcast = result.scalar_one_or_none()
        if broadcast:
            broadcast.status = BroadcastStatus.RUNNING
            broadcast.started_at = utc_now()
            await self.session.flush()
        return broadcast

    async def set_snapshot(
        self,
        broadcast_id: int,
        total_targets: int,
        audience_max_viewer_id: int,
    ) -> Optional[Broadcast]:
        """Saves initial audience snapshot metadata when broadcast starts."""
        stmt = select(Broadcast).where(Broadcast.id == broadcast_id)
        result = await self.session.execute(stmt)
        broadcast = result.scalar_one_or_none()
        if broadcast:
            broadcast.total_targets = total_targets
            broadcast.audience_max_viewer_id = audience_max_viewer_id
            await self.session.flush()
        return broadcast

    async def update_progress_and_cursor(
        self,
        broadcast_id: int,
        sent_delta: int = 0,
        failed_delta: int = 0,
        blocked_delta: int = 0,
        last_processed_viewer_id: Optional[int] = None,
    ) -> Optional[Broadcast]:
        """Updates counts and last processed viewer id cursor."""
        stmt = select(Broadcast).where(Broadcast.id == broadcast_id)
        result = await self.session.execute(stmt)
        broadcast = result.scalar_one_or_none()
        if broadcast:
            broadcast.sent_count += sent_delta
            broadcast.failed_count += failed_delta
            broadcast.blocked_count += blocked_delta
            if last_processed_viewer_id is not None:
                broadcast.last_processed_viewer_id = last_processed_viewer_id

            # Check if all completed
            processed = broadcast.sent_count + broadcast.failed_count + broadcast.blocked_count
            if processed >= broadcast.total_targets and broadcast.total_targets > 0:
                broadcast.status = (
                    BroadcastStatus.COMPLETED if broadcast.failed_count == 0 else BroadcastStatus.PARTIAL
                )
                broadcast.completed_at = utc_now()
            await self.session.flush()
        return broadcast

    async def mark_completed(self, broadcast_id: int) -> Optional[Broadcast]:
        """Marks broadcast as COMPLETED or PARTIAL if there were errors."""
        stmt = select(Broadcast).where(Broadcast.id == broadcast_id)
        result = await self.session.execute(stmt)
        broadcast = result.scalar_one_or_none()
        if broadcast:
            broadcast.status = (
                BroadcastStatus.COMPLETED if broadcast.failed_count == 0 else BroadcastStatus.PARTIAL
            )
            broadcast.completed_at = utc_now()
            await self.session.flush()
        return broadcast

    async def mark_failed(
        self,
        broadcast_id: int,
        error_code: str,
        error_message: str,
    ) -> Optional[Broadcast]:
        """Marks broadcast as FAILED with error details."""
        stmt = select(Broadcast).where(Broadcast.id == broadcast_id)
        result = await self.session.execute(stmt)
        broadcast = result.scalar_one_or_none()
        if broadcast:
            broadcast.status = BroadcastStatus.FAILED
            broadcast.last_error_code = error_code
            broadcast.last_error_message = error_message
            broadcast.completed_at = utc_now()
            await self.session.flush()
        return broadcast

    async def mark_paused(self, broadcast_id: int) -> Optional[Broadcast]:
        """Marks broadcast as PAUSED."""
        stmt = select(Broadcast).where(Broadcast.id == broadcast_id)
        result = await self.session.execute(stmt)
        broadcast = result.scalar_one_or_none()
        if broadcast:
            broadcast.status = BroadcastStatus.PAUSED
            await self.session.flush()
        return broadcast

    async def get_active_live_broadcast_for_bot(self, client_bot_id: int) -> Optional[Broadcast]:
        """Returns currently running live broadcast for a client bot, if any."""
        stmt = (
            select(Broadcast)
            .where(
                Broadcast.client_bot_id == client_bot_id,
                Broadcast.broadcast_type == "LIVE",
                Broadcast.status == BroadcastStatus.RUNNING,
            )
            .order_by(Broadcast.created_at.asc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_oldest_queued_live_broadcast(
        self, client_bot_id: Optional[int] = None
    ) -> Optional[Broadcast]:
        """Returns oldest queued LIVE broadcast (optionally for a specific bot)."""
        stmt = (
            select(Broadcast)
            .where(
                Broadcast.broadcast_type == "LIVE",
                Broadcast.status.in_([BroadcastStatus.PENDING, BroadcastStatus.QUEUED]),
            )
        )
        if client_bot_id is not None:
            stmt = stmt.where(Broadcast.client_bot_id == client_bot_id)

        stmt = stmt.order_by(Broadcast.created_at.asc()).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_bot(
        self,
        client_bot_id: int,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Broadcast]:
        stmt = (
            select(Broadcast)
            .where(Broadcast.client_bot_id == client_bot_id)
            .order_by(Broadcast.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_bot(self, client_bot_id: int, status: Optional[BroadcastStatus] = None) -> int:
        stmt = select(func.count(Broadcast.id)).where(Broadcast.client_bot_id == client_bot_id)
        if status:
            stmt = stmt.where(Broadcast.status == status)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def count_all(self) -> int:
        stmt = select(func.count(Broadcast.id))
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def count_by_status(self, status: BroadcastStatus) -> int:
        stmt = select(func.count(Broadcast.id)).where(Broadcast.status == status)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def count_completed_since(self, since: datetime) -> int:
        stmt = select(func.count(Broadcast.id)).where(
            Broadcast.status.in_([BroadcastStatus.COMPLETED, BroadcastStatus.PARTIAL]),
            Broadcast.completed_at >= since,
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def list_paginated(
        self,
        status: Optional[BroadcastStatus] = None,
        page: int = 1,
        page_size: int = 10,
    ) -> Tuple[List[Broadcast], int]:
        count_stmt = select(func.count(Broadcast.id))
        query_stmt = select(Broadcast).order_by(Broadcast.created_at.desc())

        if status:
            count_stmt = count_stmt.where(Broadcast.status == status)
            query_stmt = query_stmt.where(Broadcast.status == status)

        total_res = await self.session.execute(count_stmt)
        total_count = total_res.scalar() or 0

        offset = max(0, (page - 1) * page_size)
        query_stmt = query_stmt.limit(page_size).offset(offset)
        result = await self.session.execute(query_stmt)
        items = list(result.scalars().all())

        return items, total_count
