"""Viewer Catch-Up Repository with status transitions and cursor tracking."""

from typing import List, Optional, Set, Tuple
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import CatchupStatus
from app.core.utils import utc_now
from app.db.models.viewer_catchup import ViewerCatchup
from app.repositories.base import BaseRepository


class ViewerCatchupRepository(BaseRepository[ViewerCatchup]):
    def __init__(self, session: AsyncSession):
        super().__init__(ViewerCatchup, session)

    async def get_by_viewer_id(self, viewer_id: int) -> Optional[ViewerCatchup]:
        stmt = select(ViewerCatchup).where(ViewerCatchup.viewer_id == viewer_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create_catchup(
        self,
        client_bot_id: int,
        viewer_id: int,
    ) -> Tuple[ViewerCatchup, bool]:
        """Gets existing catch-up record for a viewer or creates a new PENDING one."""
        existing = await self.get_by_viewer_id(viewer_id)
        if existing:
            # If viewer was blocked but has returned, reset status to PENDING
            if existing.status == CatchupStatus.BLOCKED:
                existing.status = CatchupStatus.PENDING
                existing.paused_reason = None
                await self.session.flush()
            return existing, False

        new_catchup = ViewerCatchup(
            client_bot_id=client_bot_id,
            viewer_id=viewer_id,
            status=CatchupStatus.PENDING,
            last_video_id=0,
            total_eligible=0,
            delivered_count=0,
            failed_count=0,
        )
        self.session.add(new_catchup)
        await self.session.flush()
        return new_catchup, True

    async def set_target_boundary(
        self,
        viewer_id: int,
        target_max_video_id: int,
        total_eligible: int,
    ) -> Optional[ViewerCatchup]:
        catchup = await self.get_by_viewer_id(viewer_id)
        if catchup:
            catchup.target_max_video_id = target_max_video_id
            catchup.total_eligible = total_eligible
            await self.session.flush()
        return catchup

    async def mark_running(self, viewer_id: int) -> Optional[ViewerCatchup]:
        catchup = await self.get_by_viewer_id(viewer_id)
        if catchup:
            catchup.status = CatchupStatus.RUNNING
            catchup.paused_reason = None
            if not catchup.started_at:
                catchup.started_at = utc_now()
            catchup.last_attempted_at = utc_now()
            await self.session.flush()
        return catchup

    async def mark_paused(self, viewer_id: int, reason: str = "LIVE_PRIORITY") -> Optional[ViewerCatchup]:
        catchup = await self.get_by_viewer_id(viewer_id)
        if catchup:
            catchup.status = CatchupStatus.PAUSED
            catchup.paused_reason = reason
            await self.session.flush()
        return catchup

    async def mark_completed(self, viewer_id: int) -> Optional[ViewerCatchup]:
        catchup = await self.get_by_viewer_id(viewer_id)
        if catchup:
            catchup.status = CatchupStatus.COMPLETED
            catchup.completed_at = utc_now()
            catchup.paused_reason = None
            await self.session.flush()
        return catchup

    async def mark_blocked(self, viewer_id: int) -> Optional[ViewerCatchup]:
        catchup = await self.get_by_viewer_id(viewer_id)
        if catchup:
            catchup.status = CatchupStatus.BLOCKED
            catchup.paused_reason = "VIEWER_BLOCKED"
            await self.session.flush()
        return catchup

    async def mark_failed(self, viewer_id: int, reason: str) -> Optional[ViewerCatchup]:
        catchup = await self.get_by_viewer_id(viewer_id)
        if catchup:
            catchup.status = CatchupStatus.FAILED
            catchup.paused_reason = reason
            await self.session.flush()
        return catchup

    async def update_progress_and_cursor(
        self,
        viewer_id: int,
        last_video_id: int,
        delivered_delta: int = 0,
        failed_delta: int = 0,
    ) -> Optional[ViewerCatchup]:
        catchup = await self.get_by_viewer_id(viewer_id)
        if catchup:
            catchup.last_video_id = last_video_id
            catchup.delivered_count += delivered_delta
            catchup.failed_count += failed_delta
            if delivered_delta > 0:
                catchup.last_delivered_at = utc_now()
            catchup.last_attempted_at = utc_now()
            await self.session.flush()
        return catchup

    async def count_active_catchups_for_bot(self, client_bot_id: int) -> int:
        stmt = (
            select(func.count(ViewerCatchup.id))
            .where(
                ViewerCatchup.client_bot_id == client_bot_id,
                ViewerCatchup.status == CatchupStatus.RUNNING,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def list_runnable_catchups(
        self,
        limit: int = 10,
        excluded_bot_ids: Optional[Set[int]] = None,
    ) -> List[ViewerCatchup]:
        stmt = (
            select(ViewerCatchup)
            .where(
                ViewerCatchup.status.in_([CatchupStatus.PENDING, CatchupStatus.PAUSED]),
            )
        )
        if excluded_bot_ids:
            stmt = stmt.where(ViewerCatchup.client_bot_id.notin_(excluded_bot_ids))

        stmt = stmt.order_by(ViewerCatchup.created_at.asc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
