"""Permission and context guards for Control Hub Bot."""

from app.core.enums import ControlHubRole
from app.services.control_hub_service import ControlHubService


def is_private_chat(chat_type: str) -> bool:
    """Verifies that the Telegram interaction occurs inside a private chat."""
    return chat_type == "private"


async def is_platform_owner(service: ControlHubService, telegram_user_id: int) -> bool:
    """Checks whether the given Telegram user is an active Platform Owner."""
    role = await service.resolve_role(telegram_user_id)
    return role == ControlHubRole.PLATFORM_OWNER


async def is_client(service: ControlHubService, telegram_user_id: int) -> bool:
    """Checks whether the user is an authorized client."""
    role = await service.resolve_role(telegram_user_id)
    return role in (ControlHubRole.CLIENT, ControlHubRole.NEW_CLIENT)
