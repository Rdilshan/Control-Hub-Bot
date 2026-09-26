"""Resumable, ordered delivery of collection videos after one unlock."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ClientBotStatus, JobStatus, JobType, ViewerStatus, enum_val
from app.core.security import decrypt_token
from app.core.utils import utc_now
from app.db.models.background_job import BackgroundJob
from app.db.models.client_bot import ClientBot
from app.db.models.video_collection import CollectionItemDelivery, VideoCollection, VideoCollectionItem
from app.db.models.viewer import Viewer
from app.repositories.job import BackgroundJobRepository
from app.services.telegram_broadcast_rate_limiter import telegram_rate_limiter
from app.telegram.client import TelegramClient
from app.telegram.errors import TelegramForbiddenError, TelegramRateLimitError


class CollectionDeliveryWorker:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.jobs = BackgroundJobRepository(session)

    async def claim(self) -> BackgroundJob | None:
        stmt = select(BackgroundJob).where(
            BackgroundJob.job_type == JobType.COLLECTION_DELIVERY,
            BackgroundJob.status.in_([JobStatus.PENDING, JobStatus.RETRYING]),
            BackgroundJob.available_at <= utc_now(),
        ).order_by(BackgroundJob.available_at, BackgroundJob.id).limit(1).with_for_update(skip_locked=True)
        job = (await self.session.execute(stmt)).scalar_one_or_none()
        if job:
            await self.jobs.mark_running(job.id)
            await self.session.commit()
        return job

    async def process(self, job_id: int) -> None:
        job = await self.jobs.get_by_id(job_id)
        if not job or job.status != JobStatus.RUNNING:
            return
        collection = await self.session.get(VideoCollection, job.payload["collection_id"])
        viewer = await self.session.get(Viewer, job.payload["viewer_id"])
        bot = await self.session.get(ClientBot, job.client_bot_id)
        if not collection or not viewer or not bot or collection.client_bot_id != bot.id or viewer.client_bot_id != bot.id:
            await self.jobs.mark_failed(job_id, "MISSING_ENTITY", "Collection, viewer or bot missing")
            await self.session.commit()
            return
        if enum_val(viewer.status) == ViewerStatus.BLOCKED.value:
            await self.jobs.mark_completed(job_id)
            await self.session.commit()
            return
        if enum_val(bot.status) != ClientBotStatus.ACTIVE.value:
            await self.jobs.mark_retrying(job_id, utc_now() + timedelta(minutes=5), "BOT_INACTIVE", "Bot is not active")
            await self.session.commit()
            return
        client = TelegramClient(token=decrypt_token(bot.token_encrypted))
        items = list((await self.session.execute(select(VideoCollectionItem).where(
            VideoCollectionItem.collection_id == collection.id
        ).order_by(VideoCollectionItem.position, VideoCollectionItem.id))).scalars())
        for item in items:
            receipt = (await self.session.execute(select(CollectionItemDelivery).where(
                CollectionItemDelivery.item_id == item.id,
                CollectionItemDelivery.viewer_id == viewer.id,
            ))).scalar_one_or_none()
            if receipt and receipt.status == "SENT":
                continue
            if enum_val(bot.status) != ClientBotStatus.ACTIVE.value:
                await self.jobs.mark_retrying(job_id, utc_now() + timedelta(minutes=5), "BOT_INACTIVE", "Bot is not active")
                await self.session.commit()
                return
            if not receipt:
                receipt = CollectionItemDelivery(collection_id=collection.id, item_id=item.id, viewer_id=viewer.id, status="PENDING")
                self.session.add(receipt)
                await self.session.flush()
            try:
                await telegram_rate_limiter.acquire(bot.id)
                result = await client.send_video(
                    chat_id=viewer.telegram_user_id, video=item.telegram_file_id,
                    caption=item.caption, parse_mode=None, duration=item.duration_seconds,
                    width=item.width, height=item.height,
                )
                receipt.status = "SENT"
                receipt.telegram_message_id = result.get("message_id")
                receipt.last_error = None
                await self.jobs.update_heartbeat(job_id)
                await self.session.commit()
            except TelegramForbiddenError as exc:
                receipt.status = "BLOCKED"
                receipt.last_error = str(exc)
                viewer.status = ViewerStatus.BLOCKED
                await self.jobs.mark_completed(job_id)
                await self.session.commit()
                return
            except Exception as exc:
                receipt.status = "FAILED"
                receipt.last_error = str(exc)[:1000]
                if isinstance(exc, TelegramRateLimitError):
                    telegram_rate_limiter.pause_bot(bot.id, exc.retry_after)
                if job.attempt_count >= job.max_attempts:
                    await self.jobs.mark_failed(job_id, type(exc).__name__, str(exc)[:1000])
                else:
                    delay = exc.retry_after if isinstance(exc, TelegramRateLimitError) else min(900, 15 * 2 ** max(0, job.attempt_count - 1))
                    await self.jobs.mark_retrying(job_id, utc_now() + timedelta(seconds=delay), type(exc).__name__, str(exc)[:1000])
                await self.session.commit()
                return
        await self.jobs.mark_completed(job_id)
        await self.session.commit()
