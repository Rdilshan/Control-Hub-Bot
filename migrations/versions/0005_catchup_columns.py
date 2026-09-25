"""catchup_columns

Revision ID: 0005_catchup_columns
Revises: 0004_lifecycle_schema
Create Date: 2026-09-25 12:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic. Max length 32 characters.
revision: str = "0005_catchup_columns"
down_revision: Union[str, None] = "0004_lifecycle_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add missing columns to catchup_deliveries
    op.add_column(
        "catchup_deliveries",
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "catchup_deliveries",
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "catchup_deliveries",
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "catchup_deliveries",
        sa.Column("last_error_message", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("catchup_deliveries", "last_error_message")
    op.drop_column("catchup_deliveries", "last_error_code")
    op.drop_column("catchup_deliveries", "telegram_message_id")
    op.drop_column("catchup_deliveries", "attempt_count")
