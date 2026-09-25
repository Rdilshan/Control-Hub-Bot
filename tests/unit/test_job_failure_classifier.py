"""Unit tests for JobFailureClassifier."""

import pytest
from app.core.enums import ErrorClassification, ErrorCode
from app.exceptions import (
    BotDisconnectedException,
    BotPausedException,
    InvalidBotTokenException,
    SponsorNotConfiguredException,
    UnlockifyTimeoutException,
    VideoNotReadyException,
)
from app.jobs.failure_classifier import JobFailureClassifier


def test_classify_telegram_429_retry_after():
    class TelegramRetryAfter(Exception):
        retry_after = 12

    exc = TelegramRetryAfter("Telegram says: retry after 12 seconds")
    details = JobFailureClassifier.classify(exc)

    assert details.classification == ErrorClassification.RATE_LIMITED
    assert details.error_code == ErrorCode.TELEGRAM_RATE_LIMIT
    assert details.retry_after == 12
    assert details.is_retryable is True
    assert "12s" in details.safe_message


def test_classify_telegram_blocked_user():
    exc = Exception("Forbidden: bot was blocked by the user")
    details = JobFailureClassifier.classify(exc)

    assert details.classification == ErrorClassification.BLOCKED_USER
    assert details.error_code == ErrorCode.TELEGRAM_FORBIDDEN
    assert details.is_retryable is False


def test_classify_invalid_token():
    exc = InvalidBotTokenException("Token is rejected by Telegram")
    details = JobFailureClassifier.classify(exc)

    assert details.classification == ErrorClassification.CREDENTIAL_FAILURE
    assert details.error_code == ErrorCode.INVALID_TOKEN
    assert details.is_retryable is False


def test_classify_bot_lifecycle_paused_and_disconnected():
    details_paused = JobFailureClassifier.classify(BotPausedException(1, "bot paused"))
    assert details_paused.classification == ErrorClassification.PAUSE_REQUIRED
    assert details_paused.error_code == ErrorCode.BOT_PAUSED

    details_disc = JobFailureClassifier.classify(BotDisconnectedException(1, "bot disconnected"))
    assert details_disc.classification == ErrorClassification.PAUSE_REQUIRED
    assert details_disc.error_code == ErrorCode.BOT_DISCONNECTED


def test_classify_unlockify_timeout_and_errors():
    timeout_exc = UnlockifyTimeoutException("ConnectTimeout: Unlockify did not respond")
    details_timeout = JobFailureClassifier.classify(timeout_exc)
    assert details_timeout.classification == ErrorClassification.RETRYABLE
    assert details_timeout.error_code == ErrorCode.UNLOCKIFY_TIMEOUT
    assert details_timeout.is_retryable is True

    bad_req_exc = Exception("Unlockify 400 Bad Request: malformed url")
    details_400 = JobFailureClassifier.classify(bad_req_exc)
    assert details_400.classification == ErrorClassification.NON_RETRYABLE
    assert details_400.is_retryable is False

    server_err = Exception("Unlockify 502 Bad Gateway")
    details_502 = JobFailureClassifier.classify(server_err)
    assert details_502.classification == ErrorClassification.RETRYABLE
    assert details_502.is_retryable is True


def test_classify_database_errors():
    db_conn_err = Exception("OperationalError: database connection closed")
    details = JobFailureClassifier.classify(db_conn_err)
    assert details.classification == ErrorClassification.RETRYABLE
    assert details.error_code == ErrorCode.DATABASE_TEMPORARY_ERROR
    assert details.is_retryable is True

    integrity_err = Exception("IntegrityError: foreign key violation")
    details_int = JobFailureClassifier.classify(integrity_err)
    assert details_int.classification == ErrorClassification.DATA_INTEGRITY_FAILURE
    assert details_int.error_code == ErrorCode.DATABASE_INTEGRITY_ERROR
    assert details_int.is_retryable is False
