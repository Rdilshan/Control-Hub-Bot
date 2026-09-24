"""Application Lifespan lifecycle management."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI
from app.config import get_settings
from app.core.security import mask_bot_token
from app.db.session import close_db_engine, init_db_engine, check_db_health
from app.logging_config import get_logger, setup_logging
from app.redis.client import close_redis, init_redis, check_redis_health
from app.telegram.client import validate_bot_token

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manages application startup and graceful shutdown."""
    settings = get_settings()

    # 1. Setup structured logging
    setup_logging(settings.LOG_LEVEL)
    logger.info(
        f"Starting {settings.APP_NAME} in [{settings.APP_ENV.value}] mode (Debug: {settings.APP_DEBUG})"
    )

    # 2. Initialize PostgreSQL
    try:
        init_db_engine(settings.DATABASE_URL)
        db_healthy = await check_db_health()
        if db_healthy:
            logger.info("PostgreSQL database connection verified successfully")
        else:
            logger.warning("PostgreSQL database connection could not be verified on startup")
    except Exception as exc:
        logger.error(f"Failed to initialize PostgreSQL on startup: {exc}")
        if settings.is_production:
            raise

    # 3. Initialize Redis
    try:
        init_redis(settings.REDIS_URL)
        redis_healthy = await check_redis_health()
        if redis_healthy:
            logger.info("Redis connection verified successfully")
        else:
            logger.warning("Redis connection could not be verified on startup")
    except Exception as exc:
        logger.error(f"Failed to initialize Redis on startup: {exc}")
        if settings.is_production:
            raise

    # 4. Initialize Telegram Bot token verification if provided
    if settings.CONTROL_HUB_BOT_TOKEN:
        masked_tok = mask_bot_token(settings.CONTROL_HUB_BOT_TOKEN)
        try:
            bot_info = await validate_bot_token(settings.CONTROL_HUB_BOT_TOKEN)
            logger.info(f"Control Hub Telegram bot verified: @{bot_info.username} (id: {bot_info.id})")
        except Exception as exc:
            logger.error(f"Failed to verify Control Hub Telegram bot ({masked_tok}): {exc}")
            if settings.is_production:
                raise

    logger.info(f"{settings.APP_NAME} backend application is READY")

    yield

    # --- Graceful Shutdown Sequence ---
    logger.info("Initiating graceful shutdown sequence...")

    # 1. Close Redis
    try:
        await close_redis()
    except Exception as exc:
        logger.warning(f"Error during Redis close: {exc}")

    # 2. Dispose PostgreSQL Engine
    try:
        await close_db_engine()
    except Exception as exc:
        logger.warning(f"Error during Database engine disposal: {exc}")

    logger.info(f"{settings.APP_NAME} backend application shutdown complete")
