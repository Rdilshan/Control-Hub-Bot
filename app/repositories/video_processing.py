"""Video Processing Repository."""

from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import ProcessingStatus
from app.core.utils import utc_now
from app.db.models.video_processing import VideoProcessing
from app.repositories.base import BaseRepository


class VideoProcessingRepository(BaseRepository[VideoProcessing]):
    def __init__(self, session: AsyncSession):
        super().__init__(VideoProcessing, session)

    async def get_by_video_id(self, video_id: int) -> Optional[VideoProcessing]:
        stmt = select(VideoProcessing).where(VideoProcessing.video_id == video_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_progress(
        self,
        video_id: int,
        status: ProcessingStatus,
        thumbnail_file_id: Optional[str] = None,
        unlock_url: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Optional[VideoProcessing]:
        proc = await self.get_by_video_id(video_id)
        if proc:
            proc.status = status
            if thumbnail_file_id:
                proc.thumbnail_file_id = thumbnail_file_id
            if unlock_url:
                proc.unlock_url = unlock_url
            if error_code:
                proc.last_error_code = error_code
                proc.last_error_message = error_message
            if status == ProcessingStatus.READY:
                proc.processing_completed_at = utc_now()
            await self.session.flush()
        return proc

    async def increment_retry(self, video_id: int) -> Optional[VideoProcessing]:
        proc = await self.get_by_video_id(video_id)
        if proc:
            proc.retry_count += 1
            await self.session.flush()
        return proc
