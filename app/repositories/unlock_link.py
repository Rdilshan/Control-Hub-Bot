"""Unlock Link Repository."""

from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import UnlockLinkStatus
from app.db.models.unlock_link import UnlockLink
from app.repositories.base import BaseRepository


class UnlockLinkRepository(BaseRepository[UnlockLink]):
    def __init__(self, session: AsyncSession):
        super().__init__(UnlockLink, session)

    async def get_active_by_video(self, video_id: int) -> Optional[UnlockLink]:
        stmt = (
            select(UnlockLink)
            .where(
                UnlockLink.video_id == video_id,
                UnlockLink.status == UnlockLinkStatus.ACTIVE,
            )
            .order_by(UnlockLink.id.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        video_id: int,
        client_bot_id: int,
        url: str,
        provider: str = "unlockify",
        external_reference: Optional[str] = None,
    ) -> UnlockLink:
        link = UnlockLink(
            video_id=video_id,
            client_bot_id=client_bot_id,
            url=url,
            provider=provider,
            external_reference=external_reference,
            status=UnlockLinkStatus.ACTIVE,
        )
        self.session.add(link)
        await self.session.flush()
        return link
