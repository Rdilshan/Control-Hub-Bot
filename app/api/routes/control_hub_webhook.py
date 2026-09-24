"""Control Hub Telegram Webhook Route."""

from typing import Any, Dict, Optional
from fastapi import APIRouter, Body, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_db
from app.logging_config import get_logger
from app.telegram.control_hub.router import ControlHubRouter

logger = get_logger(__name__)

router = APIRouter(tags=["Telegram Webhook"])


@router.post("/webhooks/telegram/control-hub", status_code=status.HTTP_200_OK)
async def handle_control_hub_webhook(
    update: Dict[str, Any] = Body(...),
    x_telegram_bot_api_secret_token: Optional[str] = Header(None, alias="X-Telegram-Bot-Api-Secret-Token"),
    session: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Receives and processes incoming Telegram webhook updates for the Control Hub Bot."""
    settings = get_settings()

    # Secret token validation
    expected_secret = settings.TELEGRAM_WEBHOOK_SECRET
    if expected_secret:
        if not x_telegram_bot_api_secret_token or x_telegram_bot_api_secret_token != expected_secret:
            logger.warning("Rejected Telegram webhook update due to invalid or missing secret token")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid Telegram webhook secret token",
            )

    control_hub_router = ControlHubRouter()
    result = await control_hub_router.process_update(update=update, session=session)
    return {"ok": True, "result": result}
