"""Send Control Hub campaigns to active client owners."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.core.enums import ClientStatus, JobStatus
from app.db.models.client import Client
from app.db.models.message_campaign import CampaignClientDelivery, MessageCampaign
from app.repositories.job import BackgroundJobRepository
from app.services.telegram_broadcast_rate_limiter import telegram_rate_limiter
from app.telegram.client import TelegramClient
from app.telegram.errors import TelegramForbiddenError, TelegramRateLimitError


class OwnerMessageCampaignWorker:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.jobs = BackgroundJobRepository(session)

    async def claim_job(self):
        job = await self.jobs.claim_owner_campaign_job()
        await self.session.commit()
        return job

    async def process_job(self, job_id: int, telegram_client: TelegramClient | None = None):
        job = await self.jobs.get_by_id(job_id)
        if not job or job.status != JobStatus.RUNNING:
            return {"ok": False}
        campaign = await self.session.get(MessageCampaign, job.payload["campaign_id"])
        if not campaign:
            await self.jobs.mark_failed(job_id, "MISSING_CAMPAIGN", "Campaign not found")
            await self.session.commit()
            return {"ok": False}
        client = telegram_client or TelegramClient(get_settings().CONTROL_HUB_BOT_TOKEN)
        campaign.status = "RUNNING"
        await self.session.commit()
        while True:
            recipients = list((await self.session.execute(
                select(Client).where(
                    Client.status == ClientStatus.ACTIVE,
                    Client.id > campaign.last_client_id,
                    Client.id <= campaign.max_client_id,
                ).order_by(Client.id).limit(100)
            )).scalars())
            if not recipients:
                break
            for recipient in recipients:
                previous = (await self.session.execute(select(CampaignClientDelivery).where(
                    CampaignClientDelivery.campaign_id == campaign.id,
                    CampaignClientDelivery.client_id == recipient.id,
                ))).scalar_one_or_none()
                if previous and previous.status == "SENT":
                    campaign.last_client_id = recipient.id
                    continue
                try:
                    await telegram_rate_limiter.acquire(-1)
                    result = await client.send_content(recipient.telegram_user_id, campaign.content)
                    status = "SENT"
                    message_id = result.get("message_id")
                    campaign.sent_count += 1
                except TelegramForbiddenError:
                    status, message_id = "BLOCKED", None
                    campaign.blocked_count += 1
                except TelegramRateLimitError as exc:
                    telegram_rate_limiter.pause_bot(-1, exc.retry_after)
                    status, message_id = "FAILED", None
                    campaign.failed_count += 1
                except Exception:
                    status, message_id = "FAILED", None
                    campaign.failed_count += 1
                if previous:
                    previous.status, previous.telegram_message_id = status, message_id
                else:
                    self.session.add(CampaignClientDelivery(
                        campaign_id=campaign.id, client_id=recipient.id,
                        status=status, telegram_message_id=message_id,
                    ))
                campaign.last_client_id = recipient.id
            await self.jobs.update_heartbeat(job.id)
            await self.session.commit()

        failed = list((await self.session.execute(select(CampaignClientDelivery).where(
            CampaignClientDelivery.campaign_id == campaign.id,
            CampaignClientDelivery.status == "FAILED",
        ))).scalars())
        for receipt in failed:
            recipient = await self.session.get(Client, receipt.client_id)
            if not recipient or recipient.status != ClientStatus.ACTIVE:
                continue
            try:
                await telegram_rate_limiter.acquire(-1)
                result = await client.send_content(recipient.telegram_user_id, campaign.content)
                receipt.status = "SENT"
                receipt.telegram_message_id = result.get("message_id")
                campaign.failed_count -= 1
                campaign.sent_count += 1
            except TelegramForbiddenError:
                receipt.status = "BLOCKED"
                campaign.failed_count -= 1
                campaign.blocked_count += 1
            except TelegramRateLimitError as exc:
                telegram_rate_limiter.pause_bot(-1, exc.retry_after)
            except Exception:
                pass
            await self.jobs.update_heartbeat(job.id)
            await self.session.commit()
        campaign.total_targets = campaign.sent_count + campaign.failed_count + campaign.blocked_count
        campaign.status = "PARTIAL" if campaign.failed_count else "COMPLETED"
        await self.jobs.mark_completed(job.id)
        await self.session.commit()
        return {"ok": True, "campaign_id": campaign.id}
