"""Background Job Repository."""

from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import JobStatus, JobType
from app.core.utils import utc_now
from app.db.models.background_job import BackgroundJob
from app.repositories.base import BaseRepository


class BackgroundJobRepository(BaseRepository[BackgroundJob]):
    def __init__(self, session: AsyncSession):
        super().__init__(BackgroundJob, session)

    async def get_by_id(self, job_id: int) -> Optional[BackgroundJob]:
        stmt = select(BackgroundJob).where(BackgroundJob.id == job_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_job(
        self,
        job_type: JobType,
        payload: Dict[str, Any],
        client_id: Optional[int] = None,
        client_bot_id: Optional[int] = None,
        video_id: Optional[int] = None,
        broadcast_id: Optional[int] = None,
        queue_name: str = "default",
        max_attempts: int = 3,
    ) -> BackgroundJob:
        job = BackgroundJob(
            job_type=job_type,
            client_id=client_id,
            client_bot_id=client_bot_id,
            video_id=video_id,
            broadcast_id=broadcast_id,
            queue_name=queue_name,
            max_attempts=max_attempts,
            payload=payload,
            status=JobStatus.PENDING,
            scheduled_at=utc_now(),
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def mark_running(self, job_id: int) -> Optional[BackgroundJob]:
        job = await self.get_by_id(job_id)
        if job:
            job.status = JobStatus.RUNNING
            job.started_at = utc_now()
            job.attempt_count += 1
            await self.session.flush()
        return job

    async def mark_completed(self, job_id: int) -> Optional[BackgroundJob]:
        job = await self.get_by_id(job_id)
        if job:
            job.status = JobStatus.COMPLETED
            job.completed_at = utc_now()
            await self.session.flush()
        return job

    async def mark_failed(
        self,
        job_id: int,
        error_code: str,
        error_message: str,
    ) -> Optional[BackgroundJob]:
        job = await self.get_by_id(job_id)
        if job:
            job.last_error_code = error_code
            job.last_error_message = error_message
            if job.attempt_count < job.max_attempts:
                job.status = JobStatus.RETRYING
            else:
                job.status = JobStatus.FAILED
                job.completed_at = utc_now()
            await self.session.flush()
        return job

    async def list_by_bot(
        self,
        client_bot_id: int,
        limit: int = 50,
        offset: int = 0,
    ) -> List[BackgroundJob]:
        stmt = (
            select(BackgroundJob)
            .where(BackgroundJob.client_bot_id == client_bot_id)
            .order_by(BackgroundJob.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
