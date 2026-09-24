"""Sponsor Configuration Repository."""

from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.sponsor_config import SponsorConfig
from app.repositories.base import BaseRepository


class SponsorRepository(BaseRepository[SponsorConfig]):
    def __init__(self, session: AsyncSession):
        super().__init__(SponsorConfig, session)

    async def get_by_bot_id(self, client_bot_id: int) -> Optional[SponsorConfig]:
        stmt = select(SponsorConfig).where(SponsorConfig.client_bot_id == client_bot_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_sponsor(
        self,
        client_bot_id: int,
        sponsor_url: Optional[str] = None,
        sponsor_name: Optional[str] = None,
        sponsor_text: Optional[str] = None,
        button_text: Optional[str] = None,
        is_enabled: Optional[bool] = None,
    ) -> Optional[SponsorConfig]:
        sponsor = await self.get_by_bot_id(client_bot_id)
        if sponsor:
            if sponsor_url is not None:
                sponsor.sponsor_url = sponsor_url
            if sponsor_name is not None:
                sponsor.sponsor_name = sponsor_name
            if sponsor_text is not None:
                sponsor.sponsor_text = sponsor_text
            if button_text is not None:
                sponsor.button_text = button_text
            if is_enabled is not None:
                sponsor.is_enabled = is_enabled
            await self.session.flush()
        return sponsor

    async def set_enabled(self, client_bot_id: int, is_enabled: bool) -> Optional[SponsorConfig]:
        return await self.update_sponsor(client_bot_id, is_enabled=is_enabled)
