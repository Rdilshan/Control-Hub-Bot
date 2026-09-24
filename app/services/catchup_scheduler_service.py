"""Catch-Up Scheduler Service for enforcing LIVE priority, per-bot concurrency caps, and fairness."""

from typing import List, Optional, Set
from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.core.enums import BroadcastStatus, CatchupStatus
from app.db.models.broadcast import Broadcast
from app.db.models.viewer_catchup import ViewerCatchup
from app.logging_config import logger
from app.repositories.broadcast import BroadcastRepository
from app.repositories.viewer_catchup import ViewerCatchupRepository


class CatchupSchedulerService:
    """Selects eligible catch-up tasks while strictly enforcing LIVE priority and per-bot concurrency."""

    def __init__(
        self,
        session: AsyncSession,
        catchup_repo: Optional[ViewerCatchupRepository] = None,
        broadcast_repo: Optional[BroadcastRepository] = None,
    ):
        self.session = session
        self.catchup_repo = catchup_repo or ViewerCatchupRepository(session)
        self.broadcast_repo = broadcast_repo or BroadcastRepository(session)

    async def has_live_broadcast_in_progress(self, client_bot_id: int) -> bool:
        """Returns True if the bot has an active or queued LIVE broadcast that takes priority."""
        stmt = (
            select(Broadcast.id)
            .where(
                Broadcast.client_bot_id == client_bot_id,
                Broadcast.broadcast_type == "LIVE",
                Broadcast.status.in_([BroadcastStatus.PENDING, BroadcastStatus.QUEUED, BroadcastStatus.RUNNING]),
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def get_ineligible_bot_ids(self) -> Set[int]:
        """Finds all client bot IDs that are currently ineligible for catch-up execution."""
        # 1. Bots with active/queued LIVE broadcasts
        live_stmt = (
            select(distinct(Broadcast.client_bot_id))
            .where(
                Broadcast.broadcast_type == "LIVE",
                Broadcast.status.in_([BroadcastStatus.PENDING, BroadcastStatus.QUEUED, BroadcastStatus.RUNNING]),
            )
        )
        live_res = await self.session.execute(live_stmt)
        ineligible_bots = set(live_res.scalars().all())

        return ineligible_bots

    async def is_bot_available_for_catchup(self, client_bot_id: int) -> bool:
        """Checks if a specific bot can run another catch-up viewer."""
        # 1. LIVE priority check
        if await self.has_live_broadcast_in_progress(client_bot_id):
            return False

        # 2. Concurrency limit check
        settings = get_settings()
        max_concurrent = getattr(settings, "MAX_ACTIVE_CATCHUP_VIEWERS_PER_BOT", 5)
        active_count = await self.catchup_repo.count_active_catchups_for_bot(client_bot_id)
        return active_count < max_concurrent

    async def get_next_runnable_catchup(self) -> Optional[ViewerCatchup]:
        """Finds the next eligible ViewerCatchup to process across all client bots."""
        ineligible_bots = await self.get_ineligible_bot_ids()

        candidates = await self.catchup_repo.list_runnable_catchups(
            limit=50,
            excluded_bot_ids=ineligible_bots,
        )

        settings = get_settings()
        max_concurrent = getattr(settings, "MAX_ACTIVE_CATCHUP_VIEWERS_PER_BOT", 5)

        for candidate in candidates:
            active_count = await self.catchup_repo.count_active_catchups_for_bot(candidate.client_bot_id)
            if active_count < max_concurrent:
                logger.info(
                    "Selected catch-up for viewer_id=%d on bot_id=%d (status=%s)",
                    candidate.viewer_id,
                    candidate.client_bot_id,
                    candidate.status,
                )
                return candidate

        return None
