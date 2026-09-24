"""Broadcast SQLAlchemy ORM Model."""

from datetime import datetime
from typing import List, Optional
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.enums import BroadcastStatus
from app.db.base import Base, IntegerIdMixin, TimestampMixin


class Broadcast(Base, IntegerIdMixin, TimestampMixin):
    __tablename__ = "broadcasts"

    client_bot_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("client_bots.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    video_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("videos.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    created_by_admin_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("client_bot_admins.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[BroadcastStatus] = mapped_column(
        String(50),
        default=BroadcastStatus.PENDING,
        index=True,
        nullable=False,
    )
    target_type: Mapped[str] = mapped_column(String(100), default="ALL_ACTIVE_VIEWERS", nullable=False)
    total_targets: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    blocked_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_broadcasts_bot_created", "client_bot_id", "created_at"),
    )

    # Relationships
    bot: Mapped["ClientBot"] = relationship("ClientBot", back_populates="broadcasts")
    video: Mapped["Video"] = relationship("Video", back_populates="broadcasts")
    deliveries: Mapped[List["BroadcastDelivery"]] = relationship(
        "BroadcastDelivery",
        back_populates="broadcast",
        cascade="all, delete-orphan",
    )
