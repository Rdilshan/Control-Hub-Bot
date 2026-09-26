"""Add custom message campaigns and receipts.

Revision ID: 0006_message_campaigns
Revises: 0005_catchup_columns
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_message_campaigns"
down_revision = "0005_catchup_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "message_campaigns",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("creator_telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=True, unique=True),
        sa.Column("creator_client_bot_id", sa.BigInteger(), sa.ForeignKey("client_bots.id", ondelete="SET NULL"), nullable=True),
        sa.Column("audience", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("source_bot", sa.String(20), nullable=False),
        sa.Column("last_client_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("max_client_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_targets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_message_campaigns_creator_created", "message_campaigns", ["creator_telegram_user_id", "created_at"])
    op.create_table(
        "campaign_client_deliveries",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("campaign_id", sa.BigInteger(), sa.ForeignKey("message_campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.BigInteger(), sa.ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("campaign_id", "client_id", name="uq_campaign_client_delivery"),
    )
    op.alter_column("broadcasts", "video_id", existing_type=sa.BigInteger(), nullable=True)
    op.add_column("broadcasts", sa.Column("campaign_id", sa.BigInteger(), sa.ForeignKey("message_campaigns.id", ondelete="SET NULL"), nullable=True))
    op.add_column("broadcasts", sa.Column("staged_file_id", sa.String(512), nullable=True))
    op.create_index("ix_broadcasts_campaign_id", "broadcasts", ["campaign_id"])


def downgrade() -> None:
    op.drop_index("ix_broadcasts_campaign_id", table_name="broadcasts")
    op.drop_column("broadcasts", "staged_file_id")
    op.drop_column("broadcasts", "campaign_id")
    op.alter_column("broadcasts", "video_id", existing_type=sa.BigInteger(), nullable=False)
    op.drop_table("campaign_client_deliveries")
    op.drop_index("ix_message_campaigns_creator_created", table_name="message_campaigns")
    op.drop_table("message_campaigns")
