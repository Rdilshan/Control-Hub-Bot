"""Lifecycle Worker Module and Tasks."""

from typing import Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.background_job import BackgroundJob
from app.workers.lifecycle_worker import LifecycleWorker


async def process_lifecycle_job(
    session: AsyncSession,
    job: BackgroundJob,
    http_client: Optional[Any] = None,
) -> bool:
    """Executes a lifecycle background job."""
    worker = LifecycleWorker(session)
    return await worker.execute_job(job, http_client=http_client)


async def process_lifecycle_reconciliation(
    session: AsyncSession,
    http_client: Optional[Any] = None,
) -> Any:
    """Runs lifecycle health reconciliation across client bots."""
    worker = LifecycleWorker(session)
    return await worker.health_service.reconcile_lifecycle(http_client=http_client)


__all__ = [
    "LifecycleWorker",
    "process_lifecycle_job",
    "process_lifecycle_reconciliation",
]
