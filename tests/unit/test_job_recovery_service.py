"""Unit tests for JobRecoveryService and domain reconciliation."""

from datetime import datetime, timedelta, timezone
import pytest
from app.core.enums import JobStatus, JobType, VideoStatus
from app.core.utils import utc_now
from app.db.models.video import Video
from app.jobs.recovery import JobRecoveryService
from app.repositories.job import BackgroundJobRepository


@pytest.mark.asyncio
async def test_recover_stale_running_jobs(db_session):
    job_repo = BackgroundJobRepository(db_session)
    stale_time = utc_now() - timedelta(seconds=400)

    job = await job_repo.create_job(
        job_type=JobType.VIDEO_PROCESS,
        payload={"video_id": 1},
    )
    job.status = JobStatus.RUNNING
    job.started_at = stale_time
    job.last_heartbeat_at = stale_time
    job.attempt_count = 1
    await db_session.flush()

    recovery = JobRecoveryService(db_session)
    recovered = await recovery.recover_stale_running_jobs(threshold_seconds=300)

    assert len(recovered) == 1
    assert recovered[0].id == job.id
    assert recovered[0].status == JobStatus.RETRYING


@pytest.mark.asyncio
async def test_recover_lost_queued_jobs(db_session):
    job_repo = BackgroundJobRepository(db_session)
    stale_queued_time = utc_now() - timedelta(seconds=700)

    job = await job_repo.create_job(
        job_type=JobType.BROADCAST,
        payload={"broadcast_id": 1},
    )
    job.status = JobStatus.QUEUED
    job.queued_at = stale_queued_time
    await db_session.flush()

    recovery = JobRecoveryService(db_session)
    recovered = await recovery.recover_lost_queued_jobs(threshold_seconds=600)

    assert len(recovered) == 1
    assert recovered[0].id == job.id
    assert recovered[0].status == JobStatus.PENDING


@pytest.mark.asyncio
async def test_reconcile_unprocessed_videos(db_session):
    video = Video(
        client_bot_id=1,
        source_chat_id=10,
        telegram_message_id=20,
        telegram_file_id="v_unprocessed",
        telegram_file_unique_id="uniq_unproc",
        status=VideoStatus.RECEIVED,
    )
    db_session.add(video)
    await db_session.flush()


    recovery = JobRecoveryService(db_session)
    created_jobs = await recovery.reconcile_unprocessed_videos()

    assert len(created_jobs) == 1
    assert created_jobs[0].video_id == video.id
    assert created_jobs[0].job_type == JobType.VIDEO_PROCESS
