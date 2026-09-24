"""Client Repository."""

from datetime import datetime
from typing import List, Optional, Tuple
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import ClientStatus
from app.core.utils import utc_now
from app.db.models.client import Client
from app.repositories.base import BaseRepository


class ClientRepository(BaseRepository[Client]):
    def __init__(self, session: AsyncSession):
        super().__init__(Client, session)

    async def get_by_id(self, client_id: int) -> Optional[Client]:
        stmt = select(Client).where(Client.id == client_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_telegram_user_id(self, telegram_user_id: int) -> Optional[Client]:
        stmt = select(Client).where(Client.telegram_user_id == telegram_user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create(
        self,
        telegram_user_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> tuple[Client, bool]:
        """Gets existing client or creates a new one. Returns (client, created)."""
        existing = await self.get_by_telegram_user_id(telegram_user_id)
        if existing:
            existing.last_seen_at = utc_now()
            if username:
                existing.username = username
            if first_name:
                existing.first_name = first_name
            if last_name:
                existing.last_name = last_name
            await self.session.flush()
            return existing, False

        new_client = Client(
            telegram_user_id=telegram_user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            status=ClientStatus.ACTIVE,
            last_seen_at=utc_now(),
        )
        self.session.add(new_client)
        await self.session.flush()
        return new_client, True

    async def set_status(self, client_id: int, status: ClientStatus) -> Optional[Client]:
        client = await self.get_by_id(client_id)
        if client:
            client.status = status
            await self.session.flush()
        return client

    async def suspend(self, client_id: int) -> Optional[Client]:
        return await self.set_status(client_id, ClientStatus.SUSPENDED)

    async def reactivate(self, client_id: int) -> Optional[Client]:
        return await self.set_status(client_id, ClientStatus.ACTIVE)

    async def count_all(self) -> int:
        stmt = select(func.count(Client.id))
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def count_by_status(self, status: ClientStatus) -> int:
        stmt = select(func.count(Client.id)).where(Client.status == status)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def count_created_since(self, since: datetime) -> int:
        stmt = select(func.count(Client.id)).where(Client.created_at >= since)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def list_paginated(
        self,
        page: int = 1,
        page_size: int = 10,
        status: Optional[ClientStatus] = None,
    ) -> Tuple[List[Client], int]:
        count_stmt = select(func.count(Client.id))
        query_stmt = select(Client).order_by(Client.created_at.desc())

        if status:
            count_stmt = count_stmt.where(Client.status == status)
            query_stmt = query_stmt.where(Client.status == status)

        total_res = await self.session.execute(count_stmt)
        total_count = total_res.scalar() or 0

        offset = max(0, (page - 1) * page_size)
        query_stmt = query_stmt.limit(page_size).offset(offset)
        result = await self.session.execute(query_stmt)
        items = list(result.scalars().all())

        return items, total_count

    async def search(self, query: str, limit: int = 20) -> List[Client]:
        clean_q = query.strip().lstrip("@")
        if not clean_q:
            return []

        conditions = [Client.username.ilike(f"%{clean_q}%")]
        if clean_q.isdigit():
            conditions.append(Client.id == int(clean_q))
            conditions.append(Client.telegram_user_id == int(clean_q))

        stmt = (
            select(Client)
            .where(or_(*conditions))
            .order_by(Client.id.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
