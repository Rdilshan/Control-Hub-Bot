"""add_client_bot_connection_fields

Revision ID: 0002_client_bot_conn
Revises: 0001_initial_data_model
Create Date: 2026-09-24 14:35:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002_client_bot_conn"
down_revision: Union[str, None] = "0001_initial_data_model"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("client_bots", sa.Column("public_id", sa.String(length=64), nullable=True))
    op.add_column("client_bots", sa.Column("webhook_secret_encrypted", sa.Text(), nullable=True))
    op.create_index(op.f("ix_client_bots_public_id"), "client_bots", ["public_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_client_bots_public_id"), table_name="client_bots")
    op.drop_column("client_bots", "webhook_secret_encrypted")
    op.drop_column("client_bots", "public_id")
