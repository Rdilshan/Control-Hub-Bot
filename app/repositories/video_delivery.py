"""Video Delivery Repository."""

from datetime import datetime
from typing import Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import DeliveryStatus
from app.core.utils import utc_now
from app.db.models.video_delivery import VideoDelivery
from app.repositories.base import BaseRepository


class VideoDeliveryRepository(BaseRepository[VideoDelivery]):
    def __init__(self, session: AsyncSession):
        super().__init__(VideoDelivery, session)

    async def get_by_id(self, delivery_id: int) -> Optional[VideoDelivery]:
        stmt = select(VideoDelivery).where(VideoDelivery.id == delivery_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_delivery(
        self,
        client_bot_id: int,
        video_id: int,
        viewer_id: Optional[int] = None,
        telegram_user_id: Optional[int] = None,
        delivery_type: str = "UNLOCK",
        status: DeliveryStatus = DeliveryStatus.PENDING,
    ) -> VideoDelivery:
        delivery = VideoDelivery(
            client_bot_id=client_bot_id,
            video_id=video_id,
            viewer_id=viewer_id,
            telegram_user_id=telegram_user_id,
            delivery_type=delivery_type,
            status=status,
        )
        self.session.add(delivery)
        await self.session.flush()
        return delivery

    async def mark_sent(
        self,
        delivery_id: int,
        telegram_message_id: Optional[int] = None,
    ) -> Optional[VideoDelivery]:
        delivery = await self.get_by_id(delivery_id)
        if delivery:
            delivery.status = DeliveryStatus.SENT
            delivery.telegram_message_id = telegram_message_id
            delivery.sent_at = utc_now()
            await self.session.flush()
        return delivery

    async def mark_failed(
        self,
        delivery_id: int,
        error_code: str,
        error_message: str,
    ) -> Optional[VideoDelivery]:
        delivery = await self.get_by_id(delivery_id)
        if delivery:
            delivery.status = DeliveryStatus.FAILED
            delivery.error_code = error_code
            delivery.error_message = error_message
            await self.session.flush()
        return delivery

    async def mark_blocked(
        self,
        delivery_id: int,
        error_message: str = "Viewer blocked the bot",
    ) -> Optional[VideoDelivery]:
        delivery = await self.get_by_id(delivery_id)
        if delivery:
            delivery.status = DeliveryStatus.BLOCKED
            delivery.error_code = "TELEGRAM_FORBIDDEN"
            delivery.error_message = error_message
            await self.session.flush()
        return delivery

    async def count_by_bot(
        self,
        client_bot_id: int,
        status: Optional[DeliveryStatus] = None,
    ) -> int:
        stmt = select(func.count(VideoDelivery.id)).where(VideoDelivery.client_bot_id == client_bot_id)
        if status:
            stmt = stmt.where(VideoDelivery.status == status)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def count_by_video(
        self,
        video_id: int,
        status: Optional[DeliveryStatus] = None,
    ) -> int:
        stmt = select(func.count(VideoDelivery.id)).where(VideoDelivery.video_id == video_id)
        if status:
            stmt = stmt.where(VideoDelivery.status == status)
        result = await self.session.execute(stmt)
        return result.scalar() or 0
