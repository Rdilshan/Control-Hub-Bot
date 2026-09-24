"""Unlock Link SQLAlchemy ORM Model."""

from datetime import datetime
from typing import Optional
from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.enums import UnlockLinkStatus
from app.db.base import Base, IntegerIdMixin, TimestampMixin


class UnlockLink(Base, IntegerIdMixin, TimestampMixin):
    __tablename__ = "unlock_links"

    video_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("videos.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    client_bot_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("client_bots.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(100), default="unlockify", nullable=False)
    external_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[UnlockLinkStatus] = mapped_column(
        String(50),
        default=UnlockLinkStatus.ACTIVE,
        index=True,
        nullable=False,
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    video: Mapped["Video"] = relationship("Video", back_populates="unlock_links")
