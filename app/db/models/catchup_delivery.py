"""Catch-Up Delivery SQLAlchemy ORM Model."""

from datetime import datetime
from typing import Optional
from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.core.enums import CatchupStatus
from app.db.base import Base, IntegerIdMixin, TimestampMixin


class CatchupDelivery(Base, IntegerIdMixin, TimestampMixin):
    __tablename__ = "catchup_deliveries"

    client_bot_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("client_bots.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    viewer_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("viewers.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    video_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("videos.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    status: Mapped[CatchupStatus] = mapped_column(
        String(50),
        default=CatchupStatus.PENDING,
        index=True,
        nullable=False,
    )
    broadcast_delivery_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("viewer_id", "video_id", name="uq_catchup_viewer_video"),
    )
