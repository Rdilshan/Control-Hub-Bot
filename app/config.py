"""Application Configuration Module."""

from typing import Any, Optional
from functools import lru_cache
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.core.enums import Environment


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # General App Settings
    APP_NAME: str = "Control Hub"
    APP_ENV: Environment = Environment.DEVELOPMENT
    APP_DEBUG: bool = True
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    # PostgreSQL Configuration
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/control_hub"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30

    # Redis & Celery Configuration
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_APP_URL: Optional[str] = None
    CELERY_BROKER_URL: Optional[str] = None
    CELERY_RESULT_BACKEND: Optional[str] = None

    # Maintenance & Capacity Configuration
    MAINTENANCE_MODE: bool = False
    MAX_ACTIVE_VIDEO_PROCESSING_PER_CLIENT: int = 3
    MAX_ACTIVE_CATCHUP_PER_BOT: int = 5
    MAX_ACTIVE_CATCHUP_PER_CLIENT: int = 10

    # Telegram Bot Settings
    CONTROL_HUB_BOT_TOKEN: Optional[str] = None
    PLATFORM_OWNER_TELEGRAM_ID: Optional[int] = None
    BOT_TOKEN_ENCRYPTION_KEY: str = "dGVzdF9mZXJuZXRfa2V5XzMyX2J5dGVzX2xlbmd0aF8xMjM="  # Base64 32-byte key
    TELEGRAM_API_BASE_URL: str = "https://api.telegram.org"
    TELEGRAM_REQUEST_TIMEOUT: float = 30.0
    # Broadcast & Catch-Up Settings
    TELEGRAM_BROADCAST_RATE_PER_SECOND: float = 25.0
    BROADCAST_BATCH_SIZE: int = 500
    BROADCAST_MAX_RETRY_ATTEMPTS: int = 3
    CATCHUP_BATCH_SIZE: int = 10
    CATCHUP_BATCH_DELAY_SECONDS: float = 86_400.0  # 1 day between historical catch-up batches
    MAX_ACTIVE_CATCHUP_VIEWERS_PER_BOT: int = 5

    # Logging
    LOG_LEVEL: str = "INFO"

    # Webhook & Internal Security
    TELEGRAM_WEBHOOK_BASE_URL: Optional[str] = None
    TELEGRAM_WEBHOOK_SECRET: Optional[str] = None
    INTERNAL_API_SECRET: Optional[str] = None
    WEBHOOK_MAX_BODY_BYTES: int = 1_048_576  # 1MB max body size for telegram webhooks

    # Rate Limiting Settings
    RATE_LIMIT_VIEWER_PER_MINUTE: int = 30
    RATE_LIMIT_ADMIN_PER_MINUTE: int = 120
    RATE_LIMIT_CONNECTBOT_ATTEMPTS: int = 5

    # Video Processing & Unlockify Provider
    UNLOCKIFY_API_BASE_URL: str = "https://developer.unlockify.ink/api/v1"
    PUBLIC_APP_BASE_URL: str = "https://controlhub.example.com"

    @model_validator(mode="before")
    @classmethod
    def empty_str_to_none(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: (None if v == "" else v) for k, v in data.items()}
        return data

    @model_validator(mode="after")
    def validate_production_invariants(self) -> "Settings":
        """Enforces production strictness and security checks."""
        if self.APP_ENV == Environment.PRODUCTION:
            if self.APP_DEBUG:
                raise ValueError("APP_DEBUG cannot be True in production mode.")
            if not self.CONTROL_HUB_BOT_TOKEN:
                raise ValueError("CONTROL_HUB_BOT_TOKEN is required in production mode.")
            if not self.INTERNAL_API_SECRET:
                raise ValueError("INTERNAL_API_SECRET is required in production mode.")
            if not self.DATABASE_URL or "localhost" in self.DATABASE_URL:
                # Basic check - warning or ensure valid db
                pass
        return self

    @property
    def is_development(self) -> bool:
        return self.APP_ENV == Environment.DEVELOPMENT

    @property
    def is_testing(self) -> bool:
        return self.APP_ENV == Environment.TESTING

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == Environment.PRODUCTION


@lru_cache()
def get_settings() -> Settings:
    """Returns cached settings singleton instance."""
    return Settings()


class SettingsProxy:
    """Proxy to allow module-level `settings.FIELD` access while respecting lru_cache."""

    def __getattr__(self, item: str) -> Any:
        return getattr(get_settings(), item)


settings = SettingsProxy()
