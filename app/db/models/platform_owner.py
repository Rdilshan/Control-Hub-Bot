"""Platform Owner SQLAlchemy ORM Model."""

from typing import Optional
from sqlalchemy import BigInteger, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, IntegerIdMixin, TimestampMixin


class PlatformOwner(Base, IntegerIdMixin, TimestampMixin):
    __tablename__ = "platform_owners"

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
