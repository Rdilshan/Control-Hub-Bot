"""Durable Job Dispatcher with Multi-Tenant Fairness and Broker Resilience."""

import logging
from typing import Any, Callable, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import JobStatus, JobType
from app.core.utils import utc_now
from app.db.models.background_job import BackgroundJob
from app.jobs.fairness import FairSchedulingService
from app.jobs.routing import QueueRoutingService
from app.repositories.job import BackgroundJobRepository

logger = logging.getLogger(__name__)


class JobDispatcher:
    """Dispatches durable jobs from PostgreSQL to background execution queues safely."""

    def __init__(
        self,
        session: AsyncSession,
        fairness_service: Optional[FairSchedulingService] = None,
        task_publisher: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
    ):
        self.session = session
        self.job_repo = BackgroundJobRepository(session)
        self.fairness_service = fairness_service or FairSchedulingService()
        self.task_publisher = task_publisher

    async def dispatch_due_jobs(
        self,
        limit: int = 50,
        job_type: Optional[JobType] = None,
    ) -> List[BackgroundJob]:
        """Scans due PENDING/RETRYING jobs, applies fairness, claims them atomically, and enqueues them."""
        # 1. Fetch due pending jobs
        pending_jobs = await self.job_repo.get_pending_jobs(job_type=job_type, limit=limit)
        if not pending_jobs:
            return []

        # 2. Reorder for fairness across tenants
        fair_jobs = self.fairness_service.reorder_for_fairness(pending_jobs)

        dispatched: List[BackgroundJob] = []
        now = utc_now()

        for job in fair_jobs:
            # Map queue and priority
            queue_name = QueueRoutingService.get_queue_for_job_type(job.job_type)
            job.queue_name = queue_name
            job.status = JobStatus.QUEUED
            job.queued_at = now

            if self.task_publisher:
                try:
                    payload = dict(job.payload or {})
                    payload["job_id"] = job.id
                    payload["job_type"] = job.job_type
                    payload["client_bot_id"] = job.client_bot_id
                    self.task_publisher(queue_name, payload)
                except Exception as exc:
                    logger.warning(
                        "Broker publish failed for job %s (type=%s): %s. Reverting to PENDING.",
                        job.id,
                        job.job_type,
                        exc,
                    )
                    # Broker down: do not mark FAILED. Keep PENDING for next dispatch.
                    job.status = JobStatus.PENDING
                    job.queued_at = None
                    continue

            dispatched.append(job)

        await self.session.flush()
        return dispatched
