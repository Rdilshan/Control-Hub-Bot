"""Video Repository with strict bot isolation."""

from datetime import datetime
from typing import List, Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import BotEventType, ProcessingStatus, VideoStatus
from app.core.utils import utc_now
from app.db.models.bot_event import BotEvent
from app.db.models.client_bot import ClientBot
from app.db.models.video import Video
from app.db.models.video_processing import VideoProcessing
from app.repositories.base import BaseRepository


class VideoRepository(BaseRepository[Video]):
    def __init__(self, session: AsyncSession):
        super().__init__(Video, session)

    async def get_by_id(self, video_id: int) -> Optional[Video]:
        stmt = select(Video).where(Video.id == video_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_and_bot(self, video_id: int, client_bot_id: int) -> Optional[Video]:
        stmt = select(Video).where(
            Video.id == video_id,
            Video.client_bot_id == client_bot_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_telegram_message(
        self,
        client_bot_id: int,
        source_chat_id: int,
        telegram_message_id: int,
    ) -> Optional[Video]:
        stmt = select(Video).where(
            Video.client_bot_id == client_bot_id,
            Video.source_chat_id == source_chat_id,
            Video.telegram_message_id == telegram_message_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_public_id_and_bot(self, public_id: str, client_bot_id: int) -> Optional[Video]:
        stmt = select(Video).where(
            Video.public_id == public_id,
            Video.client_bot_id == client_bot_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_video(
        self,
        client_bot_id: int,
        telegram_file_id: str,
        telegram_file_unique_id: str,
        created_by_admin_id: Optional[int] = None,
        telegram_message_id: Optional[int] = None,
        source_chat_id: Optional[int] = None,
        source_sent_at: Optional[datetime] = None,
        source_thumbnail_file_id: Optional[str] = None,
        source_thumbnail_file_unique_id: Optional[str] = None,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
        file_size: Optional[int] = None,
        duration_seconds: Optional[int] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        caption: Optional[str] = None,
        public_id: Optional[str] = None,
    ) -> Video:
        """Creates a video record and its initial VideoProcessing row inside one transaction."""
        from app.core.utils import generate_public_id

        video = Video(
            client_bot_id=client_bot_id,
            created_by_admin_id=created_by_admin_id,
            public_id=public_id or generate_public_id("vid"),
            telegram_file_id=telegram_file_id,
            telegram_file_unique_id=telegram_file_unique_id,
            telegram_message_id=telegram_message_id,
            source_chat_id=source_chat_id,
            source_sent_at=source_sent_at,
            source_thumbnail_file_id=source_thumbnail_file_id,
            source_thumbnail_file_unique_id=source_thumbnail_file_unique_id,
            file_name=file_name,
            mime_type=mime_type,
            file_size=file_size,
            duration_seconds=duration_seconds,
            width=width,
            height=height,
            caption=caption,
            status=VideoStatus.RECEIVED,
        )
        self.session.add(video)
        await self.session.flush()

        # Create corresponding video_processing entry
        processing = VideoProcessing(
            video_id=video.id,
            status=ProcessingStatus.PENDING,
            thumbnail_file_id=source_thumbnail_file_id,
            thumbnail_path_or_reference=source_thumbnail_file_id,
            processing_started_at=utc_now(),
        )
        self.session.add(processing)

        # Record event
        event = BotEvent(
            client_bot_id=client_bot_id,
            event_type=BotEventType.VIDEO_CREATED,
            related_video_id=video.id,
            metadata_json={"file_unique_id": telegram_file_unique_id},
        )
        self.session.add(event)

        await self.session.flush()
        return video

    async def update_status(self, video_id: int, status: VideoStatus) -> Optional[Video]:
        video = await self.get_by_id(video_id)
        if video:
            video.status = status
            if status == VideoStatus.READY and not video.published_at:
                video.published_at = utc_now()
            await self.session.flush()
        return video

    async def mark_ready(self, video_id: int, client_bot_id: int) -> Optional[Video]:
        video = await self.get_by_id_and_bot(video_id, client_bot_id)
        if video:
            video.status = VideoStatus.READY
            video.published_at = utc_now()
            
            # Record event
            event = BotEvent(
                client_bot_id=client_bot_id,
                event_type=BotEventType.VIDEO_READY,
                related_video_id=video.id,
            )
            self.session.add(event)
            await self.session.flush()
        return video

    async def list_by_bot(
        self,
        client_bot_id: int,
        status: Optional[VideoStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Video]:
        stmt = select(Video).where(Video.client_bot_id == client_bot_id)
        if status:
            stmt = stmt.where(Video.status == status)
        stmt = stmt.order_by(Video.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_ready_by_bot(
        self,
        client_bot_id: int,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Video]:
        return await self.list_by_bot(client_bot_id=client_bot_id, status=VideoStatus.READY, limit=limit, offset=offset)

    async def list_processing_by_bot(
        self,
        client_bot_id: int,
        limit: int = 20,
    ) -> List[Video]:
        stmt = (
            select(Video)
            .where(
                Video.client_bot_id == client_bot_id,
                Video.status.in_([VideoStatus.RECEIVED, VideoStatus.PROCESSING]),
            )
            .order_by(Video.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_ready_videos_for_catchup(
        self,
        client_bot_id: int,
        limit: int = 20,
    ) -> List[Video]:
        stmt = (
            select(Video)
            .where(
                Video.client_bot_id == client_bot_id,
                Video.status == VideoStatus.READY,
            )
            .order_by(Video.published_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_bot(self, client_bot_id: int, status: Optional[VideoStatus] = None) -> int:
        stmt = select(func.count(Video.id)).where(Video.client_bot_id == client_bot_id)
        if status:
            stmt = stmt.where(Video.status == status)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def count_platform_total(self) -> int:
        stmt = select(func.count(Video.id))
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def count_created_since(self, since: datetime) -> int:
        stmt = select(func.count(Video.id)).where(Video.created_at >= since)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def count_by_client(self, client_id: int) -> int:
        stmt = (
            select(func.count(Video.id))
            .join(ClientBot, Video.client_bot_id == ClientBot.id)
            .where(ClientBot.client_id == client_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0
