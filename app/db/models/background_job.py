"""Background Job SQLAlchemy ORM Model."""

from datetime import datetime
from typing import Any, Dict, Optional
from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.enums import JobStatus, JobType
from app.core.utils import utc_now
from app.db.base import Base, IntegerIdMixin, TimestampMixin


class BackgroundJob(Base, IntegerIdMixin, TimestampMixin):
    __tablename__ = "background_jobs"

    job_type: Mapped[JobType] = mapped_column(String(50), index=True, nullable=False)
    client_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("clients.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    client_bot_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("client_bots.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    video_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("videos.id", ondelete="SET NULL"),
        nullable=True,
    )
    broadcast_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("broadcasts.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[JobStatus] = mapped_column(
        String(50),
        default=JobStatus.PENDING,
        index=True,
        nullable=False,
    )
    queue_name: Mapped[str] = mapped_column(String(100), default="default", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    last_error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        index=True,
        nullable=False,
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_jobs_status_scheduled", "status", "scheduled_at"),
    )
