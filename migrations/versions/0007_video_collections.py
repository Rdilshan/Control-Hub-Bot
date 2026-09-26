"""Video collections and original Telegram send times.

Revision ID: 0007_video_collections
Revises: 0006_message_campaigns
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_video_collections"
down_revision = "0006_message_campaigns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("videos", sa.Column("source_sent_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "video_collections",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("client_bot_id", sa.BigInteger(), sa.ForeignKey("client_bots.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("owner_telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("representative_video_id", sa.BigInteger(), sa.ForeignKey("videos.id", ondelete="SET NULL"), unique=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("thumbnail_file_id", sa.Text()),
        sa.Column("caption", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_collection_owner_status", "video_collections", ["client_bot_id", "owner_telegram_user_id", "status"])
    op.create_table(
        "video_collection_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("collection_id", sa.BigInteger(), sa.ForeignKey("video_collections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("telegram_file_id", sa.Text(), nullable=False),
        sa.Column("telegram_file_unique_id", sa.String(255), nullable=False),
        sa.Column("source_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=False),
        sa.Column("source_sent_at", sa.DateTime(timezone=True)),
        sa.Column("caption", sa.Text()),
        sa.Column("duration_seconds", sa.Integer()),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("collection_id", "source_chat_id", "telegram_message_id", name="uq_collection_item_message"),
    )
    op.create_index("ix_collection_item_order", "video_collection_items", ["collection_id", "telegram_message_id"])
    op.create_table(
        "collection_item_deliveries",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("collection_id", sa.BigInteger(), sa.ForeignKey("video_collections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", sa.BigInteger(), sa.ForeignKey("video_collection_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("viewer_id", sa.BigInteger(), sa.ForeignKey("viewers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger()),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("item_id", "viewer_id", name="uq_collection_item_viewer"),
    )


def downgrade() -> None:
    op.drop_table("collection_item_deliveries")
    op.drop_index("ix_collection_item_order", table_name="video_collection_items")
    op.drop_table("video_collection_items")
    op.drop_index("ix_collection_owner_status", table_name="video_collections")
    op.drop_table("video_collections")
    op.drop_column("videos", "source_sent_at")
