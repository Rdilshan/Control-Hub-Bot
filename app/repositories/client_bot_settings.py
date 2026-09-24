"""Client Bot Settings Repository."""

from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.client_bot_settings import ClientBotSettings
from app.repositories.base import BaseRepository


class ClientBotSettingsRepository(BaseRepository[ClientBotSettings]):
    def __init__(self, session: AsyncSession):
        super().__init__(ClientBotSettings, session)

    async def get_by_bot_id(self, client_bot_id: int) -> Optional[ClientBotSettings]:
        stmt = select(ClientBotSettings).where(ClientBotSettings.client_bot_id == client_bot_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_start_message(self, client_bot_id: int, start_message: str) -> Optional[ClientBotSettings]:
        settings = await self.get_by_bot_id(client_bot_id)
        if settings:
            settings.start_message = start_message
            await self.session.flush()
        return settings

    async def update_default_message(self, client_bot_id: int, default_message: str) -> Optional[ClientBotSettings]:
        settings = await self.get_by_bot_id(client_bot_id)
        if settings:
            settings.default_message = default_message
            await self.session.flush()
        return settings
