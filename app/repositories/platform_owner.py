"""Platform Owner Repository."""

from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.platform_owner import PlatformOwner
from app.repositories.base import BaseRepository


class PlatformOwnerRepository(BaseRepository[PlatformOwner]):
    def __init__(self, session: AsyncSession):
        super().__init__(PlatformOwner, session)

    async def get_by_telegram_user_id(self, telegram_user_id: int) -> Optional[PlatformOwner]:
        stmt = select(PlatformOwner).where(PlatformOwner.telegram_user_id == telegram_user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def is_owner(self, telegram_user_id: int) -> bool:
        owner = await self.get_by_telegram_user_id(telegram_user_id)
        return bool(owner and owner.is_active)

    async def create(
        self,
        telegram_user_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> PlatformOwner:
        owner = PlatformOwner(
            telegram_user_id=telegram_user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            is_active=True,
        )
        self.session.add(owner)
        await self.session.flush()
        return owner

    async def list_active(self) -> List[PlatformOwner]:
        stmt = select(PlatformOwner).where(PlatformOwner.is_active.is_(True))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
