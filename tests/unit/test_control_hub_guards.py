"""Unit tests for Control Hub permission and chat guards."""

from unittest.mock import AsyncMock
import pytest
from app.core.enums import ControlHubRole
from app.services.control_hub_service import ControlHubService
from app.telegram.control_hub import guards


def test_is_private_chat():
    assert guards.is_private_chat("private") is True
    assert guards.is_private_chat("group") is False
    assert guards.is_private_chat("supergroup") is False
    assert guards.is_private_chat("channel") is False
    assert guards.is_private_chat(None) is False
    assert guards.is_private_chat("") is False


@pytest.mark.asyncio
async def test_is_platform_owner():
    service = AsyncMock(spec=ControlHubService)

    # Owner
    service.resolve_role.return_value = ControlHubRole.PLATFORM_OWNER
    assert await guards.is_platform_owner(service, 100) is True

    # Client
    service.resolve_role.return_value = ControlHubRole.CLIENT
    assert await guards.is_platform_owner(service, 200) is False

    # New Client
    service.resolve_role.return_value = ControlHubRole.NEW_CLIENT
    assert await guards.is_platform_owner(service, 300) is False


@pytest.mark.asyncio
async def test_is_client():
    service = AsyncMock(spec=ControlHubService)

    # Owner
    service.resolve_role.return_value = ControlHubRole.PLATFORM_OWNER
    assert await guards.is_client(service, 100) is False

    # Client
    service.resolve_role.return_value = ControlHubRole.CLIENT
    assert await guards.is_client(service, 200) is True

    # New Client
    service.resolve_role.return_value = ControlHubRole.NEW_CLIENT
    assert await guards.is_client(service, 300) is True
