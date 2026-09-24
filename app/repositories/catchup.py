"""Catch-Up Delivery Repository with cross-source duplicate detection."""

from typing import List, Optional, Set
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import CatchupStatus, DeliveryStatus
from app.core.utils import utc_now
from app.db.models.broadcast import Broadcast
from app.db.models.broadcast_delivery import BroadcastDelivery
from app.db.models.catchup_delivery import CatchupDelivery
from app.repositories.base import BaseRepository


class CatchupDeliveryRepository(BaseRepository[CatchupDelivery]):
    def __init__(self, session: AsyncSession):
        super().__init__(CatchupDelivery, session)

    async def get_by_viewer_and_video(
        self,
        viewer_id: int,
        video_id: int,
    ) -> Optional[CatchupDelivery]:
        stmt = select(CatchupDelivery).where(
            CatchupDelivery.viewer_id == viewer_id,
            CatchupDelivery.video_id == video_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def has_received_video(self, viewer_id: int, video_id: int) -> bool:
        """Checks whether the viewer has already received the video via Catch-Up OR LIVE Broadcast."""
        # 1. Check catch-up deliveries
        catchup_record = await self.get_by_viewer_and_video(viewer_id, video_id)
        if catchup_record and catchup_record.status == CatchupStatus.SENT:
            return True

        # 2. Check broadcast deliveries
        bcast_stmt = (
            select(BroadcastDelivery.id)
            .join(Broadcast, BroadcastDelivery.broadcast_id == Broadcast.id)
            .where(
                BroadcastDelivery.viewer_id == viewer_id,
                Broadcast.video_id == video_id,
                BroadcastDelivery.status == DeliveryStatus.SENT,
            )
            .limit(1)
        )
        bcast_res = await self.session.execute(bcast_stmt)
        return bcast_res.scalar_one_or_none() is not None

    async def list_delivered_video_ids_for_viewer(self, viewer_id: int) -> Set[int]:
        """Returns the set of all video IDs already delivered to this viewer across LIVE and Catch-up."""
        # Catchup deliveries
        c_stmt = (
            select(CatchupDelivery.video_id)
            .where(
                CatchupDelivery.viewer_id == viewer_id,
                CatchupDelivery.status == CatchupStatus.SENT,
            )
        )
        c_res = await self.session.execute(c_stmt)
        delivered_ids = set(c_res.scalars().all())

        # Live broadcast deliveries
        b_stmt = (
            select(Broadcast.video_id)
            .join(BroadcastDelivery, BroadcastDelivery.broadcast_id == Broadcast.id)
            .where(
                BroadcastDelivery.viewer_id == viewer_id,
                BroadcastDelivery.status == DeliveryStatus.SENT,
            )
        )
        b_res = await self.session.execute(b_stmt)
        delivered_ids.update(b_res.scalars().all())

        return delivered_ids

    async def record_delivery(
        self,
        client_bot_id: int,
        viewer_id: int,
        video_id: int,
        status: CatchupStatus,
        telegram_message_id: Optional[int] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> CatchupDelivery:
        """Records or updates a catch-up delivery record."""
        existing = await self.get_by_viewer_and_video(viewer_id, video_id)
        now = utc_now()
        if existing:
            existing.status = status
            existing.attempt_count += 1
            if telegram_message_id is not None:
                existing.telegram_message_id = telegram_message_id
            if status == CatchupStatus.SENT:
                existing.sent_at = now
                existing.last_error_code = None
                existing.last_error_message = None
            else:
                existing.last_error_code = error_code
                existing.last_error_message = error_message
            await self.session.flush()
            return existing

        delivery = CatchupDelivery(
            client_bot_id=client_bot_id,
            viewer_id=viewer_id,
            video_id=video_id,
            status=status,
            attempt_count=1,
            telegram_message_id=telegram_message_id,
            last_error_code=error_code,
            last_error_message=error_message,
            sent_at=now if status == CatchupStatus.SENT else None,
        )
        self.session.add(delivery)
        await self.session.flush()
        return delivery

    async def record_catchup_sent(
        self,
        client_bot_id: int,
        viewer_id: int,
        video_id: int,
        broadcast_delivery_id: Optional[int] = None,
    ) -> CatchupDelivery:
        return await self.record_delivery(
            client_bot_id=client_bot_id,
            viewer_id=viewer_id,
            video_id=video_id,
            status=CatchupStatus.SENT,
        )
