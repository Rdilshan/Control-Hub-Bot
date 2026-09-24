"""Viewer SQLAlchemy ORM Model."""

from datetime import datetime
from typing import Optional
from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.enums import ViewerStatus
from app.core.utils import utc_now
from app.db.base import Base, IntegerIdMixin, TimestampMixin


class Viewer(Base, IntegerIdMixin, TimestampMixin):
    __tablename__ = "viewers"

    client_bot_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("client_bots.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    language_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    status: Mapped[ViewerStatus] = mapped_column(
        String(50),
        default=ViewerStatus.ACTIVE,
        index=True,
        nullable=False,
    )
    first_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    last_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        index=True,
        nullable=False,
    )
    blocked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("client_bot_id", "telegram_user_id", name="uq_bot_viewer_pair"),
    )

    # Relationships
    bot: Mapped["ClientBot"] = relationship("ClientBot", back_populates="viewers")
