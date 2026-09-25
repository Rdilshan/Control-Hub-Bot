"""Processed Telegram Update Deduplication Model."""

from sqlalchemy import BigInteger, DateTime, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.core.utils import utc_now
from app.db.base import Base, IntegerIdMixin, TimestampMixin


class ProcessedTelegramUpdate(Base, IntegerIdMixin, TimestampMixin):
    __tablename__ = "processed_telegram_updates"

    client_bot_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    telegram_update_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="PROCESSED", nullable=False)

    __table_args__ = (
        UniqueConstraint("client_bot_id", "telegram_update_id", name="uq_bot_telegram_update"),
        Index("ix_processed_updates_bot_update", "client_bot_id", "telegram_update_id"),
    )
