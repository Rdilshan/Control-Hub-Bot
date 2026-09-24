"""Video Repository with strict bot isolation."""

from typing import List, Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import BotEventType, ProcessingStatus, VideoStatus
from app.core.utils import utc_now
from app.db.models.bot_event import BotEvent
from app.db.models.video import Video
from app.db.models.video_processing import VideoProcessing
from app.repositories.base import BaseRepository


class VideoRepository(BaseRepository[Video]):
    def __init__(self, session: AsyncSession):
        super().__init__(Video, session)

    async def get_by_id_and_bot(self, video_id: int, client_bot_id: int) -> Optional[Video]:
        stmt = select(Video).where(
            Video.id == video_id,
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
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
        file_size: Optional[int] = None,
        duration_seconds: Optional[int] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        caption: Optional[str] = None,
    ) -> Video:
        """Creates a video record and its initial VideoProcessing row inside one transaction."""
        video = Video(
            client_bot_id=client_bot_id,
            created_by_admin_id=created_by_admin_id,
            telegram_file_id=telegram_file_id,
            telegram_file_unique_id=telegram_file_unique_id,
            telegram_message_id=telegram_message_id,
            source_chat_id=source_chat_id,
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
