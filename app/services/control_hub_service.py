"""Control Hub Business Service for role resolution and summary stats."""

from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import (
    ClientBotStatus,
    ClientStatus,
    ControlHubRole,
    JobStatus,
    VideoStatus,
    ViewerStatus,
)
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.repositories.broadcast import BroadcastRepository
from app.repositories.client import ClientRepository
from app.repositories.client_bot import ClientBotRepository
from app.repositories.job import BackgroundJobRepository
from app.repositories.platform_owner import PlatformOwnerRepository
from app.repositories.video import VideoRepository
from app.repositories.viewer import ViewerRepository


class ControlHubService:
    """Orchestrates Control Hub bot roles, summary metrics, and accounts."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.owner_repo = PlatformOwnerRepository(session)
        self.client_repo = ClientRepository(session)
        self.bot_repo = ClientBotRepository(session)
        self.job_repo = BackgroundJobRepository(session)
        self.broadcast_repo = BroadcastRepository(session)
        self.viewer_repo = ViewerRepository(session)
        self.video_repo = VideoRepository(session)

    async def resolve_role(self, telegram_user_id: int) -> ControlHubRole:
        """Determines user role: PLATFORM_OWNER, CLIENT, or NEW_CLIENT.
        
        Priority:
        1. Active Platform Owner
        2. Existing Client
        3. New Client
        """
        is_owner = await self.owner_repo.is_owner(telegram_user_id)
        if is_owner:
            return ControlHubRole.PLATFORM_OWNER

        client = await self.client_repo.get_by_telegram_user_id(telegram_user_id)
        if client:
            return ControlHubRole.CLIENT

        return ControlHubRole.NEW_CLIENT

    async def get_or_create_client(
        self,
        telegram_user_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> tuple[Client, bool]:
        """Recognizes returning client or registers new client account."""
        return await self.client_repo.get_or_create(
            telegram_user_id=telegram_user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )

    async def get_client_by_telegram_id(self, telegram_user_id: int) -> Optional[Client]:
        return await self.client_repo.get_by_telegram_user_id(telegram_user_id)

    async def list_client_bots(self, client_id: int) -> List[ClientBot]:
        """Lists connected bots strictly isolated to the specified client."""
        return await self.bot_repo.list_by_client(client_id)

    async def get_client_account_summary(self, client_id: int) -> Dict[str, Any]:
        """Returns client account summary details."""
        client = await self.client_repo.get_by_id(client_id)
        if not client:
            return {}
        bots = await self.list_client_bots(client_id)
        active_bots = [b for b in bots if b.status == ClientBotStatus.ACTIVE]

        return {
            "telegram_user_id": client.telegram_user_id,
            "username": client.username,
            "first_name": client.first_name,
            "status": client.status.value,
            "total_bots": len(bots),
            "active_bots": len(active_bots),
            "created_at": client.created_at,
            "last_seen_at": client.last_seen_at,
        }

    async def get_owner_system_stats(self) -> Dict[str, Any]:
        """Calculates system-wide platform statistics for Platform Owner."""
        total_clients = await self.client_repo.count_all()
        total_bots = await self.bot_repo.count_all()
        active_bots = await self.bot_repo.count_by_status(ClientBotStatus.ACTIVE)
        paused_bots = await self.bot_repo.count_by_status(ClientBotStatus.PAUSED)
        disconnected_bots = await self.bot_repo.count_by_status(ClientBotStatus.DISCONNECTED)

        return {
            "total_clients": total_clients,
            "total_bots": total_bots,
            "active_bots": active_bots,
            "paused_bots": paused_bots,
            "disconnected_bots": disconnected_bots,
            "total_viewers": 0,  # Sum across bots in V1
            "total_videos": 0,
            "processing_jobs": 0,
            "running_broadcasts": 0,
            "failed_items": 0,
        }
