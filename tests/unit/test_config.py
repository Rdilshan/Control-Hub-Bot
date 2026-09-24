"""Unit tests for configuration validation."""

import pytest
from pydantic import ValidationError
from app.config import Settings
from app.core.enums import Environment


def test_development_config():
    """Development settings allow debug mode and optional bot tokens."""
    settings = Settings(
        APP_ENV=Environment.DEVELOPMENT,
        APP_DEBUG=True,
    )
    assert settings.is_development
    assert not settings.is_production
    assert settings.APP_DEBUG is True


def test_production_config_rejects_debug():
    """Production mode must reject APP_DEBUG=True."""
    with pytest.raises(ValidationError):
        Settings(
            APP_ENV=Environment.PRODUCTION,
            APP_DEBUG=True,
            CONTROL_HUB_BOT_TOKEN="123456789:VALID_TOKEN",
            INTERNAL_API_SECRET="secret",
        )


def test_production_config_requires_token():
    """Production mode must require CONTROL_HUB_BOT_TOKEN."""
    with pytest.raises(ValidationError):
        Settings(
            APP_ENV=Environment.PRODUCTION,
            APP_DEBUG=False,
            CONTROL_HUB_BOT_TOKEN=None,
            INTERNAL_API_SECRET="secret",
        )


def test_production_config_requires_internal_secret():
    """Production mode must require INTERNAL_API_SECRET."""
    with pytest.raises(ValidationError):
        Settings(
            APP_ENV=Environment.PRODUCTION,
            APP_DEBUG=False,
            CONTROL_HUB_BOT_TOKEN="123456789:VALID_TOKEN",
            INTERNAL_API_SECRET=None,
        )


def test_valid_production_config():
    """Valid production config succeeds."""
    settings = Settings(
        APP_ENV=Environment.PRODUCTION,
        APP_DEBUG=False,
        CONTROL_HUB_BOT_TOKEN="123456789:VALID_TOKEN",
        INTERNAL_API_SECRET="secret1234",
    )
    assert settings.is_production
    assert not settings.APP_DEBUG
