"""Client SQLAlchemy ORM Model."""

from datetime import datetime
from typing import List, Optional
from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.enums import ClientStatus
from app.db.base import Base, IntegerIdMixin, TimestampMixin


class Client(Base, IntegerIdMixin, TimestampMixin):
    __tablename__ = "clients"

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[ClientStatus] = mapped_column(
        String(50),
        default=ClientStatus.ACTIVE,
        index=True,
        nullable=False,
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    bots: Mapped[List["ClientBot"]] = relationship(
        "ClientBot",
        back_populates="client",
        cascade="all, delete-orphan",
    )
