"""Unit tests for JobDispatcher."""

import pytest
from app.core.enums import JobStatus, JobType
from app.jobs.dispatcher import JobDispatcher
from app.repositories.job import BackgroundJobRepository


@pytest.mark.asyncio
async def test_job_dispatcher_claims_and_publishes(db_session):
    job_repo = BackgroundJobRepository(db_session)
    job = await job_repo.create_job(
        job_type=JobType.VIDEO_PROCESS,
        payload={"video_id": 42},
        client_id=1,
        client_bot_id=10,
    )

    published_tasks = []

    def mock_publisher(queue: str, payload: dict):
        published_tasks.append((queue, payload))

    dispatcher = JobDispatcher(session=db_session, task_publisher=mock_publisher)
    dispatched = await dispatcher.dispatch_due_jobs()

    assert len(dispatched) == 1
    assert dispatched[0].status == JobStatus.QUEUED
    assert dispatched[0].queued_at is not None
    assert len(published_tasks) == 1
    assert published_tasks[0][0] == "video_processing"
    assert published_tasks[0][1]["video_id"] == 42


@pytest.mark.asyncio
async def test_job_dispatcher_handles_broker_outage_safely(db_session):
    job_repo = BackgroundJobRepository(db_session)
    job = await job_repo.create_job(
        job_type=JobType.BROADCAST,
        payload={"broadcast_id": 99},
        client_id=1,
    )

    def broken_publisher(queue: str, payload: dict):
        raise ConnectionError("Redis connection refused")

    dispatcher = JobDispatcher(session=db_session, task_publisher=broken_publisher)
    dispatched = await dispatcher.dispatch_due_jobs()

    # Dispatched list is empty because publish failed
    assert len(dispatched) == 0

    # Job remains PENDING in database, not lost or failed
    db_job = await job_repo.get_by_id(job.id)
    assert db_job.status == JobStatus.PENDING
    assert db_job.queued_at is None
