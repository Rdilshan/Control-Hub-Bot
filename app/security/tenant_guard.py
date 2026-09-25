"""Tenant isolation verification guards preventing cross-bot and cross-client data leakage."""

from typing import Optional
from app.exceptions import ForbiddenError, NotFoundError


class TenantGuardService:
    """Provides assertion guards enforcing strict multi-tenant data boundaries across clients, bots, and entities."""

    @staticmethod
    def assert_bot_belongs_to_client(client_bot: Optional[object], client_id: int) -> None:
        """Verifies that a ClientBot belongs to the specified Client. Raises ForbiddenError if mismatch."""
        if not client_bot:
            raise NotFoundError("Bot record not found.")
        bot_client_id = getattr(client_bot, "client_id", None)
        if bot_client_id is None or int(bot_client_id) != int(client_id):
            raise ForbiddenError("Bot does not belong to the requesting client.")

    @staticmethod
    def assert_video_belongs_to_bot(video: Optional[object], client_bot_id: int) -> None:
        """Verifies that a Video belongs to the given ClientBot. Raises ForbiddenError / NotFoundError on mismatch."""
        if not video:
            raise NotFoundError("Video not found.")
        vid_bot_id = getattr(video, "client_bot_id", None)
        if vid_bot_id is None or int(vid_bot_id) != int(client_bot_id):
            raise ForbiddenError("Video does not belong to this bot.")

    @staticmethod
    def assert_viewer_belongs_to_bot(viewer: Optional[object], client_bot_id: int) -> None:
        """Verifies that a Viewer is registered under the given ClientBot."""
        if not viewer:
            raise NotFoundError("Viewer not found.")
        viewer_bot_id = getattr(viewer, "client_bot_id", None)
        if viewer_bot_id is None or int(viewer_bot_id) != int(client_bot_id):
            raise ForbiddenError("Viewer does not belong to this bot.")

    @staticmethod
    def assert_broadcast_belongs_to_bot(broadcast: Optional[object], client_bot_id: int) -> None:
        """Verifies that a Broadcast belongs to the given ClientBot."""
        if not broadcast:
            raise NotFoundError("Broadcast not found.")
        broadcast_bot_id = getattr(broadcast, "client_bot_id", None)
        if broadcast_bot_id is None or int(broadcast_bot_id) != int(client_bot_id):
            raise ForbiddenError("Broadcast does not belong to this bot.")

    @staticmethod
    def assert_unlock_link_belongs_to_video(unlock_link: Optional[object], video_id: int) -> None:
        """Verifies that an UnlockLink is associated with the given Video."""
        if not unlock_link:
            raise NotFoundError("Unlock link not found.")
        link_video_id = getattr(unlock_link, "video_id", None)
        if link_video_id is None or int(link_video_id) != int(video_id):
            raise ForbiddenError("Unlock link does not belong to this video.")
