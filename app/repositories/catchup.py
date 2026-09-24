"""Catch-Up Delivery Repository."""

from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import CatchupStatus
from app.core.utils import utc_now
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
        record = await self.get_by_viewer_and_video(viewer_id, video_id)
        return bool(record and record.status == CatchupStatus.SENT)

    async def record_catchup_sent(
        self,
        client_bot_id: int,
        viewer_id: int,
        video_id: int,
        broadcast_delivery_id: Optional[int] = None,
    ) -> CatchupDelivery:
        existing = await self.get_by_viewer_and_video(viewer_id, video_id)
        if existing:
            existing.status = CatchupStatus.SENT
            existing.sent_at = utc_now()
            existing.broadcast_delivery_id = broadcast_delivery_id
            await self.session.flush()
            return existing

        delivery = CatchupDelivery(
            client_bot_id=client_bot_id,
            viewer_id=viewer_id,
            video_id=video_id,
            status=CatchupStatus.SENT,
            broadcast_delivery_id=broadcast_delivery_id,
            sent_at=utc_now(),
        )
        self.session.add(delivery)
        await self.session.flush()
        return delivery

    async def list_delivered_video_ids_for_viewer(self, viewer_id: int) -> List[int]:
        stmt = (
            select(CatchupDelivery.video_id)
            .where(
                CatchupDelivery.viewer_id == viewer_id,
                CatchupDelivery.status == CatchupStatus.SENT,
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
