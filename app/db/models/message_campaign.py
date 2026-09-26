"""Custom message campaigns and Control Hub recipient receipts."""

from typing import Any, Optional
from sqlalchemy import BigInteger, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, IntegerIdMixin, TimestampMixin


class MessageCampaign(Base, IntegerIdMixin, TimestampMixin):
    __tablename__ = "message_campaigns"

    creator_telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), unique=True, nullable=True)
    creator_client_bot_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("client_bots.id", ondelete="SET NULL"), nullable=True)
    audience: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    source_bot: Mapped[str] = mapped_column(String(20), nullable=False)
    last_client_id: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    max_client_id: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_targets: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    blocked_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (Index("ix_message_campaigns_creator_created", "creator_telegram_user_id", "created_at"),)


class CampaignClientDelivery(Base, IntegerIdMixin, TimestampMixin):
    __tablename__ = "campaign_client_deliveries"

    campaign_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("message_campaigns.id", ondelete="CASCADE"), nullable=False)
    client_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    telegram_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (UniqueConstraint("campaign_id", "client_id", name="uq_campaign_client_delivery"),)
