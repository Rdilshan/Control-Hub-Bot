"""Bot Event SQLAlchemy ORM Model."""

from datetime import datetime
from typing import Any, Dict, Optional
from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.enums import BotEventType
from app.core.utils import utc_now
from app.db.base import Base, IntegerIdMixin


class BotEvent(Base, IntegerIdMixin):
    __tablename__ = "bot_events"

    client_bot_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("client_bots.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    event_type: Mapped[BotEventType] = mapped_column(String(50), index=True, nullable=False)
    telegram_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    related_video_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    related_broadcast_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    # Relationships
    bot: Mapped["ClientBot"] = relationship("ClientBot", back_populates="events")
