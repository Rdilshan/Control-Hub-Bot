"""Unit tests for WebhookSecurityService."""

import pytest
from app.exceptions import ForbiddenError, ValidationError
from app.security.webhook_security import WebhookSecurityService


def test_webhook_secret_generation():
    secret1 = WebhookSecurityService.generate_webhook_secret()
    secret2 = WebhookSecurityService.generate_webhook_secret()

    assert isinstance(secret1, str)
    assert len(secret1) >= 32
    assert secret1 != secret2


def test_public_bot_id_generation():
    pub1 = WebhookSecurityService.generate_public_bot_id()
    pub2 = WebhookSecurityService.generate_public_bot_id()

    assert isinstance(pub1, str)
    assert len(pub1) >= 16
    assert pub1 != pub2


def test_webhook_secret_verification():
    secret = "my_super_secret_webhook_token_123"

    assert WebhookSecurityService.verify_webhook_secret(secret, secret) is True
    assert WebhookSecurityService.verify_webhook_secret(secret, "wrong_secret") is False
    assert WebhookSecurityService.verify_webhook_secret(None, secret) is False
    assert WebhookSecurityService.verify_webhook_secret(secret, None) is False
    assert WebhookSecurityService.verify_webhook_secret("", secret) is False


def test_webhook_secret_header_validation_exception():
    secret = "expected_token_456"

    # Should not raise on valid
    WebhookSecurityService.validate_webhook_secret_header(secret, secret)

    # Should raise ForbiddenError on mismatch
    with pytest.raises(ForbiddenError):
        WebhookSecurityService.validate_webhook_secret_header("wrong_token", secret)


def test_webhook_payload_validation():
    valid_payload = {"update_id": 123456, "message": {"text": "hello"}}
    assert WebhookSecurityService.validate_webhook_payload(valid_payload) == valid_payload

    with pytest.raises(ValidationError):
        WebhookSecurityService.validate_webhook_payload("not_a_dict")

    with pytest.raises(ValidationError):
        WebhookSecurityService.validate_webhook_payload({"missing_update_id": 123})
