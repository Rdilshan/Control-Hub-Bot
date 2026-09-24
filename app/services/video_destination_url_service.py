"""Service for building public destination URLs for videos."""

from app.config import settings


class VideoDestinationUrlService:
    """Generates canonical destination URLs for processed videos."""

    def __init__(self, base_url: str = settings.PUBLIC_APP_BASE_URL):
        self.base_url = base_url.rstrip("/")

    def build_destination_url(self, video_public_id: str) -> str:
        """Build the public destination URL for a given video public_id."""
        return f"{self.base_url}/video/{video_public_id}"
