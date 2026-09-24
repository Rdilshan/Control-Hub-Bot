"""Queue Monitoring Service for durable PostgreSQL and Redis broker queue visibility."""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import JobStatus, JobType
from app.core.utils import utc_now
from app.db.models.background_job import BackgroundJob
from app.logging_config import get_logger
from app.redis.client import get_redis

logger = get_logger(__name__)

# Configurable Backlog Thresholds
VIDEO_PROCESS_WARN_THRESHOLD = 50
BROADCAST_WARN_THRESHOLD = 20
CATCHUP_WARN_THRESHOLD = 1000
QUEUE_OLDEST_WARN_SECONDS = 300  # 5 minutes


class QueueMonitoringService:
    """Monitors job queue pressure, durable pending states, and broker depth."""

    def __init__(self, session: AsyncSession):
        self.session = session

    def _format_age(self, delta_seconds: int) -> str:
        if delta_seconds < 60:
            return f"{delta_seconds}s"
        elif delta_seconds < 3600:
            return f"{delta_seconds // 60}m {delta_seconds % 60}s"
        else:
            return f"{delta_seconds // 3600}h {(delta_seconds % 3600) // 60}m"

    async def get_durable_job_counts(self) -> Dict[str, int]:
        """Calculates durable PostgreSQL pending/queued/retrying job counts by category."""
        stmt = (
            select(
                func.count(BackgroundJob.id).filter(
                    BackgroundJob.job_type == JobType.VIDEO_PROCESS,
                    BackgroundJob.status.in_([JobStatus.PENDING, JobStatus.QUEUED]),
                ).label("video_processing"),
                func.count(BackgroundJob.id).filter(
                    BackgroundJob.job_type == JobType.CREATE_UNLOCK_LINK,
                    BackgroundJob.status.in_([JobStatus.PENDING, JobStatus.QUEUED]),
                ).label("unlock_links"),
                func.count(BackgroundJob.id).filter(
                    BackgroundJob.job_type == JobType.BROADCAST,
                    BackgroundJob.status.in_([JobStatus.PENDING, JobStatus.QUEUED]),
                ).label("broadcasts"),
                func.count(BackgroundJob.id).filter(
                    BackgroundJob.job_type == JobType.CATCHUP,
                    BackgroundJob.status.in_([JobStatus.PENDING, JobStatus.QUEUED]),
                ).label("catchup"),
                func.count(BackgroundJob.id).filter(
                    BackgroundJob.status == JobStatus.RETRYING
                ).label("retrying"),
            )
        )
        res = await self.session.execute(stmt)
        row = res.one()

        return {
            "video_processing": row.video_processing or 0,
            "unlock_links": row.unlock_links or 0,
            "broadcasts": row.broadcasts or 0,
            "catchup": row.catchup or 0,
            "retrying": row.retrying or 0,
        }

    async def get_broker_queue_depth(self) -> Dict[str, Any]:
        """Queries Redis queue length safely. If Redis is down, returns 'Unavailable'."""
        try:
            redis = get_redis()
            # Test ping
            await redis.ping()

            # Attempt to read standard queue lengths if keys exist
            video_len = await redis.llen("celery:queue:video_processing")
            bcast_len = await redis.llen("celery:queue:broadcast")
            catchup_len = await redis.llen("celery:queue:catchup")
            default_len = await redis.llen("celery")

            return {
                "available": True,
                "video_processing": video_len,
                "broadcast": bcast_len,
                "catchup": catchup_len,
                "default": default_len,
            }
        except Exception as exc:
            logger.debug(f"Redis broker queue depth unavailable: {exc}")
            return {
                "available": False,
                "video_processing": "Unavailable",
                "broadcast": "Unavailable",
                "catchup": "Unavailable",
                "default": "Unavailable",
            }

    async def get_oldest_waiting_age(self) -> Dict[str, str]:
        """Calculates oldest waiting job ages per job type and globally."""
        now = utc_now()

        stmt = (
            select(
                BackgroundJob.job_type,
                func.min(BackgroundJob.scheduled_at).label("oldest_scheduled"),
            )
            .where(BackgroundJob.status.in_([JobStatus.PENDING, JobStatus.RETRYING]))
            .group_by(BackgroundJob.job_type)
        )
        res = await self.session.execute(stmt)
        rows = res.all()

        oldest_by_type: Dict[str, str] = {}
        global_oldest_seconds = 0

        for row in rows:
            if row.oldest_scheduled:
                scheduled = (
                    row.oldest_scheduled.replace(tzinfo=timezone.utc)
                    if row.oldest_scheduled.tzinfo is None
                    else row.oldest_scheduled
                )
                age_secs = max(0, int((now - scheduled).total_seconds()))
                if age_secs > global_oldest_seconds:
                    global_oldest_seconds = age_secs
                job_key = row.job_type.value if hasattr(row.job_type, "value") else str(row.job_type)
                oldest_by_type[job_key] = self._format_age(age_secs)

        oldest_str = self._format_age(global_oldest_seconds) if global_oldest_seconds > 0 else "None"

        return {
            "global": oldest_str,
            "global_seconds": str(global_oldest_seconds),
            "by_type": oldest_by_type,
        }

    async def get_queue_summary(self) -> Dict[str, Any]:
        """Generates full /queue monitoring dashboard."""
        durable = await self.get_durable_job_counts()
        broker = await self.get_broker_queue_depth()
        oldest = await self.get_oldest_waiting_age()

        # Determine health status
        oldest_secs = int(oldest.get("global_seconds", "0"))
        is_critical = (
            durable["video_processing"] > VIDEO_PROCESS_WARN_THRESHOLD * 2
            or durable["broadcasts"] > BROADCAST_WARN_THRESHOLD * 2
            or durable["catchup"] > CATCHUP_WARN_THRESHOLD * 2
            or oldest_secs > QUEUE_OLDEST_WARN_SECONDS * 2
        )
        is_warning = (
            durable["video_processing"] > VIDEO_PROCESS_WARN_THRESHOLD
            or durable["broadcasts"] > BROADCAST_WARN_THRESHOLD
            or durable["catchup"] > CATCHUP_WARN_THRESHOLD
            or oldest_secs > QUEUE_OLDEST_WARN_SECONDS
        )

        status_label = "🚨 Critical" if is_critical else ("⚠️ Backlog" if is_warning else "✅ Healthy")

        return {
            "status_label": status_label,
            "durable": durable,
            "broker": broker,
            "oldest_waiting": oldest.get("global", "None"),
            "oldest_by_type": oldest.get("by_type", {}),
        }
