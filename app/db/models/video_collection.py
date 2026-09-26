"""A draft or published group of videos represented by one video post."""

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntegerIdMixin, TimestampMixin


class VideoCollection(Base, IntegerIdMixin, TimestampMixin):
    __tablename__ = "video_collections"

    client_bot_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("client_bots.id", ondelete="RESTRICT"), nullable=False)
    owner_telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    representative_video_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("videos.id", ondelete="SET NULL"), unique=True, nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    thumbnail_file_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_collection_owner_status", "client_bot_id", "owner_telegram_user_id", "status"),)


class VideoCollectionItem(Base, IntegerIdMixin, TimestampMixin):
    __tablename__ = "video_collection_items"

    collection_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("video_collections.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    telegram_file_id: Mapped[str] = mapped_column(Text, nullable=False)
    telegram_file_unique_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("collection_id", "source_chat_id", "telegram_message_id", name="uq_collection_item_message"),
        Index("ix_collection_item_order", "collection_id", "telegram_message_id"),
    )


class CollectionItemDelivery(Base, IntegerIdMixin, TimestampMixin):
    __tablename__ = "collection_item_deliveries"

    collection_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("video_collections.id", ondelete="CASCADE"), nullable=False)
    item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("video_collection_items.id", ondelete="CASCADE"), nullable=False)
    viewer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("viewers.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    telegram_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("item_id", "viewer_id", name="uq_collection_item_viewer"),)
