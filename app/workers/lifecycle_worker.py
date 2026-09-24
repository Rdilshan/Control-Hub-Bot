"""Lifecycle Background Worker for asynchronous bot disconnect, health, and resume coordination."""

from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import JobStatus, JobType
from app.db.models.background_job import BackgroundJob
from app.logging_config import logger
from app.repositories.job import BackgroundJobRepository
from app.services.client_bot_health_service import ClientBotHealthService
from app.services.client_bot_lifecycle_service import ClientBotLifecycleService


class LifecycleWorker:
    """Processes background jobs related to Client Bot lifecycle transitions and maintenance."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.job_repo = BackgroundJobRepository(session)
        self.lifecycle_service = ClientBotLifecycleService(session)
        self.health_service = ClientBotHealthService(session)

    async def execute_job(self, job: BackgroundJob, http_client: Optional[Any] = None) -> bool:
        """Executes a single lifecycle background job."""
        job.status = JobStatus.RUNNING
        await self.session.flush()

        payload = getattr(job, "payload", None) or getattr(job, "payload_json", None) or {}
        bot_id = job.client_bot_id or payload.get("client_bot_id")

        try:
            if job.job_type == JobType.CLIENT_BOT_DISCONNECT:
                success, msg = await self.lifecycle_service.complete_disconnect(bot_id, http_client=http_client)
                if not success:
                    raise Exception(msg)

            elif job.job_type == JobType.CLIENT_BOT_HEALTH_CHECK:
                success, msg, details = await self.health_service.check_bot_health(bot_id, http_client=http_client)

            elif job.job_type == JobType.CLIENT_BOT_RESUME_WORK:
                counts = await self.lifecycle_service.resume_bot_work(bot_id)

            elif job.job_type == JobType.CLIENT_BOT_LIFECYCLE_RECONCILE:
                res = await self.health_service.reconcile_lifecycle(http_client=http_client)

            else:
                logger.warning(f"LifecycleWorker received unrecognized job type: {job.job_type}")

            job.status = JobStatus.COMPLETED
            await self.session.flush()
            return True

        except Exception as exc:
            logger.exception(f"LifecycleWorker failed executing job #{job.id} ({job.job_type}): {exc}")
            job.status = JobStatus.FAILED
            job.last_error_message = str(exc)
            await self.session.flush()
            return False
