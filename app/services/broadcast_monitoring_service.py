"""Broadcast Monitoring Service providing LIVE & Catch-Up broadcast progress and observability."""

from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import BroadcastStatus, CatchupStatus
from app.core.utils import utc_now
from app.db.models.broadcast import Broadcast
from app.db.models.client_bot import ClientBot
from app.db.models.viewer_catchup import ViewerCatchup
from app.logging_config import get_logger
from app.repositories.broadcast import BroadcastRepository

logger = get_logger(__name__)

DEFAULT_STALE_BROADCAST_THRESHOLD_SECONDS = 1800  # 30 minutes


class BroadcastMonitoringService:
    """Monitors live broadcasts and catch-up delivery campaigns."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.broadcast_repo = BroadcastRepository(session)

    def _get_start_of_today_utc(self) -> datetime:
        now = utc_now()
        return datetime.combine(now.date(), time.min, tzinfo=timezone.utc)

    async def get_broadcast_summary(self, client_bot_id: Optional[int] = None) -> Dict[str, Any]:
        """Provides high-level summary of LIVE and Catch-Up broadcasts."""
        today_start = self._get_start_of_today_utc()

        # LIVE Query
        stmt_live = select(
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

        if client_bot_id is not None:
            stmt_live = stmt_live.where(Broadcast.client_bot_id == client_bot_id)

        res_live = await self.session.execute(stmt_live)
        row_live = res_live.one()

        # Catch-Up Query
        stmt_catchup = select(
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
        if client_bot_id is not None:
            stmt_catchup = stmt_catchup.where(ViewerCatchup.client_bot_id == client_bot_id)

        res_catchup = await self.session.execute(stmt_catchup)
        row_catchup = res_catchup.one()

        return {
            "live": {
                "running": row_live.running or 0,
                "waiting": row_live.waiting or 0,
                "completed_today": row_live.completed_today or 0,
                "failed": row_live.failed or 0,
            },
            "catchup": {
                "running": row_catchup.running or 0,
                "waiting": row_catchup.waiting or 0,
                "completed_today": row_catchup.completed_today or 0,
                "failed": row_catchup.failed or 0,
                "blocked": row_catchup.blocked or 0,
            },
        }

    async def get_broadcast_detail(self, broadcast_id: int) -> Optional[Dict[str, Any]]:
        """Calculates granular broadcast progress metrics with percentage calculation."""
        broadcast = await self.broadcast_repo.get_by_id(broadcast_id)
        if not broadcast:
            return None

        bot = await self.session.get(ClientBot, broadcast.client_bot_id)

        total = broadcast.total_targets or 0
        sent = broadcast.sent_count or 0
        blocked = broadcast.blocked_count or 0
        failed = broadcast.failed_count or 0
        processed = sent + blocked + failed
        remaining = max(0, total - processed)

        percentage = round((processed / total * 100), 2) if total > 0 else 0.0

        return {
            "broadcast": broadcast,
            "bot": bot,
            "total_targets": total,
            "sent": sent,
            "blocked": blocked,
            "failed": failed,
            "processed": processed,
            "remaining": remaining,
            "progress_percentage": percentage,
        }

    async def list_broadcasts_paginated(
        self,
        client_bot_id: Optional[int] = None,
        status: Optional[BroadcastStatus] = None,
        page: int = 1,
        page_size: int = 10,
    ) -> Tuple[List[Dict[str, Any]], int, int]:
        """Lists broadcasts with pagination."""
        count_stmt = select(func.count(Broadcast.id))
        query_stmt = select(Broadcast).order_by(Broadcast.created_at.desc())

        if client_bot_id is not None:
            count_stmt = count_stmt.where(Broadcast.client_bot_id == client_bot_id)
            query_stmt = query_stmt.where(Broadcast.client_bot_id == client_bot_id)

        if status:
            count_stmt = count_stmt.where(Broadcast.status == status)
            query_stmt = query_stmt.where(Broadcast.status == status)

        total_res = await self.session.execute(count_stmt)
        total_count = total_res.scalar() or 0

        total_pages = max(1, (total_count + page_size - 1) // page_size) if total_count > 0 else 1
        offset = max(0, (page - 1) * page_size)

        query_stmt = query_stmt.limit(page_size).offset(offset)
        result = await self.session.execute(query_stmt)
        bcasts = list(result.scalars().all())

        items = []
        for b in bcasts:
            bot = await self.session.get(ClientBot, b.client_bot_id)
            items.append({
                "broadcast": b,
                "bot": bot,
            })

        return items, total_count, total_pages

    async def detect_stale_broadcasts(
        self, threshold_seconds: int = DEFAULT_STALE_BROADCAST_THRESHOLD_SECONDS
    ) -> List[Broadcast]:
        """Detects broadcasts running for longer than threshold."""
        cutoff = utc_now() - timedelta(seconds=threshold_seconds)
        stmt = (
            select(Broadcast)
            .where(
                Broadcast.status == BroadcastStatus.RUNNING,
                Broadcast.started_at < cutoff,
            )
            .order_by(Broadcast.started_at.asc())
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())
