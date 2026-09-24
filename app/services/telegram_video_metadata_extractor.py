"""Telegram Video Metadata Extractor."""

from typing import Any, Dict, Optional
from pydantic import BaseModel


class VideoCreateData(BaseModel):
    file_id: str
    file_unique_id: str
    message_id: Optional[int] = None
    chat_id: Optional[int] = None
    file_name: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    duration_seconds: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    caption: Optional[str] = None
    source_thumbnail_file_id: Optional[str] = None
    source_thumbnail_file_unique_id: Optional[str] = None


class TelegramVideoMetadataExtractor:
    """Extracts standardized VideoCreateData from a Telegram update or message without downloading video bytes."""

    @staticmethod
    def extract(actor_data: Dict[str, Any], chat_id: Optional[int] = None) -> Optional[VideoCreateData]:
        video = actor_data.get("video")
        if not video or not isinstance(video, dict):
            return None

        file_id = video.get("file_id")
        file_unique_id = video.get("file_unique_id")
        if not file_id or not file_unique_id:
            return None

        message_id = actor_data.get("message_id")
        src_chat_id = actor_data.get("chat_id") or chat_id
        file_name = video.get("file_name")
        mime_type = video.get("mime_type", "video/mp4")
        file_size = video.get("file_size")
        duration_seconds = video.get("duration")
        width = video.get("width")
        height = video.get("height")
        caption = actor_data.get("caption")

        thumbnail = video.get("thumbnail") or video.get("thumb")
        thumb_file_id = None
        thumb_file_unique_id = None
        if isinstance(thumbnail, dict):
            thumb_file_id = thumbnail.get("file_id")
            thumb_file_unique_id = thumbnail.get("file_unique_id")

        return VideoCreateData(
            file_id=str(file_id),
            file_unique_id=str(file_unique_id),
            message_id=int(message_id) if message_id is not None else None,
            chat_id=int(src_chat_id) if src_chat_id is not None else None,
            file_name=file_name,
            mime_type=mime_type,
            file_size=int(file_size) if file_size is not None else None,
            duration_seconds=int(duration_seconds) if duration_seconds is not None else None,
            width=int(width) if width is not None else None,
            height=int(height) if height is not None else None,
            caption=caption,
            source_thumbnail_file_id=thumb_file_id,
            source_thumbnail_file_unique_id=thumb_file_unique_id,
        )
