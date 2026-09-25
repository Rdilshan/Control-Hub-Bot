"""lifecycle_and_extended_schema

Revision ID: 0004_lifecycle_and_extended_schema
Revises: 0003_video_creation
Create Date: 2026-09-25 10:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0004_lifecycle_and_extended_schema"
down_revision: Union[str, None] = "0003_video_creation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. client_bots missing lifecycle columns
    op.add_column("client_bots", sa.Column("last_status_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("client_bots", sa.Column("status_reason", sa.String(length=255), nullable=True))
    op.add_column("client_bots", sa.Column("desired_status", sa.String(length=50), nullable=True))
    op.add_column("client_bots", sa.Column("lifecycle_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False))

    # 2. background_jobs extended columns
    op.add_column("background_jobs", sa.Column("resource_type", sa.String(length=50), nullable=True))
    op.add_column("background_jobs", sa.Column("resource_id", sa.BigInteger(), nullable=True))
    op.add_column("background_jobs", sa.Column("priority", sa.Integer(), server_default=sa.text("0"), nullable=False))
    op.add_column("background_jobs", sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.add_column("background_jobs", sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("background_jobs", sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("background_jobs", sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("background_jobs", sa.Column("deduplication_key", sa.String(length=255), nullable=True))
    op.add_column("background_jobs", sa.Column("correlation_id", sa.String(length=100), nullable=True))
    op.add_column("background_jobs", sa.Column("parent_job_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key("fk_background_jobs_parent_job_id", "background_jobs", "background_jobs", ["parent_job_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_jobs_status_available", "background_jobs", ["status", "available_at"], unique=False)
    op.create_index(op.f("ix_background_jobs_deduplication_key"), "background_jobs", ["deduplication_key"], unique=False)

    # 3. broadcasts extended columns
    op.add_column("broadcasts", sa.Column("broadcast_type", sa.String(length=50), server_default="LIVE", nullable=False))
    op.add_column("broadcasts", sa.Column("audience_max_viewer_id", sa.BigInteger(), nullable=True))
    op.add_column("broadcasts", sa.Column("last_processed_viewer_id", sa.BigInteger(), nullable=True))
    op.add_column("broadcasts", sa.Column("last_error_code", sa.String(length=100), nullable=True))
    op.add_column("broadcasts", sa.Column("last_error_message", sa.String(length=1000), nullable=True))
    op.create_index("ix_broadcasts_bot_status", "broadcasts", ["client_bot_id", "status"], unique=False)

    # 4. catchup_deliveries missing index
    op.create_index("ix_catchup_deliveries_viewer_status", "catchup_deliveries", ["viewer_id", "status"], unique=False)

    # 5. viewer_catchup table
    op.create_table(
        "viewer_catchup",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("client_bot_id", sa.BigInteger(), nullable=False),
        sa.Column("viewer_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="PENDING", nullable=False),
        sa.Column("last_video_id", sa.BigInteger(), nullable=True),
        sa.Column("target_max_video_id", sa.BigInteger(), nullable=True),
        sa.Column("total_eligible", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("delivered_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("paused_reason", sa.String(length=100), nullable=True),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["client_bot_id"], ["client_bots.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["viewer_id"], ["viewers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("viewer_id"),
    )
    op.create_index(op.f("ix_viewer_catchup_client_bot_id"), "viewer_catchup", ["client_bot_id"], unique=False)
    op.create_index(op.f("ix_viewer_catchup_status"), "viewer_catchup", ["status"], unique=False)
    op.create_index(op.f("ix_viewer_catchup_viewer_id"), "viewer_catchup", ["viewer_id"], unique=True)
    op.create_index("ix_viewer_catchup_bot_status", "viewer_catchup", ["client_bot_id", "status"], unique=False)

    # 6. video_deliveries table
    op.create_table(
        "video_deliveries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("client_bot_id", sa.BigInteger(), nullable=False),
        sa.Column("video_id", sa.BigInteger(), nullable=False),
        sa.Column("viewer_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("delivery_type", sa.String(length=50), server_default="UNLOCK", nullable=False),
        sa.Column("status", sa.String(length=50), server_default="PENDING", nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["client_bot_id"], ["client_bots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["viewer_id"], ["viewers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_video_deliveries_client_bot_id"), "video_deliveries", ["client_bot_id"], unique=False)
    op.create_index(op.f("ix_video_deliveries_delivery_type"), "video_deliveries", ["delivery_type"], unique=False)
    op.create_index(op.f("ix_video_deliveries_status"), "video_deliveries", ["status"], unique=False)
    op.create_index(op.f("ix_video_deliveries_telegram_user_id"), "video_deliveries", ["telegram_user_id"], unique=False)
    op.create_index(op.f("ix_video_deliveries_video_id"), "video_deliveries", ["video_id"], unique=False)
    op.create_index(op.f("ix_video_deliveries_viewer_id"), "video_deliveries", ["viewer_id"], unique=False)
    op.create_index("ix_video_deliveries_bot_video", "video_deliveries", ["client_bot_id", "video_id"], unique=False)
    op.create_index("ix_video_deliveries_viewer", "video_deliveries", ["viewer_id", "video_id"], unique=False)

    # 7. processed_telegram_updates table
    op.create_table(
        "processed_telegram_updates",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("client_bot_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_update_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="PROCESSED", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_bot_id", "telegram_update_id", name="uq_bot_telegram_update"),
    )
    op.create_index(op.f("ix_processed_telegram_updates_client_bot_id"), "processed_telegram_updates", ["client_bot_id"], unique=False)
    op.create_index(op.f("ix_processed_telegram_updates_telegram_update_id"), "processed_telegram_updates", ["telegram_update_id"], unique=False)
    op.create_index("ix_processed_updates_bot_update", "processed_telegram_updates", ["client_bot_id", "telegram_update_id"], unique=False)


def downgrade() -> None:
    # 7. processed_telegram_updates
    op.drop_index("ix_processed_updates_bot_update", table_name="processed_telegram_updates")
    op.drop_index(op.f("ix_processed_telegram_updates_telegram_update_id"), table_name="processed_telegram_updates")
    op.drop_index(op.f("ix_processed_telegram_updates_client_bot_id"), table_name="processed_telegram_updates")
    op.drop_table("processed_telegram_updates")

    # 6. video_deliveries
    op.drop_index("ix_video_deliveries_viewer", table_name="video_deliveries")
    op.drop_index("ix_video_deliveries_bot_video", table_name="video_deliveries")
    op.drop_index(op.f("ix_video_deliveries_viewer_id"), table_name="video_deliveries")
    op.drop_index(op.f("ix_video_deliveries_video_id"), table_name="video_deliveries")
    op.drop_index(op.f("ix_video_deliveries_telegram_user_id"), table_name="video_deliveries")
    op.drop_index(op.f("ix_video_deliveries_status"), table_name="video_deliveries")
    op.drop_index(op.f("ix_video_deliveries_delivery_type"), table_name="video_deliveries")
    op.drop_index(op.f("ix_video_deliveries_client_bot_id"), table_name="video_deliveries")
    op.drop_table("video_deliveries")

    # 5. viewer_catchup
    op.drop_index("ix_viewer_catchup_bot_status", table_name="viewer_catchup")
    op.drop_index(op.f("ix_viewer_catchup_viewer_id"), table_name="viewer_catchup")
    op.drop_index(op.f("ix_viewer_catchup_status"), table_name="viewer_catchup")
    op.drop_index(op.f("ix_viewer_catchup_client_bot_id"), table_name="viewer_catchup")
    op.drop_table("viewer_catchup")

    # 4. catchup_deliveries
    op.drop_index("ix_catchup_deliveries_viewer_status", table_name="catchup_deliveries")

    # 3. broadcasts
    op.drop_index("ix_broadcasts_bot_status", table_name="broadcasts")
    op.drop_column("broadcasts", "last_error_message")
    op.drop_column("broadcasts", "last_error_code")
    op.drop_column("broadcasts", "last_processed_viewer_id")
    op.drop_column("broadcasts", "audience_max_viewer_id")
    op.drop_column("broadcasts", "broadcast_type")

    # 2. background_jobs
    op.drop_index(op.f("ix_background_jobs_deduplication_key"), table_name="background_jobs")
    op.drop_index("ix_jobs_status_available", table_name="background_jobs")
    op.drop_constraint("fk_background_jobs_parent_job_id", "background_jobs", type_="foreignkey")
    op.drop_column("background_jobs", "parent_job_id")
    op.drop_column("background_jobs", "correlation_id")
    op.drop_column("background_jobs", "deduplication_key")
    op.drop_column("background_jobs", "last_heartbeat_at")
    op.drop_column("background_jobs", "last_attempt_at")
    op.drop_column("background_jobs", "queued_at")
    op.drop_column("background_jobs", "available_at")
    op.drop_column("background_jobs", "priority")
    op.drop_column("background_jobs", "resource_id")
    op.drop_column("background_jobs", "resource_type")

    # 1. client_bots
    op.drop_column("client_bots", "lifecycle_version")
    op.drop_column("client_bots", "desired_status")
    op.drop_column("client_bots", "status_reason")
    op.drop_column("client_bots", "last_status_changed_at")
