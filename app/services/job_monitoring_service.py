"""Job Monitoring Service providing background job observability, stale detection, and safe reporting."""

from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import JobStatus, JobType, enum_val
from app.core.utils import utc_now
from app.db.models.background_job import BackgroundJob
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.logging_config import get_logger
from app.repositories.job import BackgroundJobRepository

logger = get_logger(__name__)

DEFAULT_STALE_JOB_THRESHOLD_SECONDS = 900  # 15 minutes


class JobMonitoringService:
    """Provides monitoring, inspection, stale job detection, and retry controls for background jobs."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.job_repo = BackgroundJobRepository(session)

    def _get_start_of_today_utc(self) -> datetime:
        now = utc_now()
        return datetime.combine(now.date(), time.min, tzinfo=timezone.utc)

    async def get_job_summary(self) -> Dict[str, Any]:
        """Returns high level summary of jobs across all statuses."""
        today_start = self._get_start_of_today_utc()

        stmt = (
            select(
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
        )
        res = await self.session.execute(stmt)
        row = res.one()

        return {
            "pending": row.pending or 0,
            "running": row.running or 0,
            "retrying": row.retrying or 0,
            "failed": row.failed or 0,
            "completed_today": row.completed_today or 0,
        }

    async def list_jobs_paginated(
        self,
        status: Optional[JobStatus] = None,
        job_type: Optional[JobType] = None,
        page: int = 1,
        page_size: int = 10,
    ) -> Tuple[List[Dict[str, Any]], int, int]:
        """Lists jobs with pagination and associated bot/client metadata."""
        jobs, total_count = await self.job_repo.list_paginated(
            status=status, job_type=job_type, page=page, page_size=page_size
        )
        total_pages = max(1, (total_count + page_size - 1) // page_size) if total_count > 0 else 1

        items = []
        for job in jobs:
            bot = await self.session.get(ClientBot, job.client_bot_id) if job.client_bot_id else None
            client = await self.session.get(Client, job.client_id) if job.client_id else None
            items.append({
                "job": job,
                "bot": bot,
                "client": client,
            })

        return items, total_count, total_pages

    async def get_job_detail(self, job_id: int) -> Optional[Dict[str, Any]]:
        """Fetches detailed info for a single job with safe error formatting."""
        job = await self.job_repo.get_by_id(job_id)
        if not job:
            return None

        bot = await self.session.get(ClientBot, job.client_bot_id) if job.client_bot_id else None
        client = await self.session.get(Client, job.client_id) if job.client_id else None

        safe_error = None
        if job.status in (JobStatus.FAILED, JobStatus.RETRYING):
            safe_error = {
                "error_code": job.last_error_code or "UNKNOWN_ERROR",
                "error_message": job.last_error_message or "An unexpected error occurred during processing.",
                "attempt_count": job.attempt_count,
                "max_attempts": job.max_attempts,
            }

        return {
            "job": job,
            "bot": bot,
            "client": client,
            "safe_error": safe_error,
            "is_retryable": job.status in (JobStatus.FAILED, JobStatus.RETRYING),
        }

    async def detect_stale_jobs(
        self, threshold_seconds: int = DEFAULT_STALE_JOB_THRESHOLD_SECONDS
    ) -> List[BackgroundJob]:
        """Detects jobs stuck in RUNNING state longer than threshold."""
        cutoff = utc_now() - timedelta(seconds=threshold_seconds)
        stmt = (
            select(BackgroundJob)
            .where(
                BackgroundJob.status == JobStatus.RUNNING,
                BackgroundJob.started_at < cutoff,
            )
            .order_by(BackgroundJob.started_at.asc())
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def retry_job(
        self, job_id: int, performed_by_owner_id: Optional[int] = None
    ) -> Tuple[bool, str, Optional[BackgroundJob]]:
        """Safely marks a failed/retrying job back to PENDING for execution."""
        success, msg, job = await self.job_repo.retry_job(job_id)
        if success:
            logger.info(
                f"Job #{job_id} retried by owner #{performed_by_owner_id or 'system'}"
            )
        return success, msg, job
