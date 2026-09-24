"""Client Bot Telegram Webhook Dynamic Dispatcher Route."""

from typing import Any, Dict, Optional
from fastapi import APIRouter, Body, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_constant_time
from app.db.session import get_db
from app.exceptions import ForbiddenError, NotFoundError
from app.logging_config import get_logger
from app.repositories.client_bot import ClientBotRepository
from app.services.bot_token_encryption_service import BotTokenEncryptionService
from app.telegram.client_bot.dispatcher import ClientBotDispatcher

logger = get_logger(__name__)

router = APIRouter(tags=["Client Bot Webhook"])


@router.post("/webhooks/telegram/client/{public_id}", status_code=status.HTTP_200_OK)
async def handle_client_bot_webhook(
    public_id: str,
    update: Dict[str, Any] = Body(...),
    x_telegram_bot_api_secret_token: Optional[str] = Header(None, alias="X-Telegram-Bot-Api-Secret-Token"),
    session: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Receives and processes incoming Telegram webhook updates for a connected Client Bot."""
    bot_repo = ClientBotRepository(session)
    bot = await bot_repo.get_by_public_id(public_id)
    if not bot:
        logger.warning(f"Rejected webhook update: No Client Bot found for public_id '{public_id}'")
        raise NotFoundError("Client bot not found")

    # Validate secret token if configured on the bot
    if bot.webhook_secret_encrypted:
        encryption_service = BotTokenEncryptionService()
        expected_secret = encryption_service.decrypt_token(bot.webhook_secret_encrypted)
        if expected_secret:
            if not x_telegram_bot_api_secret_token or not verify_constant_time(
                x_telegram_bot_api_secret_token, expected_secret
            ):
                logger.warning(f"Rejected webhook update for bot #{bot.id}: Invalid secret token")
                raise ForbiddenError("Invalid Telegram webhook secret token")

    dispatcher = ClientBotDispatcher(bot=bot)
    result = await dispatcher.process_update(update=update, session=session)
    return {"ok": True, "result": result}
