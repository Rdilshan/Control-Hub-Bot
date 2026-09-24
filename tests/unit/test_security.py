"""Unit tests for security, secret masking, and comparison utilities."""

from app.core.security import mask_bot_token, mask_secret, verify_constant_time


def test_mask_bot_token():
    token = "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
    masked = mask_bot_token(token)
    assert masked == "123456789:***REDACTED***"
    assert "ABCdef" not in masked


def test_mask_secret():
    secret = "my_super_secret_internal_key_value"
    masked = mask_secret(secret, visible_prefix=3, visible_suffix=3)
    assert masked.startswith("my_")
    assert masked.endswith("lue")
    assert "super_secret" not in masked


def test_mask_empty_secret():
    assert mask_secret(None) == "[EMPTY]"
    assert mask_bot_token("") == "[NO_TOKEN]"


def test_verify_constant_time():
    assert verify_constant_time("secret123", "secret123") is True
    assert verify_constant_time("secret123", "wrongsecret") is False
    assert verify_constant_time(None, "secret") is False
    assert verify_constant_time("secret", None) is False
