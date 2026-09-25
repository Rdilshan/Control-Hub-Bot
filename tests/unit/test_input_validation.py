"""Unit tests for InputValidationService."""

import pytest
from app.exceptions import ValidationError
from app.security.validation import InputValidationService


def test_sponsor_url_validation_valid():
    valid_urls = [
        "https://example.com/sponsor",
        "http://sponsor.org/offer?id=123",
        "https://sub.domain.co.uk/path/to/page#section",
    ]
    for url in valid_urls:
        validated = InputValidationService.validate_sponsor_url(url)
        assert validated == url


def test_sponsor_url_validation_invalid_schemes():
    invalid_urls = [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "data:text/html,<script>alert(1)</script>",
        "ftp://ftp.example.com/file",
        "customscheme://test",
    ]
    for url in invalid_urls:
        with pytest.raises(ValidationError):
            InputValidationService.validate_sponsor_url(url)


def test_sponsor_url_validation_localhost():
    invalid_hosts = [
        "http://localhost/admin",
        "http://127.0.0.1:8000/test",
        "https://0.0.0.0/attack",
    ]
    for url in invalid_hosts:
        with pytest.raises(ValidationError):
            InputValidationService.validate_sponsor_url(url)


def test_sponsor_url_validation_length_and_control_chars():
    long_url = "https://example.com/" + "a" * 2100
    with pytest.raises(ValidationError):
        InputValidationService.validate_sponsor_url(long_url)

    ctrl_url = "https://example.com/bad\x00path"
    with pytest.raises(ValidationError):
        InputValidationService.validate_sponsor_url(ctrl_url)


def test_start_and_default_message_validation():
    valid_text = "Welcome to our exclusive channel bot!"
    assert InputValidationService.validate_start_message(valid_text) == valid_text
    assert InputValidationService.validate_default_message(valid_text) == valid_text

    with pytest.raises(ValidationError):
        InputValidationService.validate_start_message("")

    with pytest.raises(ValidationError):
        InputValidationService.validate_default_message("")

    oversized = "a" * 3500
    with pytest.raises(ValidationError):
        InputValidationService.validate_start_message(oversized)


def test_bot_token_format_validation():
    assert InputValidationService.validate_bot_token_format("123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ1234567") is True
    assert InputValidationService.validate_bot_token_format("invalid_token_format") is False
    assert InputValidationService.validate_bot_token_format("") is False
    assert InputValidationService.validate_bot_token_format(None) is False
