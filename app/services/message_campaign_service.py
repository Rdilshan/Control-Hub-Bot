"""Create and inspect custom broadcast campaigns."""

from typing import Any, Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import ClientBotStatus, ClientStatus, JobType, ViewerStatus
from app.db.models.broadcast import Broadcast
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.db.models.message_campaign import MessageCampaign
from app.db.models.viewer import Viewer
from app.repositories.job import BackgroundJobRepository
from app.services.message_content import validate_cross_bot_content


class MessageCampaignService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.jobs = BackgroundJobRepository(session)

    async def create(
        self, creator_telegram_user_id: int, audience: str, content: dict[str, Any],
        source_bot: str, client_bot_id: Optional[int] = None,
        idempotency_key: Optional[str] = None,
    ) -> MessageCampaign:
        if idempotency_key:
            existing = (await self.session.execute(select(MessageCampaign).where(MessageCampaign.idempotency_key == idempotency_key))).scalar_one_or_none()
            if existing:
                return existing
        if audience not in ("OWNERS", "ONE_BOT", "ALL_VIEWERS"):
            raise ValueError("Unknown audience")
        if audience == "ONE_BOT" and client_bot_id is None:
            raise ValueError("Select a bot")
        if source_bot == "CLIENT" and audience != "ONE_BOT":
            raise ValueError("Client bot owners can only broadcast to their own viewers")
        if source_bot == "HUB" and audience != "OWNERS":
            validate_cross_bot_content(content)

        campaign = MessageCampaign(
            creator_telegram_user_id=creator_telegram_user_id,
            idempotency_key=idempotency_key,
            creator_client_bot_id=client_bot_id if source_bot == "CLIENT" else None,
            audience=audience, content=content, source_bot=source_bot,
            status="PENDING", total_targets=0,
        )
        self.session.add(campaign)
        await self.session.flush()

        if audience == "OWNERS":
            campaign.max_client_id = (await self.session.scalar(select(func.max(Client.id)).where(Client.status == ClientStatus.ACTIVE))) or 0
            campaign.total_targets = (await self.session.scalar(select(func.count(Client.id)).where(Client.status == ClientStatus.ACTIVE, Client.id <= campaign.max_client_id))) or 0
            await self.jobs.create_job(
                job_type=JobType.OWNER_MESSAGE_CAMPAIGN,
                payload={"campaign_id": campaign.id}, resource_type="message_campaign",
                resource_id=campaign.id, queue_name="broadcast_live", priority=80,
                deduplication_key=f"owner-campaign:{campaign.id}",
            )
        else:
            stmt = select(ClientBot).where(ClientBot.status == ClientBotStatus.ACTIVE)
            if audience == "ONE_BOT":
                stmt = stmt.where(ClientBot.id == client_bot_id)
            bots = list((await self.session.execute(stmt)).scalars())
            if audience == "ONE_BOT" and not bots:
                raise ValueError("Bot is not active")
            for bot in bots:
                count = (await self.session.scalar(select(func.count(Viewer.id)).where(Viewer.client_bot_id == bot.id, Viewer.status == ViewerStatus.ACTIVE))) or 0
                campaign.total_targets += count
                broadcast = Broadcast(
                    client_bot_id=bot.id, video_id=None, campaign_id=campaign.id,
                    broadcast_type="LIVE", target_type="ALL_ACTIVE_VIEWERS",
                    status="PENDING", total_targets=count,
                )
                self.session.add(broadcast)
                await self.session.flush()
                await self.jobs.create_broadcast_job(
                    broadcast_id=broadcast.id, video_id=None,
                    client_bot_id=bot.id, client_id=bot.client_id,
                )
        await self.session.flush()
        return campaign

    async def list_campaigns(self, creator_telegram_user_id: int, client_bot_id: Optional[int] = None) -> list[MessageCampaign]:
        stmt = select(MessageCampaign).where(MessageCampaign.creator_telegram_user_id == creator_telegram_user_id)
        if client_bot_id is not None:
            stmt = stmt.where(MessageCampaign.creator_client_bot_id == client_bot_id)
        return list((await self.session.execute(stmt.order_by(MessageCampaign.id.desc()).limit(10))).scalars())

    async def detail(self, campaign_id: int, creator_telegram_user_id: Optional[int] = None) -> Optional[dict[str, Any]]:
        campaign = await self.session.get(MessageCampaign, campaign_id)
        if not campaign or (creator_telegram_user_id is not None and campaign.creator_telegram_user_id != creator_telegram_user_id):
            return None
        broadcasts = list((await self.session.execute(select(Broadcast).where(Broadcast.campaign_id == campaign.id))).scalars())
        if broadcasts:
            total = sum(b.total_targets for b in broadcasts)
            sent = sum(b.sent_count for b in broadcasts)
            failed = sum(b.failed_count for b in broadcasts)
            blocked = sum(b.blocked_count for b in broadcasts)
            states = {str(b.status.value if hasattr(b.status, "value") else b.status) for b in broadcasts}
            status = "RUNNING" if "RUNNING" in states else "PENDING" if states & {"PENDING", "QUEUED"} else "FAILED" if "FAILED" in states and not sent else "COMPLETED" if states <= {"COMPLETED", "PARTIAL"} else "PARTIAL"
            if status == "COMPLETED" and failed:
                status = "PARTIAL"
        else:
            total, sent, failed, blocked, status = campaign.total_targets, campaign.sent_count, campaign.failed_count, campaign.blocked_count, campaign.status
        return {
            "id": campaign.id, "audience": campaign.audience, "status": status,
            "total": total, "sent": sent, "failed": failed, "blocked": blocked,
            "remaining": max(0, total - sent - failed - blocked),
            "bots": len(broadcasts),
        }
