"""Video Delivery SQLAlchemy ORM Model."""

from datetime import datetime
from typing import Optional
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.enums import DeliveryStatus
from app.db.base import Base, IntegerIdMixin, TimestampMixin


class VideoDelivery(Base, IntegerIdMixin, TimestampMixin):
    __tablename__ = "video_deliveries"

    client_bot_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("client_bots.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    video_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("videos.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    viewer_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("viewers.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    telegram_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
        index=True,
    )
    delivery_type: Mapped[str] = mapped_column(
        String(50),
        default="UNLOCK",
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
    error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_video_deliveries_bot_video", "client_bot_id", "video_id"),
        Index("ix_video_deliveries_viewer", "viewer_id", "video_id"),
    )

    # Relationships
    bot: Mapped["ClientBot"] = relationship("ClientBot")
    video: Mapped["Video"] = relationship("Video")
    viewer: Mapped[Optional["Viewer"]] = relationship("Viewer")
