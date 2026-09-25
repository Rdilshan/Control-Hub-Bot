"""Unit tests for AuthorizationService and TenantGuardService."""

import pytest
from app.core.enums import BotStatus
from app.exceptions import ForbiddenError, NotFoundError, UnauthorizedError, BotPausedException, BotDisconnectedException
from app.security.authorization import AuthorizationService
from app.security.tenant_guard import TenantGuardService


class MockBot:
    def __init__(self, id=1, client_id=10, status=BotStatus.ACTIVE):
        self.id = id
        self.client_id = client_id
        self.status = status


class MockVideo:
    def __init__(self, id=100, client_bot_id=1):
        self.id = id
        self.client_bot_id = client_bot_id


class MockViewer:
    def __init__(self, id=200, client_bot_id=1):
        self.id = id
        self.client_bot_id = client_bot_id


class MockBroadcast:
    def __init__(self, id=300, client_bot_id=1):
        self.id = id
        self.client_bot_id = client_bot_id


class MockUnlockLink:
    def __init__(self, id=400, video_id=100):
        self.id = id
        self.video_id = video_id


def test_platform_owner_authorization():
    auth_service = AuthorizationService(platform_owner_id=999)
    assert auth_service.is_platform_owner(999) is True
    assert auth_service.is_platform_owner(123) is False

    auth_service.require_platform_owner(999)

    with pytest.raises(ForbiddenError):
        auth_service.require_platform_owner(123)


def test_client_authorization():
    auth_service = AuthorizationService(platform_owner_id=999)
    auth_service.require_client(123, client={"id": 1})

    with pytest.raises(UnauthorizedError):
        auth_service.require_client(123, client=None)


def test_client_bot_owner_authorization():
    auth_service = AuthorizationService(platform_owner_id=999)
    bot = MockBot(id=1, client_id=10)

    auth_service.require_client_bot_owner(client_id=10, client_bot=bot)

    with pytest.raises(ForbiddenError):
        auth_service.require_client_bot_owner(client_id=99, client_bot=bot)

    with pytest.raises(NotFoundError):
        auth_service.require_client_bot_owner(client_id=10, client_bot=None)


def test_client_bot_admin_authorization():
    auth_service = AuthorizationService(platform_owner_id=999)
    bot = MockBot(id=1, client_id=10)

    auth_service.require_client_bot_admin(telegram_user_id=123, client_bot=bot, is_admin=True)

    with pytest.raises(ForbiddenError):
        auth_service.require_client_bot_admin(telegram_user_id=123, client_bot=bot, is_admin=False)

    with pytest.raises(NotFoundError):
        auth_service.require_client_bot_admin(telegram_user_id=123, client_bot=None, is_admin=True)


def test_active_client_bot_authorization():
    auth_service = AuthorizationService(platform_owner_id=999)

    active_bot = MockBot(id=1, status=BotStatus.ACTIVE)
    auth_service.require_active_client_bot(active_bot)

    paused_bot = MockBot(id=2, status=BotStatus.PAUSED)
    with pytest.raises(BotPausedException):
        auth_service.require_active_client_bot(paused_bot)

    disconnected_bot = MockBot(id=3, status=BotStatus.DISCONNECTED)
    with pytest.raises(BotDisconnectedException):
        auth_service.require_active_client_bot(disconnected_bot)


def test_tenant_guard_cross_tenant_checks():
    bot = MockBot(id=1, client_id=10)
    video = MockVideo(id=100, client_bot_id=1)
    viewer = MockViewer(id=200, client_bot_id=1)
    broadcast = MockBroadcast(id=300, client_bot_id=1)
    unlock_link = MockUnlockLink(id=400, video_id=100)

    # Valid tenant checks
    TenantGuardService.assert_bot_belongs_to_client(bot, client_id=10)
    TenantGuardService.assert_video_belongs_to_bot(video, client_bot_id=1)
    TenantGuardService.assert_viewer_belongs_to_bot(viewer, client_bot_id=1)
    TenantGuardService.assert_broadcast_belongs_to_bot(broadcast, client_bot_id=1)
    TenantGuardService.assert_unlock_link_belongs_to_video(unlock_link, video_id=100)

    # Cross-tenant violation checks
    with pytest.raises(ForbiddenError):
        TenantGuardService.assert_bot_belongs_to_client(bot, client_id=99)

    with pytest.raises(ForbiddenError):
        TenantGuardService.assert_video_belongs_to_bot(video, client_bot_id=2)

    with pytest.raises(ForbiddenError):
        TenantGuardService.assert_viewer_belongs_to_bot(viewer, client_bot_id=2)

    with pytest.raises(ForbiddenError):
        TenantGuardService.assert_broadcast_belongs_to_bot(broadcast, client_bot_id=2)

    with pytest.raises(ForbiddenError):
        TenantGuardService.assert_unlock_link_belongs_to_video(unlock_link, video_id=999)
