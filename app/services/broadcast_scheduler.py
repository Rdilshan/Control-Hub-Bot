"""Broadcast Scheduler for multi-bot fairness and single-active LIVE broadcast enforcement."""

from typing import List, Optional
from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import BroadcastStatus
from app.db.models.broadcast import Broadcast
from app.logging_config import logger
from app.repositories.broadcast import BroadcastRepository


class BroadcastScheduler:
    """Selects the next eligible broadcast to process while enforcing bot concurrency limits and fairness."""

    def __init__(self, session: AsyncSession, broadcast_repo: Optional[BroadcastRepository] = None):
        self.session = session
        self.broadcast_repo = broadcast_repo or BroadcastRepository(session)

    async def get_next_runnable_broadcast(self) -> Optional[Broadcast]:
        """Finds the next runnable LIVE broadcast across all client bots.

        Enforces:
        1. Only one active LIVE broadcast per Client Bot.
        2. LIVE broadcast priority.
        3. Fair FIFO selection across bots.
        """
        # 1. Find all client_bot_ids that have currently RUNNING live broadcasts
        running_bots_stmt = (
            select(distinct(Broadcast.client_bot_id))
            .where(
                Broadcast.broadcast_type == "LIVE",
                Broadcast.status == BroadcastStatus.RUNNING,
            )
        )
        running_bots_res = await self.session.execute(running_bots_stmt)
        running_bot_ids = set(running_bots_res.scalars().all())

        # 2. Query oldest queued LIVE broadcasts from bots that are not currently running a broadcast
        stmt = (
            select(Broadcast)
            .where(
                Broadcast.broadcast_type == "LIVE",
                Broadcast.status.in_([BroadcastStatus.PENDING, BroadcastStatus.QUEUED]),
            )
        )
        if running_bot_ids:
            stmt = stmt.where(Broadcast.client_bot_id.notin_(running_bot_ids))

        stmt = stmt.order_by(Broadcast.created_at.asc()).limit(1)
        result = await self.session.execute(stmt)
        broadcast = result.scalar_one_or_none()

        if broadcast:
            logger.info(
                "Scheduler selected broadcast id=%d for bot id=%d (type=%s, queued_at=%s)",
                broadcast.id,
                broadcast.client_bot_id,
                broadcast.broadcast_type,
                broadcast.created_at,
            )
        return broadcast

    async def is_bot_available_for_live(self, client_bot_id: int) -> bool:
        """Returns True if the bot has no currently RUNNING LIVE broadcast."""
        active = await self.broadcast_repo.get_active_live_broadcast_for_bot(client_bot_id)
        return active is None

    async def list_runnable_broadcasts(self, limit: int = 10) -> List[Broadcast]:
        """Returns a list of runnable broadcasts across different available bots."""
        running_bots_stmt = (
            select(distinct(Broadcast.client_bot_id))
            .where(
                Broadcast.broadcast_type == "LIVE",
                Broadcast.status == BroadcastStatus.RUNNING,
            )
        )
        running_bots_res = await self.session.execute(running_bots_stmt)
        running_bot_ids = set(running_bots_res.scalars().all())

        stmt = (
            select(Broadcast)
            .where(
                Broadcast.broadcast_type == "LIVE",
                Broadcast.status.in_([BroadcastStatus.PENDING, BroadcastStatus.QUEUED]),
            )
        )
        if running_bot_ids:
            stmt = stmt.where(Broadcast.client_bot_id.notin_(running_bot_ids))

        stmt = stmt.order_by(Broadcast.created_at.asc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
