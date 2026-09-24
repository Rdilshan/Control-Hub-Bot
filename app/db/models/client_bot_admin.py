"""Client Bot Admin SQLAlchemy ORM Model."""

from typing import Optional
from sqlalchemy import BigInteger, Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.enums import BotAdminRole
from app.db.base import Base, IntegerIdMixin, TimestampMixin


class ClientBotAdmin(Base, IntegerIdMixin, TimestampMixin):
    __tablename__ = "client_bot_admins"

    client_bot_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("client_bots.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[BotAdminRole] = mapped_column(
        String(50),
        default=BotAdminRole.OWNER,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        UniqueConstraint("client_bot_id", "telegram_user_id", name="uq_bot_admin_pair"),
    )

    # Relationships
    bot: Mapped["ClientBot"] = relationship("ClientBot", back_populates="admins")
