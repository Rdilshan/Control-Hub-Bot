"""Client Bot Settings SQLAlchemy ORM Model."""

from typing import Optional
from sqlalchemy import BigInteger, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, IntegerIdMixin, TimestampMixin


class ClientBotSettings(Base, IntegerIdMixin, TimestampMixin):
    __tablename__ = "client_bot_settings"

    client_bot_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("client_bots.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    start_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    default_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    bot: Mapped["ClientBot"] = relationship("ClientBot", back_populates="settings")
