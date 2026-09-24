"""Video SQLAlchemy ORM Model."""

from datetime import datetime
from typing import List, Optional
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.enums import VideoStatus
from app.db.base import Base, IntegerIdMixin, TimestampMixin


class Video(Base, IntegerIdMixin, TimestampMixin):
    __tablename__ = "videos"

    client_bot_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("client_bots.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    created_by_admin_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("client_bot_admins.id", ondelete="SET NULL"),
        nullable=True,
    )
    telegram_file_id: Mapped[str] = mapped_column(Text, nullable=False)
    telegram_file_unique_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    telegram_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    source_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[VideoStatus] = mapped_column(
        String(50),
        default=VideoStatus.RECEIVED,
        index=True,
        nullable=False,
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        index=True,
        nullable=True,
    )

    __table_args__ = (
        Index("ix_videos_bot_created", "client_bot_id", "created_at"),
    )

    # Relationships
    bot: Mapped["ClientBot"] = relationship("ClientBot", back_populates="videos")
    processing: Mapped[Optional["VideoProcessing"]] = relationship(
        "VideoProcessing",
        back_populates="video",
        uselist=False,
        cascade="all, delete-orphan",
    )
    unlock_links: Mapped[List["UnlockLink"]] = relationship(
        "UnlockLink",
        back_populates="video",
        cascade="all, delete-orphan",
    )
    broadcasts: Mapped[List["Broadcast"]] = relationship("Broadcast", back_populates="video")
