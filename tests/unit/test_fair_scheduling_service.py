"""Unit tests for FairSchedulingService."""

from datetime import datetime, timedelta, timezone
from app.core.enums import JobStatus, JobType
from app.core.utils import utc_now
from app.db.models.background_job import BackgroundJob
from app.jobs.fairness import FairSchedulingService


def test_fairness_reordering_round_robin():
    fairness = FairSchedulingService()

    # Create 5 jobs for Client 1 and 2 jobs for Client 2 (all same priority)
    jobs = [
        BackgroundJob(id=1, client_id=1, job_type=JobType.VIDEO_PROCESS, priority=60, scheduled_at=utc_now()),
        BackgroundJob(id=2, client_id=1, job_type=JobType.VIDEO_PROCESS, priority=60, scheduled_at=utc_now()),
        BackgroundJob(id=3, client_id=1, job_type=JobType.VIDEO_PROCESS, priority=60, scheduled_at=utc_now()),
        BackgroundJob(id=4, client_id=1, job_type=JobType.VIDEO_PROCESS, priority=60, scheduled_at=utc_now()),
        BackgroundJob(id=5, client_id=1, job_type=JobType.VIDEO_PROCESS, priority=60, scheduled_at=utc_now()),
        BackgroundJob(id=6, client_id=2, job_type=JobType.VIDEO_PROCESS, priority=60, scheduled_at=utc_now()),
        BackgroundJob(id=7, client_id=2, job_type=JobType.VIDEO_PROCESS, priority=60, scheduled_at=utc_now()),
    ]

    reordered = fairness.reorder_for_fairness(jobs)
    client_ids = [j.client_id for j in reordered]

    # Client 2 should not be starved behind 5 jobs of Client 1
    # Expected round-robin: Client 1, Client 2, Client 1, Client 2, Client 1, Client 1, Client 1
    assert client_ids[:4] == [1, 2, 1, 2]
    assert len(reordered) == 7


def test_priority_live_over_catchup():
    fairness = FairSchedulingService()

    live_job = BackgroundJob(id=1, client_id=1, job_type=JobType.BROADCAST, priority=80, scheduled_at=utc_now())
    catchup_job = BackgroundJob(id=2, client_id=1, job_type=JobType.CATCHUP, priority=30, scheduled_at=utc_now())

    reordered = fairness.reorder_for_fairness([catchup_job, live_job])
    assert reordered[0].id == live_job.id
    assert reordered[1].id == catchup_job.id


def test_concurrency_caps():
    fairness = FairSchedulingService(
        max_active_video_processing_per_client=2,
        max_active_broadcasts_per_bot=1,
    )

    job_video = BackgroundJob(id=1, client_id=10, job_type=JobType.VIDEO_PROCESS)
    # Under limit (active=1 < cap=2) -> Allowed
    assert fairness.can_dispatch_job(job_video, active_video_processing_by_client={10: 1}) is True
    # At limit (active=2 >= cap=2) -> Rejected
    assert fairness.can_dispatch_job(job_video, active_video_processing_by_client={10: 2}) is False

    job_broadcast = BackgroundJob(id=2, client_bot_id=5, job_type=JobType.BROADCAST)
    # 1 active broadcast for bot 5 -> Rejected
    assert fairness.can_dispatch_job(job_broadcast, active_broadcasts_by_bot={5: 1}) is False
    # 0 active broadcasts for bot 5 -> Allowed
    assert fairness.can_dispatch_job(job_broadcast, active_broadcasts_by_bot={5: 0}) is True
