"""Unit tests for SecretRedactionService."""

from app.security.redaction import SecretRedactionService


def test_redact_bot_token_in_string():
    raw_text = "Bot error with token 123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ1234567 failed to start"
    redacted = SecretRedactionService.redact_string(raw_text)

    assert "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ1234567" not in redacted
    assert "[REDACTED]" in redacted


def test_mask_bot_token():
    token = "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ1234567"
    masked = SecretRedactionService.mask_token(token)

    assert masked.startswith("1234")
    assert masked.endswith("4567")
    assert "********" in masked


def test_redact_nested_dictionary():
    payload = {
        "user_id": 123,
        "token": "secret_token_val",
        "bot_token": "987654321:abcdefghijABCDEFGHIJ12345678901234",
        "nested": {
            "password": "my_password",
            "safe_field": "public_data",
            "message": "Calling bot with 123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ1234567 now",
        },
        "list_data": [
            {"api_key": "sensitive_api_key"},
            "Plain text without secrets",
        ],
    }

    cleaned = SecretRedactionService.redact_data(payload)

    assert cleaned["token"] == "[REDACTED]"
    assert cleaned["bot_token"] == "[REDACTED]"
    assert cleaned["nested"]["password"] == "[REDACTED]"
    assert cleaned["nested"]["safe_field"] == "public_data"
    assert "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ1234567" not in cleaned["nested"]["message"]
    assert "[REDACTED]" in cleaned["nested"]["message"]
    assert cleaned["list_data"][0]["api_key"] == "[REDACTED]"
    assert cleaned["list_data"][1] == "Plain text without secrets"
