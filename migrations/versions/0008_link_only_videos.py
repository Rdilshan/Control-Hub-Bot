"""Link-only video delivery mode.

Revision ID: 0008_link_only_videos
Revises: 0007_video_collections
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_link_only_videos"
down_revision = "0007_video_collections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "videos",
        sa.Column("delivery_mode", sa.String(30), nullable=False, server_default="PUBLISHED"),
    )
    op.create_check_constraint(
        "ck_videos_delivery_mode",
        "videos",
        "delivery_mode in ('PUBLISHED', 'LINK_ONLY')",
    )
    op.create_index("ix_videos_delivery_mode", "videos", ["delivery_mode"])
    op.create_index("ix_videos_bot_mode_status", "videos", ["client_bot_id", "delivery_mode", "status"])
    op.alter_column("videos", "delivery_mode", server_default=None)
    op.add_column(
        "video_collections",
        sa.Column("delivery_mode", sa.String(30), nullable=False, server_default="PUBLISHED"),
    )
    op.create_check_constraint(
        "ck_video_collections_delivery_mode",
        "video_collections",
        "delivery_mode in ('PUBLISHED', 'LINK_ONLY')",
    )
    op.alter_column("video_collections", "delivery_mode", server_default=None)


def downgrade() -> None:
    op.drop_constraint("ck_video_collections_delivery_mode", "video_collections", type_="check")
    op.drop_column("video_collections", "delivery_mode")
    op.drop_index("ix_videos_bot_mode_status", table_name="videos")
    op.drop_index("ix_videos_delivery_mode", table_name="videos")
    op.drop_constraint("ck_videos_delivery_mode", "videos", type_="check")
    op.drop_column("videos", "delivery_mode")
