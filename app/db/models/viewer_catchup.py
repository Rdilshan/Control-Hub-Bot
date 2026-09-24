"""Viewer Catch-Up State SQLAlchemy ORM Model."""

from datetime import datetime
from typing import Optional
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.enums import CatchupStatus
from app.db.base import Base, IntegerIdMixin, TimestampMixin


class ViewerCatchup(Base, IntegerIdMixin, TimestampMixin):
    __tablename__ = "viewer_catchup"

    client_bot_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("client_bots.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    viewer_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("viewers.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    status: Mapped[CatchupStatus] = mapped_column(
        String(50),
        default=CatchupStatus.PENDING,
        index=True,
        nullable=False,
    )
    last_video_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    target_max_video_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    total_eligible: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    delivered_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    paused_reason: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_attempted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_viewer_catchup_bot_status", "client_bot_id", "status"),
    )

    # Relationships
    bot: Mapped["ClientBot"] = relationship("ClientBot")
    viewer: Mapped["Viewer"] = relationship("Viewer")
