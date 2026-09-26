"""Database ORM Models Registry."""

from app.db.base import Base
from app.db.models.platform_owner import PlatformOwner
from app.db.models.client import Client
from app.db.models.client_bot import ClientBot
from app.db.models.client_bot_admin import ClientBotAdmin
from app.db.models.client_bot_settings import ClientBotSettings
from app.db.models.sponsor_config import SponsorConfig
from app.db.models.viewer import Viewer
from app.db.models.video import Video
from app.db.models.video_processing import VideoProcessing
from app.db.models.unlock_link import UnlockLink
from app.db.models.broadcast import Broadcast
from app.db.models.broadcast_delivery import BroadcastDelivery
from app.db.models.message_campaign import MessageCampaign, CampaignClientDelivery
from app.db.models.catchup_delivery import CatchupDelivery
from app.db.models.viewer_catchup import ViewerCatchup
from app.db.models.video_delivery import VideoDelivery
from app.db.models.background_job import BackgroundJob
from app.db.models.bot_event import BotEvent
from app.db.models.processed_update import ProcessedTelegramUpdate

__all__ = [
    "Base",
    "PlatformOwner",
    "Client",
    "ClientBot",
    "ClientBotAdmin",
    "ClientBotSettings",
    "SponsorConfig",
    "Viewer",
    "Video",
    "VideoProcessing",
    "UnlockLink",
    "Broadcast",
    "BroadcastDelivery",
    "MessageCampaign",
    "CampaignClientDelivery",
    "CatchupDelivery",
    "ViewerCatchup",
    "VideoDelivery",
    "BackgroundJob",
    "BotEvent",
    "ProcessedTelegramUpdate",
]
