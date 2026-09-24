"""Preview Photo Service for preparing reusable Telegram photo assets."""

import os
import tempfile
from typing import Optional
from app.exceptions import ExternalServiceError
from app.logging_config import logger
from app.telegram.client import TelegramClient
from app.telegram.errors import TelegramAPIError, TelegramInvalidTokenError

# Minimal 1x1 valid JPEG fallback image bytes
DEFAULT_PREVIEW_JPEG_BYTES = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00"
    b"\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19"
    b"\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.\' \",#\x1c\x1c(7),01444\x1f\'9=82<.342"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01"
    b"\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05"
    b"\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
)


class PreviewPhotoService:
    """Handles downloading source thumbnails and uploading reusable Telegram Photos."""

    def __init__(self, telegram_client: TelegramClient):
        self.telegram_client = telegram_client

    async def prepare_preview_photo(
        self,
        chat_id: int | str,
        source_thumbnail_file_id: Optional[str] = None,
        existing_preview_file_id: Optional[str] = None,
    ) -> str:
        """Ensures a reusable Telegram Photo file_id exists for the video.

        Args:
            chat_id: Telegram chat ID to perform the photo upload into.
            source_thumbnail_file_id: Optional file_id of the source video thumbnail.
            existing_preview_file_id: Optional previously prepared photo file_id.

        Returns:
            The reusable Telegram photo file_id.
        """
        if existing_preview_file_id:
            logger.info("Using existing preview photo file_id: %s", existing_preview_file_id)
            return existing_preview_file_id

        photo_bytes: Optional[bytes] = None

        if source_thumbnail_file_id:
            try:
                file_info = await self.telegram_client.get_file(source_thumbnail_file_id)
                file_path = file_info.get("file_path")
                if file_path:
                    photo_bytes = await self.telegram_client.download_file(file_path)
            except (TelegramInvalidTokenError,):
                raise
            except Exception as exc:
                logger.warning(
                    "Failed to download source thumbnail %s: %s. Falling back to default preview.",
                    source_thumbnail_file_id,
                    exc,
                )
                photo_bytes = None

        if not photo_bytes:
            logger.info("Using default preview image fallback")
            photo_bytes = DEFAULT_PREVIEW_JPEG_BYTES

        # Write to temporary file with secure cleanup
        temp_file_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                tmp.write(photo_bytes)
                temp_file_path = tmp.name

            # Read bytes and upload to Telegram via same bot
            with open(temp_file_path, "rb") as f:
                upload_bytes = f.read()

            upload_res = await self.telegram_client.send_photo(
                chat_id=chat_id,
                photo=upload_bytes,
                caption="Preview asset",
            )

            # Extract highest resolution photo file_id
            photos = upload_res.get("photo", [])
            if not photos:
                raise ExternalServiceError("Telegram did not return photo sizes after upload")

            # Largest photo is the last element
            preview_file_id = photos[-1]["file_id"]

            # Best-effort delete temporary chat message
            msg_id = upload_res.get("message_id")
            if msg_id:
                try:
                    await self.telegram_client.delete_message(chat_id=chat_id, message_id=msg_id)
                except Exception as del_exc:
                    logger.debug("Could not delete temp preview message: %s", del_exc)

            logger.info("Successfully prepared preview photo file_id: %s", preview_file_id)
            return preview_file_id

        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except Exception as rm_exc:
                    logger.warning("Failed to remove temp file %s: %s", temp_file_path, rm_exc)
