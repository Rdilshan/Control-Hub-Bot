"""Client Bot Repository."""

from datetime import datetime
from typing import List, Optional, Tuple
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import BotAdminRole, BotEventType, ClientBotStatus
from app.core.security import decrypt_token, encrypt_token
from app.core.utils import utc_now
from app.db.models.bot_event import BotEvent
from app.db.models.client_bot import ClientBot
from app.db.models.client_bot_admin import ClientBotAdmin
from app.db.models.client_bot_settings import ClientBotSettings
from app.db.models.sponsor_config import SponsorConfig
from app.repositories.base import BaseRepository


class ClientBotRepository(BaseRepository[ClientBot]):
    def __init__(self, session: AsyncSession):
        super().__init__(ClientBot, session)

    async def get_by_id(self, bot_id: int) -> Optional[ClientBot]:
        stmt = select(ClientBot).where(ClientBot.id == bot_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_and_client(self, bot_id: int, client_id: int) -> Optional[ClientBot]:
        stmt = select(ClientBot).where(
            ClientBot.id == bot_id,
            ClientBot.client_id == client_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_telegram_bot_id(self, telegram_bot_id: int) -> Optional[ClientBot]:
        stmt = select(ClientBot).where(ClientBot.telegram_bot_id == telegram_bot_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_public_id(self, public_id: str) -> Optional[ClientBot]:
        stmt = select(ClientBot).where(ClientBot.public_id == public_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_client(self, client_id: int) -> List[ClientBot]:
        stmt = select(ClientBot).where(ClientBot.client_id == client_id).order_by(ClientBot.id.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_with_defaults(
        self,
        client_id: int,
        telegram_bot_id: int,
        token: str,
        username: Optional[str] = None,
        display_name: Optional[str] = None,
        owner_telegram_user_id: Optional[int] = None,
        owner_username: Optional[str] = None,
        owner_first_name: Optional[str] = None,
    ) -> ClientBot:
        """Creates a client bot along with default settings, default sponsor config, and owner admin."""
        encrypted_token = encrypt_token(token)

        bot = ClientBot(
            client_id=client_id,
            telegram_bot_id=telegram_bot_id,
            username=username,
            display_name=display_name or username,
            token_encrypted=encrypted_token,
            status=ClientBotStatus.ACTIVE,
            connected_at=utc_now(),
            last_verified_at=utc_now(),
        )
        self.session.add(bot)
        await self.session.flush()

        # 1. Add Default Settings
        settings = ClientBotSettings(
            client_bot_id=bot.id,
            start_message=f"👋 Welcome to @{username or 'our bot'}! Use /help to get started.",
            default_message="👋 Hello! Please use the video posts and unlock button to watch.",
        )
        self.session.add(settings)

        # 2. Add Default Sponsor Config (disabled by default)
        sponsor = SponsorConfig(
            client_bot_id=bot.id,
            is_enabled=False,
            button_text="🔓 Unlock Video",
        )
        self.session.add(sponsor)

        # 3. Add Owner as Admin if owner_telegram_user_id provided
        if owner_telegram_user_id:
            admin = ClientBotAdmin(
                client_bot_id=bot.id,
                telegram_user_id=owner_telegram_user_id,
                username=owner_username,
                first_name=owner_first_name,
                role=BotAdminRole.OWNER,
                is_active=True,
            )
            self.session.add(admin)

        # 4. Record event
        event = BotEvent(
            client_bot_id=bot.id,
            event_type=BotEventType.BOT_CONNECTED,
            telegram_user_id=owner_telegram_user_id,
            metadata_json={"username": username, "telegram_bot_id": telegram_bot_id},
        )
        self.session.add(event)

        await self.session.flush()
        return bot

    async def get_decrypted_token(self, bot_id: int) -> Optional[str]:
        bot = await self.get_by_id(bot_id)
        if not bot or not bot.token_encrypted:
            return None
        return decrypt_token(bot.token_encrypted)

    async def pause_bot(self, bot_id: int) -> Optional[ClientBot]:
        bot = await self.get_by_id(bot_id)
        if bot:
            bot.status = ClientBotStatus.PAUSED
            bot.paused_at = utc_now()
            
            event = BotEvent(
                client_bot_id=bot.id,
                event_type=BotEventType.BOT_PAUSED,
                metadata_json={"paused_at": bot.paused_at.isoformat()},
            )
            self.session.add(event)
            await self.session.flush()
        return bot

    async def resume_bot(self, bot_id: int) -> Optional[ClientBot]:
        bot = await self.get_by_id(bot_id)
        if bot:
            bot.status = ClientBotStatus.ACTIVE
            bot.paused_at = None
            
            event = BotEvent(
                client_bot_id=bot.id,
                event_type=BotEventType.BOT_RESUMED,
                metadata_json={"resumed_at": utc_now().isoformat()},
            )
            self.session.add(event)
            await self.session.flush()
        return bot

    async def disconnect_bot(self, bot_id: int) -> Optional[ClientBot]:
        bot = await self.get_by_id(bot_id)
        if bot:
            bot.status = ClientBotStatus.DISCONNECTED
            bot.disconnected_at = utc_now()
            bot.token_encrypted = None  # Revoke token on disconnect
            
            event = BotEvent(
                client_bot_id=bot.id,
                event_type=BotEventType.BOT_DISCONNECTED,
                metadata_json={"disconnected_at": bot.disconnected_at.isoformat()},
            )
            self.session.add(event)
            await self.session.flush()
        return bot

    async def update_status(self, bot_id: int, status: ClientBotStatus) -> Optional[ClientBot]:
        bot = await self.get_by_id(bot_id)
        if bot:
            bot.status = status
            await self.session.flush()
        return bot

    async def count_all(self) -> int:
        stmt = select(func.count(ClientBot.id))
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def count_by_status(self, status: ClientBotStatus) -> int:
        stmt = select(func.count(ClientBot.id)).where(ClientBot.status == status)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def count_created_since(self, since: datetime) -> int:
        stmt = select(func.count(ClientBot.id)).where(ClientBot.created_at >= since)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def list_paginated(
        self,
        page: int = 1,
        page_size: int = 10,
        status: Optional[ClientBotStatus] = None,
    ) -> Tuple[List[ClientBot], int]:
        count_stmt = select(func.count(ClientBot.id))
        query_stmt = select(ClientBot).order_by(ClientBot.created_at.desc())

        if status:
            count_stmt = count_stmt.where(ClientBot.status == status)
            query_stmt = query_stmt.where(ClientBot.status == status)

        total_res = await self.session.execute(count_stmt)
        total_count = total_res.scalar() or 0

        offset = max(0, (page - 1) * page_size)
        query_stmt = query_stmt.limit(page_size).offset(offset)
        result = await self.session.execute(query_stmt)
        items = list(result.scalars().all())

        return items, total_count

    async def search(self, query: str, limit: int = 20) -> List[ClientBot]:
        clean_q = query.strip().lstrip("@")
        if not clean_q:
            return []

        conditions = [ClientBot.username.ilike(f"%{clean_q}%")]
        if clean_q.isdigit():
            conditions.append(ClientBot.id == int(clean_q))
            conditions.append(ClientBot.telegram_bot_id == int(clean_q))

        stmt = (
            select(ClientBot)
            .where(or_(*conditions))
            .order_by(ClientBot.id.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
