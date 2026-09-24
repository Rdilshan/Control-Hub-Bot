"""Client Bot SQLAlchemy ORM Model."""

from datetime import datetime
from typing import List, Optional
from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.enums import ClientBotStatus
from app.core.utils import utc_now
from app.db.base import Base, IntegerIdMixin, TimestampMixin


class ClientBot(Base, IntegerIdMixin, TimestampMixin):
    __tablename__ = "client_bots"

    client_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("clients.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    telegram_bot_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    token_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[ClientBotStatus] = mapped_column(
        String(50),
        default=ClientBotStatus.ACTIVE,
        index=True,
        nullable=False,
    )
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    paused_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    disconnected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    client: Mapped["Client"] = relationship("Client", back_populates="bots")
    settings: Mapped[Optional["ClientBotSettings"]] = relationship(
        "ClientBotSettings",
        back_populates="bot",
        uselist=False,
        cascade="all, delete-orphan",
    )
    sponsor_config: Mapped[Optional["SponsorConfig"]] = relationship(
        "SponsorConfig",
        back_populates="bot",
        uselist=False,
        cascade="all, delete-orphan",
    )
    admins: Mapped[List["ClientBotAdmin"]] = relationship(
        "ClientBotAdmin",
        back_populates="bot",
        cascade="all, delete-orphan",
    )
    viewers: Mapped[List["Viewer"]] = relationship("Viewer", back_populates="bot")
    videos: Mapped[List["Video"]] = relationship("Video", back_populates="bot")
    broadcasts: Mapped[List["Broadcast"]] = relationship("Broadcast", back_populates="bot")
    events: Mapped[List["BotEvent"]] = relationship("BotEvent", back_populates="bot")
