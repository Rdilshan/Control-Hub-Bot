"""Video Processing SQLAlchemy ORM Model."""

from datetime import datetime
from typing import Optional
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.enums import ProcessingStatus
from app.db.base import Base, IntegerIdMixin, TimestampMixin


class VideoProcessing(Base, IntegerIdMixin, TimestampMixin):
    __tablename__ = "video_processing"

    video_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("videos.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    status: Mapped[ProcessingStatus] = mapped_column(
        String(50),
        default=ProcessingStatus.PENDING,
        index=True,
        nullable=False,
    )
    thumbnail_file_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    thumbnail_path_or_reference: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    unlock_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    processing_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    video: Mapped["Video"] = relationship("Video", back_populates="processing")
