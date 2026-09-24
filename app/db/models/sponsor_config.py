"""Sponsor Configuration SQLAlchemy ORM Model."""

from typing import Optional
from sqlalchemy import BigInteger, Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, IntegerIdMixin, TimestampMixin


class SponsorConfig(Base, IntegerIdMixin, TimestampMixin):
    __tablename__ = "sponsor_configs"

    client_bot_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("client_bots.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sponsor_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sponsor_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sponsor_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    button_text: Mapped[str] = mapped_column(String(255), default="🔓 Unlock Video", nullable=False)

    # Relationships
    bot: Mapped["ClientBot"] = relationship("ClientBot", back_populates="sponsor_config")
