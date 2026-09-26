"""Live Broadcast Worker for executing BROADCAST background jobs."""

from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.core.enums import JobStatus, JobType
from app.db.models.background_job import BackgroundJob
from app.db.models.broadcast import Broadcast
from app.logging_config import logger
from app.repositories.job import BackgroundJobRepository
from app.services.broadcast_service import BroadcastService


class LiveBroadcastWorker:
    """Worker for executing queued LIVE broadcast background jobs."""

    def __init__(
        self,
        session: AsyncSession,
        broadcast_service: Optional[BroadcastService] = None,
    ):
        self.session = session
        self.job_repo = BackgroundJobRepository(session)
        self.service = broadcast_service or BroadcastService(session)

    async def get_pending_jobs(self, limit: int = 10) -> List[BackgroundJob]:
        """Fetches pending BROADCAST jobs ready to run."""
        stmt = (
            select(BackgroundJob)
            .where(
                BackgroundJob.job_type == JobType.BROADCAST,
                BackgroundJob.status.in_([JobStatus.PENDING, JobStatus.RETRYING]),
            )
            .order_by(BackgroundJob.scheduled_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def claim_jobs(self, limit: Optional[int] = None) -> List[BackgroundJob]:
        """Claims runnable broadcast jobs with multi-worker and per-bot safety."""
        settings = get_settings()
        claim_limit = limit or getattr(settings, "BROADCAST_WORKER_CLAIM_LIMIT", 5)
        jobs = await self.job_repo.claim_runnable_broadcast_jobs(limit=claim_limit)
        await self.session.commit()
        return jobs

    async def process_job(self, job_id: int) -> Dict[str, Any]:
        """Executes a single LIVE broadcast background job."""
        job = await self.job_repo.get_by_id(job_id)
        if not job:
            logger.warning("Job id=%d not found", job_id)
            return {"ok": False, "error": "job_not_found"}

        broadcast_id = job.broadcast_id or (job.payload or {}).get("broadcast_id")
        if not broadcast_id:
            logger.error("Job id=%d missing broadcast_id in payload", job_id)
            await self.job_repo.mark_failed(job_id, "MISSING_BROADCAST_ID", "No broadcast_id in job payload")
            await self.session.commit()
            return {"ok": False, "error": "MISSING_BROADCAST_ID"}

        if job.status != JobStatus.RUNNING:
            await self.job_repo.mark_running(job_id)
            broadcast = await self.session.get(Broadcast, broadcast_id)
            if broadcast:
                from app.core.enums import BroadcastStatus

                broadcast.status = BroadcastStatus.RUNNING
                if not broadcast.started_at:
                    from app.core.utils import utc_now

                    broadcast.started_at = utc_now()
            await self.session.commit()

        try:
            result = await self.service.run_broadcast(broadcast_id)
            if result.get("ok"):
                await self.job_repo.mark_completed(job_id)
            else:
                error_code = result.get("error", "BROADCAST_FAILED")
                error_message = result.get("message", "Broadcast dispatch failed")
                await self.job_repo.mark_failed(job_id, error_code, error_message)
            await self.session.commit()
            return result
        except Exception as exc:
            logger.exception("Unexpected error executing broadcast job id=%d: %s", job_id, exc)
            await self.job_repo.mark_failed(job_id, "UNEXPECTED_ERROR", str(exc))
            await self.session.commit()
            return {"ok": False, "error": "UNEXPECTED_ERROR", "message": str(exc)}
