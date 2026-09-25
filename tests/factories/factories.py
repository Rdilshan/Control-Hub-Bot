"""Test data factories for rapidly building valid model instances."""

import secrets
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import (
    ClientStatus,
    ClientBotStatus,
    BotAdminRole,
    ViewerStatus,
    VideoStatus,
    BroadcastStatus,
    CatchupStatus,
    JobType,
    JobStatus,
)
from app.core.utils import utc_now
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.db.models.client_bot_admin import ClientBotAdmin
from app.db.models.client_bot_settings import ClientBotSettings
from app.db.models.viewer import Viewer
from app.db.models.video import Video
from app.db.models.sponsor_config import SponsorConfig as Sponsor
from app.db.models.broadcast import Broadcast
from app.db.models.viewer_catchup import ViewerCatchup
from app.db.models.background_job import BackgroundJob


class ClientFactory:
    @staticmethod
    async def create(
        session: AsyncSession,
        telegram_user_id: Optional[int] = None,
        username: Optional[str] = None,
        status: ClientStatus = ClientStatus.ACTIVE,
    ) -> Client:
        client = Client(
            telegram_user_id=telegram_user_id or secrets.randbelow(1_000_000_000),
            username=username or f"client_{secrets.token_hex(4)}",
            status=status,
            created_at=utc_now(),
        )
        session.add(client)
        await session.flush()
        return client


class ClientBotFactory:
    @staticmethod
    async def create(
        session: AsyncSession,
        client_id: int,
        telegram_bot_id: Optional[int] = None,
        username: Optional[str] = None,
        status: ClientBotStatus = ClientBotStatus.ACTIVE,
        public_id: Optional[str] = None,
    ) -> ClientBot:
        bot = ClientBot(
            client_id=client_id,
            telegram_bot_id=telegram_bot_id or secrets.randbelow(1_000_000_000),
            username=username or f"bot_{secrets.token_hex(4)}",
            first_name="Test Client Bot",
            public_id=public_id or f"pub_{secrets.token_hex(6)}",
            status=status,
            token_encrypted="encrypted_test_token_abc",
            webhook_secret_encrypted="encrypted_webhook_secret_xyz",
            created_at=utc_now(),
        )
        session.add(bot)
        await session.flush()
        return bot


class ClientBotAdminFactory:
    @staticmethod
    async def create(
        session: AsyncSession,
        client_bot_id: int,
        telegram_user_id: Optional[int] = None,
        role: BotAdminRole = BotAdminRole.OWNER,
    ) -> ClientBotAdmin:
        admin = ClientBotAdmin(
            client_bot_id=client_bot_id,
            telegram_user_id=telegram_user_id or secrets.randbelow(1_000_000_000),
            role=role,
            created_at=utc_now(),
        )
        session.add(admin)
        await session.flush()
        return admin


class ViewerFactory:
    @staticmethod
    async def create(
        session: AsyncSession,
        client_bot_id: int,
        telegram_user_id: Optional[int] = None,
        status: ViewerStatus = ViewerStatus.ACTIVE,
    ) -> Viewer:
        uid = telegram_user_id or secrets.randbelow(1_000_000_000)
        viewer = Viewer(
            client_bot_id=client_bot_id,
            telegram_user_id=uid,
            username=f"viewer_{secrets.token_hex(4)}",
            status=status,
            created_at=utc_now(),
        )
        session.add(viewer)
        await session.flush()
        return viewer


class VideoFactory:
    @staticmethod
    async def create(
        session: AsyncSession,
        client_bot_id: int,
        title: str = "Test Video",
        status: VideoStatus = VideoStatus.READY,
        telegram_file_id: Optional[str] = None,
    ) -> Video:
        video = Video(
            client_bot_id=client_bot_id,
            public_id=f"vid_{secrets.token_hex(6)}",
            title=title,
            status=status,
            telegram_file_id=telegram_file_id or f"file_id_{secrets.token_hex(8)}",
            telegram_file_unique_id=f"uniq_{secrets.token_hex(8)}",
            telegram_message_id=secrets.randbelow(100_000),
            source_chat_id=secrets.randbelow(1_000_000_000),
            created_at=utc_now(),
        )
        session.add(video)
        await session.flush()
        return video


class SponsorFactory:
    @staticmethod
    async def create(
        session: AsyncSession,
        client_bot_id: int,
        url: str = "https://example.com/sponsor-offer",
        button_text: str = "Get Access",
    ) -> Sponsor:
        sponsor = Sponsor(
            client_bot_id=client_bot_id,
            url=url,
            button_text=button_text,
            is_active=True,
            created_at=utc_now(),
        )
        session.add(sponsor)
        await session.flush()
        return sponsor


class BroadcastFactory:
    @staticmethod
    async def create(
        session: AsyncSession,
        client_bot_id: int,
        video_id: int,
        status: BroadcastStatus = BroadcastStatus.COMPLETED,
        total_recipients: int = 10,
        successful_deliveries: int = 10,
    ) -> Broadcast:
        broadcast = Broadcast(
            client_bot_id=client_bot_id,
            video_id=video_id,
            status=status,
            total_recipients=total_recipients,
            successful_deliveries=successful_deliveries,
            failed_deliveries=0,
            created_at=utc_now(),
        )
        session.add(broadcast)
        await session.flush()
        return broadcast


class CatchupFactory:
    @staticmethod
    async def create(
        session: AsyncSession,
        client_bot_id: int,
        viewer_id: int,
        status: CatchupStatus = CatchupStatus.COMPLETED,
        last_delivered_video_id: Optional[int] = None,
    ) -> ViewerCatchup:
        catchup = ViewerCatchup(
            client_bot_id=client_bot_id,
            viewer_id=viewer_id,
            status=status,
            last_delivered_video_id=last_delivered_video_id,
            created_at=utc_now(),
        )
        session.add(catchup)
        await session.flush()
        return catchup


class JobFactory:
    @staticmethod
    async def create(
        session: AsyncSession,
        client_bot_id: Optional[int] = None,
        job_type: JobType = JobType.LIVE_BROADCAST,
        status: JobStatus = JobStatus.COMPLETED,
        payload_json: Optional[Dict[str, Any]] = None,
    ) -> BackgroundJob:
        job = BackgroundJob(
            client_bot_id=client_bot_id,
            job_type=job_type,
            status=status,
            payload_json=payload_json or {},
            created_at=utc_now(),
        )
        session.add(job)
        await session.flush()
        return job
