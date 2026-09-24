"""SQLAlchemy Base and common model mixins with dialect-aware primary keys."""

from datetime import datetime
from sqlalchemy import BigInteger, DateTime, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from app.core.utils import utc_now

# BigInt on PostgreSQL / MySQL, standard Integer on SQLite for proper autoincrement
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    pass


class TimestampMixin:
    """Provides UTC created_at and updated_at timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class IntegerIdMixin:
    """Provides standard integer primary key that autoincrements on all dialects."""

    id: Mapped[int] = mapped_column(
        BigIntPK,
        primary_key=True,
        autoincrement=True,
    )
