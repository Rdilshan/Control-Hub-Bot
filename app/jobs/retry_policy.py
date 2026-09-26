"""Configurable Retry Policies and Exponential Backoff with Jitter."""

import random
from dataclasses import dataclass
from typing import Dict, Optional
from app.core.enums import JobType


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 10.0
    max_delay: float = 300.0
    backoff_multiplier: float = 2.0
    jitter: bool = True

    def calculate_delay(self, attempt_count: int, retry_after: Optional[int] = None) -> float:
        """Calculates delay in seconds for the next retry attempt."""
        if retry_after is not None and retry_after > 0:
            return min(float(retry_after), self.max_delay)

        # Exponential backoff: base_delay * (multiplier ^ (attempt - 1))
        exponent = max(0, attempt_count - 1)
        delay = self.base_delay * (self.backoff_multiplier ** exponent)

        if self.jitter:
            # Add up to 20% random jitter to avoid retry storms
            delay = delay + random.uniform(0, 0.2 * delay)

        return min(delay, self.max_delay)


DEFAULT_POLICY = RetryPolicy(
    max_attempts=3,
    base_delay=10.0,
    max_delay=300.0,
    backoff_multiplier=2.0,
    jitter=True,
)

JOB_TYPE_POLICIES: Dict[JobType, RetryPolicy] = {
    JobType.TELEGRAM_UPDATE_PROCESS: RetryPolicy(
        max_attempts=3,
        base_delay=5.0,
        max_delay=60.0,
        backoff_multiplier=2.0,
        jitter=True,
    ),
    JobType.VIDEO_PROCESS: RetryPolicy(
        max_attempts=5,
        base_delay=15.0,
        max_delay=600.0,
        backoff_multiplier=2.0,
        jitter=True,
    ),
    JobType.CREATE_UNLOCK_LINK: RetryPolicy(
        max_attempts=5,
        base_delay=10.0,
        max_delay=300.0,
        backoff_multiplier=2.0,
        jitter=True,
    ),
    JobType.UNLOCKIFY_CREATE_LINK: RetryPolicy(
        max_attempts=5,
        base_delay=10.0,
        max_delay=300.0,
        backoff_multiplier=2.0,
        jitter=True,
    ),
    JobType.BROADCAST: RetryPolicy(
        max_attempts=10,
        base_delay=10.0,
        max_delay=900.0,
        backoff_multiplier=2.0,
        jitter=True,
    ),
    JobType.OWNER_MESSAGE_CAMPAIGN: RetryPolicy(
        max_attempts=10,
        base_delay=10.0,
        max_delay=900.0,
        backoff_multiplier=2.0,
        jitter=True,
    ),
    JobType.LIVE_BROADCAST: RetryPolicy(
        max_attempts=10,
        base_delay=10.0,
        max_delay=900.0,
        backoff_multiplier=2.0,
        jitter=True,
    ),
    JobType.CATCHUP: RetryPolicy(
        max_attempts=5,
        base_delay=20.0,
        max_delay=900.0,
        backoff_multiplier=2.0,
        jitter=True,
    ),
    JobType.CATCHUP_BATCH: RetryPolicy(
        max_attempts=5,
        base_delay=20.0,
        max_delay=900.0,
        backoff_multiplier=2.0,
        jitter=True,
    ),
    JobType.CLIENT_BOT_PROVISION: RetryPolicy(
        max_attempts=3,
        base_delay=10.0,
        max_delay=120.0,
        backoff_multiplier=2.0,
        jitter=True,
    ),
    JobType.CLIENT_BOT_DISCONNECT: RetryPolicy(
        max_attempts=3,
        base_delay=10.0,
        max_delay=120.0,
        backoff_multiplier=2.0,
        jitter=True,
    ),
    JobType.CLIENT_BOT_RECONNECT: RetryPolicy(
        max_attempts=3,
        base_delay=10.0,
        max_delay=120.0,
        backoff_multiplier=2.0,
        jitter=True,
    ),
}


def get_retry_policy_for_job_type(job_type: JobType) -> RetryPolicy:
    """Returns the configured RetryPolicy for the given JobType."""
    return JOB_TYPE_POLICIES.get(job_type, DEFAULT_POLICY)
