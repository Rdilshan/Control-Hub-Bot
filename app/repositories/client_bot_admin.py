"""Client Bot Admin Repository."""

from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import BotAdminRole
from app.db.models.client_bot_admin import ClientBotAdmin
from app.repositories.base import BaseRepository


class ClientBotAdminRepository(BaseRepository[ClientBotAdmin]):
    def __init__(self, session: AsyncSession):
        super().__init__(ClientBotAdmin, session)

    async def get_by_bot_and_telegram_user(
        self,
        client_bot_id: int,
        telegram_user_id: int,
    ) -> Optional[ClientBotAdmin]:
        stmt = select(ClientBotAdmin).where(
            ClientBotAdmin.client_bot_id == client_bot_id,
            ClientBotAdmin.telegram_user_id == telegram_user_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def is_admin_or_owner(self, client_bot_id: int, telegram_user_id: int) -> bool:
        admin = await self.get_by_bot_and_telegram_user(client_bot_id, telegram_user_id)
        return bool(admin and admin.is_active)

    async def add_admin(
        self,
        client_bot_id: int,
        telegram_user_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        role: BotAdminRole = BotAdminRole.ADMIN,
    ) -> ClientBotAdmin:
        admin = ClientBotAdmin(
            client_bot_id=client_bot_id,
            telegram_user_id=telegram_user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            role=role,
            is_active=True,
        )
        self.session.add(admin)
        await self.session.flush()
        return admin

    async def list_by_bot(self, client_bot_id: int) -> List[ClientBotAdmin]:
        stmt = select(ClientBotAdmin).where(
            ClientBotAdmin.client_bot_id == client_bot_id,
            ClientBotAdmin.is_active.is_(True),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
