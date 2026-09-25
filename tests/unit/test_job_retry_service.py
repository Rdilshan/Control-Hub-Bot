"""Unit tests for JobRetryService."""

import pytest
from app.core.enums import JobStatus, JobType, ProcessingStatus, VideoStatus
from app.db.models.video import Video
from app.db.models.video_processing import VideoProcessing
from app.repositories.job import BackgroundJobRepository
from app.repositories.video import VideoRepository
from app.repositories.video_processing import VideoProcessingRepository
from app.services.job_retry_service import JobRetryService


@pytest.mark.asyncio
async def test_job_retry_service_manual_retry(db_session):
    job_repo = BackgroundJobRepository(db_session)
    job = await job_repo.create_job(
        job_type=JobType.VIDEO_PROCESS,
        payload={"video_id": 10},
        client_bot_id=1,
    )
    job.status = JobStatus.FAILED

    retry_service = JobRetryService(db_session)
    success, msg, retried_job = await retry_service.retry_job(job.id, user_id=123)

    assert success is True
    assert retried_job.status == JobStatus.PENDING


@pytest.mark.asyncio
async def test_retry_video_processing_checkpoint_preservation(db_session):
    video = Video(
        client_bot_id=1,
        source_chat_id=100,
        telegram_message_id=200,
        telegram_file_id="vid_123",
        telegram_file_unique_id="uniq_123",
        status=VideoStatus.FAILED,
    )
    db_session.add(video)
    await db_session.flush()


    proc = VideoProcessing(
        video_id=video.id,
        status=ProcessingStatus.FAILED,
        thumbnail_file_id="thumb_preview_saved",
    )
    db_session.add(proc)
    await db_session.flush()


    retry_service = JobRetryService(db_session)
    success, msg, job = await retry_service.retry_video_processing(video.id, client_bot_id=1)

    assert success is True
    assert job is not None
    assert job.status == JobStatus.PENDING
    assert job.payload.get("thumbnail_file_id") == "thumb_preview_saved"
    assert video.status == VideoStatus.PROCESSING
    assert proc.status == ProcessingStatus.CREATING_UNLOCK_LINK
