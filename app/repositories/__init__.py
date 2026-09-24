"""Repositories Package Registry."""

from app.repositories.base import BaseRepository
from app.repositories.platform_owner import PlatformOwnerRepository
from app.repositories.client import ClientRepository
from app.repositories.client_bot import ClientBotRepository
from app.repositories.client_bot_admin import ClientBotAdminRepository
from app.repositories.client_bot_settings import ClientBotSettingsRepository
from app.repositories.sponsor import SponsorRepository
from app.repositories.viewer import ViewerRepository
from app.repositories.video import VideoRepository
from app.repositories.video_processing import VideoProcessingRepository
from app.repositories.unlock_link import UnlockLinkRepository
from app.repositories.broadcast import BroadcastRepository
from app.repositories.delivery import BroadcastDeliveryRepository
from app.repositories.catchup import CatchupDeliveryRepository
from app.repositories.job import BackgroundJobRepository
from app.repositories.event import BotEventRepository

__all__ = [
    "BaseRepository",
    "PlatformOwnerRepository",
    "ClientRepository",
    "ClientBotRepository",
    "ClientBotAdminRepository",
    "ClientBotSettingsRepository",
    "SponsorRepository",
    "ViewerRepository",
    "VideoRepository",
    "VideoProcessingRepository",
    "UnlockLinkRepository",
    "BroadcastRepository",
    "BroadcastDeliveryRepository",
    "CatchupDeliveryRepository",
    "BackgroundJobRepository",
    "BotEventRepository",
]
