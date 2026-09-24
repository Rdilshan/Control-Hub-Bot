"""add_video_creation_fields

Revision ID: 0003_video_creation
Revises: 0002_client_bot_conn
Create Date: 2026-09-24 15:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0003_video_creation"
down_revision: Union[str, None] = "0002_client_bot_conn"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("videos", sa.Column("public_id", sa.String(length=64), nullable=True))
    op.add_column("videos", sa.Column("source_thumbnail_file_id", sa.Text(), nullable=True))
    op.add_column("videos", sa.Column("source_thumbnail_file_unique_id", sa.String(length=255), nullable=True))
    
    op.create_index(op.f("ix_videos_public_id"), "videos", ["public_id"], unique=True)
    op.create_index("ix_videos_bot_status", "videos", ["client_bot_id", "status"], unique=False)
    op.create_unique_constraint("uq_videos_bot_source_message", "videos", ["client_bot_id", "source_chat_id", "telegram_message_id"])


def downgrade() -> None:
    op.drop_constraint("uq_videos_bot_source_message", "videos", type_="unique")
    op.drop_index("ix_videos_bot_status", table_name="videos")
    op.drop_index(op.f("ix_videos_public_id"), table_name="videos")
    op.drop_column("videos", "source_thumbnail_file_unique_id")
    op.drop_column("videos", "source_thumbnail_file_id")
    op.drop_column("videos", "public_id")
