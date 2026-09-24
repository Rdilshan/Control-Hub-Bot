"""Client Bot Statistics Repository with strict bot isolation and SQL aggregation."""

from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    BroadcastStatus,
    CatchupStatus,
    ProcessingStatus,
    VideoStatus,
    ViewerStatus,
)
from app.core.utils import utc_now
from app.db.models.broadcast import Broadcast
from app.db.models.video import Video
from app.db.models.video_processing import VideoProcessing
from app.db.models.viewer import Viewer
from app.db.models.viewer_catchup import ViewerCatchup


class ClientBotStatsRepository:
    """Provides high-performance aggregate statistics scoped to a single Client Bot."""

    def __init__(self, session: AsyncSession):
        self.session = session

    def _get_start_of_today_utc(self) -> datetime:
        now = utc_now()
        return datetime.combine(now.date(), time.min, tzinfo=timezone.utc)

    def _get_seven_days_ago_utc(self) -> datetime:
        return utc_now() - timedelta(days=7)

    async def get_user_counts(self, client_bot_id: int) -> Dict[str, int]:
        """Calculates viewer counts (total, active, blocked, new today, new last 7 days)."""
        today_start = self._get_start_of_today_utc()
        seven_days_ago = self._get_seven_days_ago_utc()

        # Aggregate viewer metrics in single query
        stmt = (
            select(
                func.count(Viewer.id).label("total"),
                func.count(Viewer.id).filter(Viewer.status == ViewerStatus.ACTIVE).label("active"),
                func.count(Viewer.id).filter(Viewer.status == ViewerStatus.BLOCKED).label("blocked"),
                func.count(Viewer.id).filter(Viewer.first_started_at >= today_start).label("new_today"),
                func.count(Viewer.id).filter(Viewer.first_started_at >= seven_days_ago).label("new_7_days"),
            )
            .where(Viewer.client_bot_id == client_bot_id)
        )
        res = await self.session.execute(stmt)
        row = res.one()

        return {
            "total": row.total or 0,
            "active": row.active or 0,
            "blocked": row.blocked or 0,
            "new_today": row.new_today or 0,
            "new_7_days": row.new_7_days or 0,
        }

    async def get_video_counts(self, client_bot_id: int) -> Dict[str, int]:
        """Calculates video counts (total, ready, processing, failed, disabled, created today)."""
        today_start = self._get_start_of_today_utc()

        stmt = (
            select(
                func.count(Video.id).label("total"),
                func.count(Video.id).filter(Video.status == VideoStatus.READY).label("ready"),
                func.count(Video.id).filter(
                    Video.status.in_([VideoStatus.RECEIVED, VideoStatus.PROCESSING])
                ).label("processing"),
                func.count(Video.id).filter(Video.status == VideoStatus.FAILED).label("failed"),
                func.count(Video.id).filter(Video.status == VideoStatus.DISABLED).label("disabled"),
                func.count(Video.id).filter(Video.created_at >= today_start).label("created_today"),
            )
            .where(Video.client_bot_id == client_bot_id)
        )
        res = await self.session.execute(stmt)
        row = res.one()

        return {
            "total": row.total or 0,
            "ready": row.ready or 0,
            "processing": row.processing or 0,
            "failed": row.failed or 0,
            "disabled": row.disabled or 0,
            "created_today": row.created_today or 0,
        }

    async def get_processing_counts(self, client_bot_id: int) -> Dict[str, int]:
        """Calculates granular processing breakdown by stage."""
        today_start = self._get_start_of_today_utc()

        # Received status
        stmt_rec = (
            select(func.count(Video.id))
            .where(
                Video.client_bot_id == client_bot_id,
                Video.status == VideoStatus.RECEIVED,
            )
        )
        received_res = await self.session.execute(stmt_rec)
        received = received_res.scalar() or 0

        # Processing stages from VideoProcessing joined with Video
        stmt_proc = (
            select(
                func.count(VideoProcessing.id).filter(
                    VideoProcessing.status.in_([ProcessingStatus.PROCESSING_THUMBNAIL, ProcessingStatus.PROCESSING])
                ).label("preview"),
                func.count(VideoProcessing.id).filter(
                    VideoProcessing.status == ProcessingStatus.CREATING_UNLOCK_LINK
                ).label("unlockify"),
            )
            .join(Video, VideoProcessing.video_id == Video.id)
            .where(Video.client_bot_id == client_bot_id)
        )
        proc_res = await self.session.execute(stmt_proc)
        proc_row = proc_res.one()

        # Ready today
        stmt_ready_today = (
            select(func.count(Video.id))
            .where(
                Video.client_bot_id == client_bot_id,
                Video.status == VideoStatus.READY,
                Video.published_at >= today_start,
            )
        )
        ready_res = await self.session.execute(stmt_ready_today)
        ready_today = ready_res.scalar() or 0

        # Failed
        stmt_failed = (
            select(func.count(Video.id))
            .where(
                Video.client_bot_id == client_bot_id,
                Video.status == VideoStatus.FAILED,
            )
        )
        failed_res = await self.session.execute(stmt_failed)
        failed = failed_res.scalar() or 0

        return {
            "received": received,
            "preview": proc_row.preview or 0,
            "unlockify": proc_row.unlockify or 0,
            "ready_today": ready_today,
            "failed": failed,
        }

    async def get_broadcast_counts(self, client_bot_id: int) -> Dict[str, int]:
        """Calculates LIVE and Catch-Up broadcast metrics for a bot."""
        today_start = self._get_start_of_today_utc()

        # LIVE Broadcasts
        stmt_live = (
            select(
                func.count(Broadcast.id).filter(Broadcast.status == BroadcastStatus.RUNNING).label("running"),
                func.count(Broadcast.id).filter(
                    Broadcast.status.in_([BroadcastStatus.PENDING, BroadcastStatus.QUEUED])
                ).label("waiting"),
                func.count(Broadcast.id).filter(
                    Broadcast.status.in_([BroadcastStatus.COMPLETED, BroadcastStatus.PARTIAL]),
                    Broadcast.completed_at >= today_start,
                ).label("completed_today"),
                func.count(Broadcast.id).filter(Broadcast.status == BroadcastStatus.FAILED).label("failed"),
            )
            .where(
                Broadcast.client_bot_id == client_bot_id,
                Broadcast.broadcast_type == "LIVE",
            )
        )
        live_res = await self.session.execute(stmt_live)
        live_row = live_res.one()

        # Catch-Up Viewers
        stmt_catchup = (
            select(
                func.count(ViewerCatchup.id).filter(ViewerCatchup.status == CatchupStatus.RUNNING).label("running"),
                func.count(ViewerCatchup.id).filter(
                    ViewerCatchup.status.in_([CatchupStatus.PENDING, CatchupStatus.PAUSED])
                ).label("waiting"),
                func.count(ViewerCatchup.id).filter(
                    ViewerCatchup.status == CatchupStatus.COMPLETED,
                    ViewerCatchup.completed_at >= today_start,
                ).label("completed_today"),
                func.count(ViewerCatchup.id).filter(ViewerCatchup.status == CatchupStatus.FAILED).label("failed"),
                func.count(ViewerCatchup.id).filter(ViewerCatchup.status == CatchupStatus.BLOCKED).label("blocked"),
            )
            .where(ViewerCatchup.client_bot_id == client_bot_id)
        )
        catchup_res = await self.session.execute(stmt_catchup)
        catchup_row = catchup_res.one()

        return {
            "live_running": live_row.running or 0,
            "live_waiting": live_row.waiting or 0,
            "live_completed_today": live_row.completed_today or 0,
            "live_failed": live_row.failed or 0,
            "catchup_running": catchup_row.running or 0,
            "catchup_waiting": catchup_row.waiting or 0,
            "catchup_completed_today": catchup_row.completed_today or 0,
            "catchup_failed": catchup_row.failed or 0,
            "catchup_blocked": catchup_row.blocked or 0,
        }

    async def get_catchup_counts(self, client_bot_id: int) -> Dict[str, int]:
        """Calculates standalone catch-up stats."""
        today_start = self._get_start_of_today_utc()

        stmt = (
            select(
                func.count(ViewerCatchup.id).filter(ViewerCatchup.status == CatchupStatus.RUNNING).label("running"),
                func.count(ViewerCatchup.id).filter(
                    ViewerCatchup.status.in_([CatchupStatus.PENDING, CatchupStatus.PAUSED])
                ).label("waiting"),
                func.count(ViewerCatchup.id).filter(
                    ViewerCatchup.status == CatchupStatus.COMPLETED,
                    ViewerCatchup.completed_at >= today_start,
                ).label("completed_today"),
                func.count(ViewerCatchup.id).filter(ViewerCatchup.status == CatchupStatus.FAILED).label("failed"),
                func.count(ViewerCatchup.id).filter(ViewerCatchup.status == CatchupStatus.BLOCKED).label("blocked"),
            )
            .where(ViewerCatchup.client_bot_id == client_bot_id)
        )
        res = await self.session.execute(stmt)
        row = res.one()

        return {
            "running": row.running or 0,
            "waiting": row.waiting or 0,
            "completed_today": row.completed_today or 0,
            "failed": row.failed or 0,
            "blocked": row.blocked or 0,
        }
