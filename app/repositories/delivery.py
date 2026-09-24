"""Broadcast Delivery Repository."""

from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import DeliveryStatus
from app.core.utils import utc_now
from app.db.models.broadcast_delivery import BroadcastDelivery
from app.repositories.base import BaseRepository


class BroadcastDeliveryRepository(BaseRepository[BroadcastDelivery]):
    def __init__(self, session: AsyncSession):
        super().__init__(BroadcastDelivery, session)

    async def get_by_broadcast_and_viewer(
        self,
        broadcast_id: int,
        viewer_id: int,
    ) -> Optional[BroadcastDelivery]:
        stmt = select(BroadcastDelivery).where(
            BroadcastDelivery.broadcast_id == broadcast_id,
            BroadcastDelivery.viewer_id == viewer_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_pending_delivery(
        self,
        broadcast_id: int,
        viewer_id: int,
    ) -> BroadcastDelivery:
        delivery = BroadcastDelivery(
            broadcast_id=broadcast_id,
            viewer_id=viewer_id,
            status=DeliveryStatus.PENDING,
        )
        self.session.add(delivery)
        await self.session.flush()
        return delivery

    async def create_pending_batch(
        self,
        broadcast_id: int,
        viewer_ids: List[int],
    ) -> List[BroadcastDelivery]:
        deliveries = [
            BroadcastDelivery(
                broadcast_id=broadcast_id,
                viewer_id=v_id,
                status=DeliveryStatus.PENDING,
            )
            for v_id in viewer_ids
        ]
        self.session.add_all(deliveries)
        await self.session.flush()
        return deliveries

    async def get_pending_batch(
        self,
        broadcast_id: int,
        limit: int = 100,
    ) -> List[BroadcastDelivery]:
        stmt = (
            select(BroadcastDelivery)
            .where(
                BroadcastDelivery.broadcast_id == broadcast_id,
                BroadcastDelivery.status == DeliveryStatus.PENDING,
            )
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_deliveries_for_viewers(
        self,
        broadcast_id: int,
        viewer_ids: List[int],
    ) -> dict[int, BroadcastDelivery]:
        """Returns a dict mapping viewer_id -> BroadcastDelivery for the given viewer IDs."""
        if not viewer_ids:
            return {}
        stmt = select(BroadcastDelivery).where(
            BroadcastDelivery.broadcast_id == broadcast_id,
            BroadcastDelivery.viewer_id.in_(viewer_ids),
        )
        result = await self.session.execute(stmt)
        deliveries = result.scalars().all()
        return {d.viewer_id: d for d in deliveries}

    async def record_delivery(
        self,
        broadcast_id: int,
        viewer_id: int,
        status: DeliveryStatus,
        telegram_message_id: Optional[int] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> BroadcastDelivery:
        """Creates or updates a delivery record for a viewer."""
        delivery = await self.get_by_broadcast_and_viewer(broadcast_id, viewer_id)
        now = utc_now()
        if delivery:
            delivery.status = status
            delivery.attempt_count += 1
            if telegram_message_id is not None:
                delivery.telegram_message_id = telegram_message_id
            if status == DeliveryStatus.SENT:
                delivery.sent_at = now
                delivery.last_error_code = None
                delivery.last_error_message = None
            else:
                delivery.last_error_code = error_code
                delivery.last_error_message = error_message
        else:
            delivery = BroadcastDelivery(
                broadcast_id=broadcast_id,
                viewer_id=viewer_id,
                status=status,
                attempt_count=1,
                telegram_message_id=telegram_message_id,
                last_error_code=error_code,
                last_error_message=error_message,
                sent_at=now if status == DeliveryStatus.SENT else None,
            )
            self.session.add(delivery)
        await self.session.flush()
        return delivery

    async def get_retryable_failed_deliveries(
        self,
        broadcast_id: int,
        max_attempts: int = 3,
        limit: int = 100,
    ) -> List[BroadcastDelivery]:
        """Fetches failed deliveries that have not exceeded max retry attempts."""
        stmt = (
            select(BroadcastDelivery)
            .where(
                BroadcastDelivery.broadcast_id == broadcast_id,
                BroadcastDelivery.status == DeliveryStatus.FAILED,
                BroadcastDelivery.attempt_count < max_attempts,
            )
            .order_by(BroadcastDelivery.id.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def mark_sent(
        self,
        delivery_id: int,
        telegram_message_id: Optional[int] = None,
    ) -> Optional[BroadcastDelivery]:
        stmt = select(BroadcastDelivery).where(BroadcastDelivery.id == delivery_id)
        result = await self.session.execute(stmt)
        delivery = result.scalar_one_or_none()
        if delivery:
            delivery.status = DeliveryStatus.SENT
            delivery.telegram_message_id = telegram_message_id
            delivery.sent_at = utc_now()
            delivery.attempt_count += 1
            await self.session.flush()
        return delivery

    async def mark_failed(
        self,
        delivery_id: int,
        error_code: str,
        error_message: str,
    ) -> Optional[BroadcastDelivery]:
        stmt = select(BroadcastDelivery).where(BroadcastDelivery.id == delivery_id)
        result = await self.session.execute(stmt)
        delivery = result.scalar_one_or_none()
        if delivery:
            delivery.status = DeliveryStatus.FAILED
            delivery.last_error_code = error_code
            delivery.last_error_message = error_message
            delivery.attempt_count += 1
            await self.session.flush()
        return delivery

    async def mark_blocked(
        self,
        delivery_id: int,
        error_message: str = "User blocked bot",
    ) -> Optional[BroadcastDelivery]:
        stmt = select(BroadcastDelivery).where(BroadcastDelivery.id == delivery_id)
        result = await self.session.execute(stmt)
        delivery = result.scalar_one_or_none()
        if delivery:
            delivery.status = DeliveryStatus.BLOCKED
            delivery.last_error_code = "TELEGRAM_FORBIDDEN"
            delivery.last_error_message = error_message
            delivery.attempt_count += 1
            await self.session.flush()
        return delivery
