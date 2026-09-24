"""Platform Statistics Repository providing platform-wide aggregations for Platform Owner."""

from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    BroadcastStatus,
    CatchupStatus,
    ClientBotStatus,
    ClientStatus,
    JobStatus,
    VideoStatus,
    ViewerStatus,
)
from app.core.utils import utc_now
from app.db.models.background_job import BackgroundJob
from app.db.models.broadcast import Broadcast
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.db.models.video import Video
from app.db.models.viewer import Viewer
from app.db.models.viewer_catchup import ViewerCatchup


class PlatformStatsRepository:
    """Calculates efficient platform-wide aggregates across all clients, bots, and jobs."""

    def __init__(self, session: AsyncSession):
        self.session = session

    def _get_start_of_today_utc(self) -> datetime:
        now = utc_now()
        return datetime.combine(now.date(), time.min, tzinfo=timezone.utc)

    async def get_client_counts(self) -> Dict[str, int]:
        today_start = self._get_start_of_today_utc()
        stmt = select(
            func.count(Client.id).label("total"),
            func.count(Client.id).filter(Client.status == ClientStatus.ACTIVE).label("active"),
            func.count(Client.id).filter(Client.status == ClientStatus.SUSPENDED).label("suspended"),
            func.count(Client.id).filter(Client.status == ClientStatus.DISABLED).label("disabled"),
            func.count(Client.id).filter(Client.created_at >= today_start).label("new_today"),
        )
        res = await self.session.execute(stmt)
        row = res.one()
        return {
            "total": row.total or 0,
            "active": row.active or 0,
            "suspended": row.suspended or 0,
            "disabled": row.disabled or 0,
            "new_today": row.new_today or 0,
        }

    async def get_bot_counts(self) -> Dict[str, int]:
        today_start = self._get_start_of_today_utc()
        stmt = select(
            func.count(ClientBot.id).label("total"),
            func.count(ClientBot.id).filter(ClientBot.status == ClientBotStatus.ACTIVE).label("active"),
            func.count(ClientBot.id).filter(ClientBot.status == ClientBotStatus.PAUSED).label("paused"),
            func.count(ClientBot.id).filter(ClientBot.status == ClientBotStatus.DISCONNECTED).label("disconnected"),
            func.count(ClientBot.id).filter(ClientBot.status == ClientBotStatus.INVALID_TOKEN).label("invalid_token"),
            func.count(ClientBot.id).filter(ClientBot.status == ClientBotStatus.UNAVAILABLE).label("unavailable"),
            func.count(ClientBot.id).filter(ClientBot.status == ClientBotStatus.REVOKED).label("revoked"),
            func.count(ClientBot.id).filter(ClientBot.status == ClientBotStatus.PROVISIONING).label("provisioning"),
            func.count(ClientBot.id).filter(ClientBot.created_at >= today_start).label("new_today"),
        )
        res = await self.session.execute(stmt)
        row = res.one()
        return {
            "total": row.total or 0,
            "active": row.active or 0,
            "paused": row.paused or 0,
            "disconnected": row.disconnected or 0,
            "invalid_token": row.invalid_token or 0,
            "unavailable": row.unavailable or 0,
            "revoked": row.revoked or 0,
            "provisioning": row.provisioning or 0,
            "new_today": row.new_today or 0,
            "needs_attention": (row.invalid_token or 0) + (row.unavailable or 0) + (row.disconnected or 0),
        }

    async def get_viewer_counts(self) -> Dict[str, int]:
        today_start = self._get_start_of_today_utc()
        stmt = select(
            func.count(Viewer.id).label("total"),
            func.count(Viewer.id).filter(Viewer.status == ViewerStatus.ACTIVE).label("active"),
            func.count(Viewer.id).filter(Viewer.status == ViewerStatus.BLOCKED).label("blocked"),
            func.count(Viewer.id).filter(Viewer.first_started_at >= today_start).label("new_today"),
        )
        res = await self.session.execute(stmt)
        row = res.one()
        return {
            "total": row.total or 0,
            "active": row.active or 0,
            "blocked": row.blocked or 0,
            "new_today": row.new_today or 0,
        }

    async def get_video_counts(self) -> Dict[str, int]:
        today_start = self._get_start_of_today_utc()
        stmt = select(
            func.count(Video.id).label("total"),
            func.count(Video.id).filter(Video.status == VideoStatus.READY).label("ready"),
            func.count(Video.id).filter(
                Video.status.in_([VideoStatus.RECEIVED, VideoStatus.PROCESSING])
            ).label("processing"),
            func.count(Video.id).filter(Video.status == VideoStatus.FAILED).label("failed"),
            func.count(Video.id).filter(Video.status == VideoStatus.DISABLED).label("disabled"),
            func.count(Video.id).filter(Video.created_at >= today_start).label("created_today"),
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

    async def get_job_counts(self) -> Dict[str, int]:
        today_start = self._get_start_of_today_utc()
        stmt = select(
            func.count(BackgroundJob.id).label("total"),
            func.count(BackgroundJob.id).filter(
                BackgroundJob.status.in_([JobStatus.PENDING, JobStatus.QUEUED])
            ).label("pending"),
            func.count(BackgroundJob.id).filter(BackgroundJob.status == JobStatus.RUNNING).label("running"),
            func.count(BackgroundJob.id).filter(BackgroundJob.status == JobStatus.RETRYING).label("retrying"),
            func.count(BackgroundJob.id).filter(BackgroundJob.status == JobStatus.FAILED).label("failed"),
            func.count(BackgroundJob.id).filter(
                BackgroundJob.status == JobStatus.COMPLETED,
                BackgroundJob.completed_at >= today_start,
            ).label("completed_today"),
        )
        res = await self.session.execute(stmt)
        row = res.one()
        return {
            "total": row.total or 0,
            "pending": row.pending or 0,
            "running": row.running or 0,
            "retrying": row.retrying or 0,
            "failed": row.failed or 0,
            "completed_today": row.completed_today or 0,
        }

    async def get_broadcast_counts(self) -> Dict[str, int]:
        today_start = self._get_start_of_today_utc()
        stmt_live = select(
            func.count(Broadcast.id).label("total"),
            func.count(Broadcast.id).filter(Broadcast.status == BroadcastStatus.RUNNING).label("running"),
            func.count(Broadcast.id).filter(
                Broadcast.status.in_([BroadcastStatus.PENDING, BroadcastStatus.QUEUED])
            ).label("waiting"),
            func.count(Broadcast.id).filter(
                Broadcast.status.in_([BroadcastStatus.COMPLETED, BroadcastStatus.PARTIAL]),
                Broadcast.completed_at >= today_start,
            ).label("completed_today"),
            func.count(Broadcast.id).filter(Broadcast.status == BroadcastStatus.FAILED).label("failed"),
        ).where(Broadcast.broadcast_type == "LIVE")
        res_live = await self.session.execute(stmt_live)
        row_live = res_live.one()

        stmt_catchup = select(
            func.count(ViewerCatchup.id).label("total"),
            func.count(ViewerCatchup.id).filter(ViewerCatchup.status == CatchupStatus.RUNNING).label("running"),
            func.count(ViewerCatchup.id).filter(
                ViewerCatchup.status.in_([CatchupStatus.PENDING, CatchupStatus.PAUSED])
            ).label("waiting"),
            func.count(ViewerCatchup.id).filter(
                ViewerCatchup.status == CatchupStatus.COMPLETED,
                ViewerCatchup.completed_at >= today_start,
            ).label("completed_today"),
            func.count(ViewerCatchup.id).filter(ViewerCatchup.status == CatchupStatus.FAILED).label("failed"),
        )
        res_catchup = await self.session.execute(stmt_catchup)
        row_catchup = res_catchup.one()

        return {
            "live_running": row_live.running or 0,
            "live_waiting": row_live.waiting or 0,
            "live_completed_today": row_live.completed_today or 0,
            "live_failed": row_live.failed or 0,
            "catchup_running": row_catchup.running or 0,
            "catchup_waiting": row_catchup.waiting or 0,
            "catchup_completed_today": row_catchup.completed_today or 0,
            "catchup_failed": row_catchup.failed or 0,
        }

    async def get_system_stats(self) -> Dict[str, Any]:
        """Collects full platform-wide statistics dashboard."""
        clients = await self.get_client_counts()
        bots = await self.get_bot_counts()
        viewers = await self.get_viewer_counts()
        videos = await self.get_video_counts()
        jobs = await self.get_job_counts()
        broadcasts = await self.get_broadcast_counts()

        return {
            "clients": clients,
            "bots": bots,
            "viewers": viewers,
            "videos": videos,
            "jobs": jobs,
            "broadcasts": broadcasts,
        }
