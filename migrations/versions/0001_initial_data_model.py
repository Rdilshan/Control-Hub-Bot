"""initial_data_model

Revision ID: 0001_initial_data_model
Revises: 
Create Date: 2026-09-24 12:45:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001_initial_data_model"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Platform Owners
    op.create_table(
        "platform_owners",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_user_id"),
    )
    op.create_index(op.f("ix_platform_owners_telegram_user_id"), "platform_owners", ["telegram_user_id"], unique=True)

    # 2. Clients
    op.create_table(
        "clients",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_user_id"),
    )
    op.create_index(op.f("ix_clients_status"), "clients", ["status"], unique=False)
    op.create_index(op.f("ix_clients_telegram_user_id"), "clients", ["telegram_user_id"], unique=True)

    # 3. Client Bots
    op.create_table(
        "client_bots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_bot_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("token_encrypted", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_bot_id"),
    )
    op.create_index(op.f("ix_client_bots_client_id"), "client_bots", ["client_id"], unique=False)
    op.create_index(op.f("ix_client_bots_status"), "client_bots", ["status"], unique=False)
    op.create_index(op.f("ix_client_bots_telegram_bot_id"), "client_bots", ["telegram_bot_id"], unique=True)

    # 4. Client Bot Admins
    op.create_table(
        "client_bot_admins",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("client_bot_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["client_bot_id"], ["client_bots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_bot_id", "telegram_user_id", name="uq_bot_admin_pair"),
    )
    op.create_index(op.f("ix_client_bot_admins_client_bot_id"), "client_bot_admins", ["client_bot_id"], unique=False)
    op.create_index(op.f("ix_client_bot_admins_telegram_user_id"), "client_bot_admins", ["telegram_user_id"], unique=False)

    # 5. Client Bot Settings
    op.create_table(
        "client_bot_settings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("client_bot_id", sa.BigInteger(), nullable=False),
        sa.Column("start_message", sa.Text(), nullable=True),
        sa.Column("default_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["client_bot_id"], ["client_bots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_bot_id"),
    )
    op.create_index(op.f("ix_client_bot_settings_client_bot_id"), "client_bot_settings", ["client_bot_id"], unique=True)

    # 6. Sponsor Configs
    op.create_table(
        "sponsor_configs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("client_bot_id", sa.BigInteger(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("sponsor_name", sa.String(length=255), nullable=True),
        sa.Column("sponsor_text", sa.Text(), nullable=True),
        sa.Column("sponsor_url", sa.Text(), nullable=True),
        sa.Column("button_text", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["client_bot_id"], ["client_bots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_bot_id"),
    )
    op.create_index(op.f("ix_sponsor_configs_client_bot_id"), "sponsor_configs", ["client_bot_id"], unique=True)

    # 7. Viewers
    op.create_table(
        "viewers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("client_bot_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column("language_code", sa.String(length=10), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("first_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["client_bot_id"], ["client_bots.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_bot_id", "telegram_user_id", name="uq_bot_viewer_pair"),
    )
    op.create_index(op.f("ix_viewers_client_bot_id"), "viewers", ["client_bot_id"], unique=False)
    op.create_index(op.f("ix_viewers_last_seen_at"), "viewers", ["last_seen_at"], unique=False)
    op.create_index(op.f("ix_viewers_status"), "viewers", ["status"], unique=False)
    op.create_index(op.f("ix_viewers_telegram_user_id"), "viewers", ["telegram_user_id"], unique=False)

    # 8. Videos
    op.create_table(
        "videos",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("client_bot_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by_admin_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_file_id", sa.Text(), nullable=False),
        sa.Column("telegram_file_unique_id", sa.String(length=255), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("source_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("file_name", sa.Text(), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["client_bot_id"], ["client_bots.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_admin_id"], ["client_bot_admins.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_videos_bot_created", "videos", ["client_bot_id", "created_at"], unique=False)
    op.create_index(op.f("ix_videos_client_bot_id"), "videos", ["client_bot_id"], unique=False)
    op.create_index(op.f("ix_videos_published_at"), "videos", ["published_at"], unique=False)
    op.create_index(op.f("ix_videos_status"), "videos", ["status"], unique=False)
    op.create_index(op.f("ix_videos_telegram_file_unique_id"), "videos", ["telegram_file_unique_id"], unique=False)

    # 9. Video Processing
    op.create_table(
        "video_processing",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("video_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("thumbnail_file_id", sa.Text(), nullable=True),
        sa.Column("thumbnail_path_or_reference", sa.Text(), nullable=True),
        sa.Column("unlock_url", sa.Text(), nullable=True),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("video_id"),
    )
    op.create_index(op.f("ix_video_processing_status"), "video_processing", ["status"], unique=False)
    op.create_index(op.f("ix_video_processing_video_id"), "video_processing", ["video_id"], unique=True)

    # 10. Unlock Links
    op.create_table(
        "unlock_links",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("video_id", sa.BigInteger(), nullable=False),
        sa.Column("client_bot_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("external_reference", sa.String(length=255), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["client_bot_id"], ["client_bots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_unlock_links_client_bot_id"), "unlock_links", ["client_bot_id"], unique=False)
    op.create_index(op.f("ix_unlock_links_status"), "unlock_links", ["status"], unique=False)
    op.create_index(op.f("ix_unlock_links_video_id"), "unlock_links", ["video_id"], unique=False)

    # 11. Broadcasts
    op.create_table(
        "broadcasts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("client_bot_id", sa.BigInteger(), nullable=False),
        sa.Column("video_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by_admin_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("target_type", sa.String(length=100), nullable=False),
        sa.Column("total_targets", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("sent_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("blocked_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["client_bot_id"], ["client_bots.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_admin_id"], ["client_bot_admins.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_broadcasts_bot_created", "broadcasts", ["client_bot_id", "created_at"], unique=False)
    op.create_index(op.f("ix_broadcasts_client_bot_id"), "broadcasts", ["client_bot_id"], unique=False)
    op.create_index(op.f("ix_broadcasts_status"), "broadcasts", ["status"], unique=False)
    op.create_index(op.f("ix_broadcasts_video_id"), "broadcasts", ["video_id"], unique=False)

    # 12. Broadcast Deliveries
    op.create_table(
        "broadcast_deliveries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("broadcast_id", sa.BigInteger(), nullable=False),
        sa.Column("viewer_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["broadcast_id"], ["broadcasts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["viewer_id"], ["viewers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("broadcast_id", "viewer_id", name="uq_broadcast_viewer_delivery"),
    )
    op.create_index("ix_broadcast_deliveries_bcast_status", "broadcast_deliveries", ["broadcast_id", "status"], unique=False)
    op.create_index(op.f("ix_broadcast_deliveries_broadcast_id"), "broadcast_deliveries", ["broadcast_id"], unique=False)
    op.create_index(op.f("ix_broadcast_deliveries_status"), "broadcast_deliveries", ["status"], unique=False)
    op.create_index(op.f("ix_broadcast_deliveries_viewer_id"), "broadcast_deliveries", ["viewer_id"], unique=False)

    # 13. Catch-Up Deliveries
    op.create_table(
        "catchup_deliveries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("client_bot_id", sa.BigInteger(), nullable=False),
        sa.Column("viewer_id", sa.BigInteger(), nullable=False),
        sa.Column("video_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("broadcast_delivery_id", sa.BigInteger(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["client_bot_id"], ["client_bots.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["viewer_id"], ["viewers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("viewer_id", "video_id", name="uq_catchup_viewer_video"),
    )
    op.create_index(op.f("ix_catchup_deliveries_client_bot_id"), "catchup_deliveries", ["client_bot_id"], unique=False)
    op.create_index(op.f("ix_catchup_deliveries_status"), "catchup_deliveries", ["status"], unique=False)
    op.create_index(op.f("ix_catchup_deliveries_video_id"), "catchup_deliveries", ["video_id"], unique=False)
    op.create_index(op.f("ix_catchup_deliveries_viewer_id"), "catchup_deliveries", ["viewer_id"], unique=False)

    # 14. Background Jobs
    op.create_table(
        "background_jobs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_type", sa.String(length=50), nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=True),
        sa.Column("client_bot_id", sa.BigInteger(), nullable=True),
        sa.Column("video_id", sa.BigInteger(), nullable=True),
        sa.Column("broadcast_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("queue_name", sa.String(length=100), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["broadcast_id"], ["broadcasts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["client_bot_id"], ["client_bots.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_status_scheduled", "background_jobs", ["status", "scheduled_at"], unique=False)
    op.create_index(op.f("ix_background_jobs_client_bot_id"), "background_jobs", ["client_bot_id"], unique=False)
    op.create_index(op.f("ix_background_jobs_client_id"), "background_jobs", ["client_id"], unique=False)
    op.create_index(op.f("ix_background_jobs_job_type"), "background_jobs", ["job_type"], unique=False)
    op.create_index(op.f("ix_background_jobs_scheduled_at"), "background_jobs", ["scheduled_at"], unique=False)
    op.create_index(op.f("ix_background_jobs_status"), "background_jobs", ["status"], unique=False)

    # 15. Bot Events
    op.create_table(
        "bot_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("client_bot_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("related_video_id", sa.BigInteger(), nullable=True),
        sa.Column("related_broadcast_id", sa.BigInteger(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["client_bot_id"], ["client_bots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_bot_events_client_bot_id"), "bot_events", ["client_bot_id"], unique=False)
    op.create_index(op.f("ix_bot_events_event_type"), "bot_events", ["event_type"], unique=False)


def downgrade() -> None:
    op.drop_table("bot_events")
    op.drop_table("background_jobs")
    op.drop_table("catchup_deliveries")
    op.drop_table("broadcast_deliveries")
    op.drop_table("broadcasts")
    op.drop_table("unlock_links")
    op.drop_table("video_processing")
    op.drop_table("videos")
    op.drop_table("viewers")
    op.drop_table("sponsor_configs")
    op.drop_table("client_bot_settings")
    op.drop_table("client_bot_admins")
    op.drop_table("client_bots")
    op.drop_table("clients")
    op.drop_table("platform_owners")
