"""Durable collection drafts and one-post publication."""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ClientBotStatus, enum_val
from app.core.utils import utc_now
from app.db.models.client_bot import ClientBot
from app.db.models.video_collection import VideoCollection, VideoCollectionItem
from app.repositories.job import BackgroundJobRepository
from app.repositories.sponsor import SponsorRepository
from app.repositories.video import VideoRepository
from app.services.telegram_video_metadata_extractor import TelegramVideoMetadataExtractor


class VideoCollectionService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def draft(self, bot_id: int, user_id: int, lock: bool = False) -> Optional[VideoCollection]:
        stmt = select(VideoCollection).where(
            VideoCollection.client_bot_id == bot_id,
            VideoCollection.owner_telegram_user_id == user_id,
            VideoCollection.status == "DRAFT",
        ).order_by(VideoCollection.id.desc()).limit(1)
        if lock:
            stmt = stmt.with_for_update()
        draft = (await self.session.execute(stmt)).scalar_one_or_none()
        if draft and draft.expires_at.replace(tzinfo=timezone.utc) <= utc_now():
            draft.status = "EXPIRED"
            await self.session.flush()
            return None
        return draft

    async def start(self, bot: ClientBot, user_id: int) -> VideoCollection:
        if enum_val(bot.status) != ClientBotStatus.ACTIVE.value:
            raise ValueError("This bot is not active.")
        sponsor = await SponsorRepository(self.session).get_by_bot_id(bot.id)
        if not sponsor or not sponsor.is_enabled:
            raise ValueError("Configure /sponsor before creating a collection.")
        await self.session.execute(select(ClientBot.id).where(ClientBot.id == bot.id).with_for_update())
        old = await self.draft(bot.id, user_id, lock=True)
        if old:
            old.status = "CANCELLED"
        draft = VideoCollection(
            client_bot_id=bot.id, owner_telegram_user_id=user_id,
            status="DRAFT", expires_at=utc_now() + timedelta(minutes=30),
        )
        self.session.add(draft)
        await self.session.commit()
        return draft

    async def cancel(self, bot_id: int, user_id: int) -> bool:
        draft = await self.draft(bot_id, user_id, lock=True)
        if not draft:
            return False
        draft.status = "CANCELLED"
        await self.session.commit()
        return True

    async def receive(self, bot_id: int, user_id: int, actor_data: dict[str, Any]) -> str:
        draft = await self.draft(bot_id, user_id, lock=True)
        if not draft:
            return "Collection expired. Send /createcollection to start again."
        video = TelegramVideoMetadataExtractor.extract(actor_data, chat_id=actor_data.get("chat_id"))
        if video:
            if not video.message_id or not video.chat_id:
                return "This video could not be identified. Please send it again."
            existing = (await self.session.execute(select(VideoCollectionItem.id).where(
                VideoCollectionItem.collection_id == draft.id,
                VideoCollectionItem.source_chat_id == video.chat_id,
                VideoCollectionItem.telegram_message_id == video.message_id,
            ))).scalar_one_or_none()
            if existing:
                return "Video already received."
            sent_at = actor_data.get("message_date")
            self.session.add(VideoCollectionItem(
                collection_id=draft.id, position=video.message_id,
                telegram_file_id=video.file_id, telegram_file_unique_id=video.file_unique_id,
                source_chat_id=video.chat_id, telegram_message_id=video.message_id,
                source_sent_at=datetime.fromtimestamp(sent_at, tz=timezone.utc) if isinstance(sent_at, (int, float)) else None,
                caption=video.caption, duration_seconds=video.duration_seconds,
                width=video.width, height=video.height,
            ))
            draft.expires_at = utc_now() + timedelta(minutes=30)
            await self.session.commit()
            count = (await self.session.execute(select(func.count(VideoCollectionItem.id)).where(
                VideoCollectionItem.collection_id == draft.id
            ))).scalar_one()
            return f"{count} video(s) received. Send more videos, then one thumbnail photo and /done."
        photos = (actor_data.get("raw_message") or {}).get("photo")
        if photos:
            file_id = photos[-1].get("file_id") if isinstance(photos[-1], dict) else None
            if not file_id:
                return "This photo could not be identified. Please send it again."
            draft.thumbnail_file_id = file_id
            draft.caption = actor_data.get("caption") or "Video Collection"
            draft.expires_at = utc_now() + timedelta(minutes=30)
            await self.session.commit()
            count = (await self.session.execute(select(func.count(VideoCollectionItem.id)).where(
                VideoCollectionItem.collection_id == draft.id
            ))).scalar_one()
            return f"Thumbnail received. {count} video(s) saved. If the count is correct, send /done."
        return "Send Telegram videos, one thumbnail photo, or /done. Send /cancel to discard this collection."

    async def finish(self, bot: ClientBot, user_id: int) -> tuple[Optional[int], str]:
        draft = await self.draft(bot.id, user_id, lock=True)
        if not draft:
            return None, "Collection expired. Send /createcollection to start again."
        items = list((await self.session.execute(select(VideoCollectionItem).where(
            VideoCollectionItem.collection_id == draft.id
        ).order_by(VideoCollectionItem.position, VideoCollectionItem.id))).scalars())
        if not items:
            return None, "Send at least one video before /done."
        if not draft.thumbnail_file_id:
            return None, "Send one thumbnail photo before /done."
        if enum_val(bot.status) != ClientBotStatus.ACTIVE.value:
            return None, "This bot is not active. The collection remains a draft."
        sponsor = await SponsorRepository(self.session).get_by_bot_id(bot.id)
        if not sponsor or not sponsor.is_enabled:
            return None, "Configure /sponsor before publishing. The collection remains a draft."
        first = items[0]
        video = await VideoRepository(self.session).create_video(
            client_bot_id=bot.id, telegram_file_id=first.telegram_file_id,
            telegram_file_unique_id=first.telegram_file_unique_id,
            source_chat_id=first.source_chat_id, telegram_message_id=first.telegram_message_id,
            source_sent_at=first.source_sent_at,
            source_thumbnail_file_id=draft.thumbnail_file_id,
            caption=draft.caption or "Video Collection",
            duration_seconds=first.duration_seconds, width=first.width, height=first.height,
        )
        draft.representative_video_id = video.id
        draft.status = "PUBLISHED"
        await BackgroundJobRepository(self.session).create_video_processing_job(
            video_id=video.id, client_bot_id=bot.id, client_id=bot.client_id,
            thumbnail_file_id=draft.thumbnail_file_id,
        )
        await self.session.commit()
        return video.id, f"Collection received: {len(items)} video(s). One preview and unlock link are being prepared."
