"""Unit tests for RetryPolicy and backoff calculation."""

from app.core.enums import JobType
from app.jobs.retry_policy import (
    RetryPolicy,
    get_retry_policy_for_job_type,
)


def test_retry_policy_exponential_backoff():
    policy = RetryPolicy(
        max_attempts=5,
        base_delay=10.0,
        max_delay=100.0,
        backoff_multiplier=2.0,
        jitter=False,
    )

    # Attempt 1: 10 * 2^0 = 10
    assert policy.calculate_delay(1) == 10.0
    # Attempt 2: 10 * 2^1 = 20
    assert policy.calculate_delay(2) == 20.0
    # Attempt 3: 10 * 2^2 = 40
    assert policy.calculate_delay(3) == 40.0
    # Attempt 4: 10 * 2^3 = 80
    assert policy.calculate_delay(4) == 80.0
    # Attempt 5: 10 * 2^4 = 160 -> capped at max_delay 100
    assert policy.calculate_delay(5) == 100.0


def test_retry_policy_with_retry_after():
    policy = RetryPolicy(max_delay=60.0)
    # retry_after should be respected directly
    assert policy.calculate_delay(attempt_count=2, retry_after=15) == 15.0
    # retry_after capped at max_delay
    assert policy.calculate_delay(attempt_count=1, retry_after=120) == 60.0


def test_job_type_policies():
    telegram_policy = get_retry_policy_for_job_type(JobType.TELEGRAM_UPDATE_PROCESS)
    assert telegram_policy.max_attempts == 3
    assert telegram_policy.max_delay <= 60.0

    video_policy = get_retry_policy_for_job_type(JobType.VIDEO_PROCESS)
    assert video_policy.max_attempts == 5
    assert video_policy.max_delay >= 300.0
