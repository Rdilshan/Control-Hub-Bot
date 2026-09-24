"""Broadcast Delivery SQLAlchemy ORM Model."""

from datetime import datetime
from typing import Optional
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.enums import DeliveryStatus
from app.db.base import Base, IntegerIdMixin, TimestampMixin


class BroadcastDelivery(Base, IntegerIdMixin, TimestampMixin):
    __tablename__ = "broadcast_deliveries"

    broadcast_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("broadcasts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    viewer_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("viewers.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    status: Mapped[DeliveryStatus] = mapped_column(
        String(50),
        default=DeliveryStatus.PENDING,
        index=True,
        nullable=False,
    )
    telegram_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("broadcast_id", "viewer_id", name="uq_broadcast_viewer_delivery"),
        Index("ix_broadcast_deliveries_bcast_status", "broadcast_id", "status"),
    )

    # Relationships
    broadcast: Mapped["Broadcast"] = relationship("Broadcast", back_populates="deliveries")
