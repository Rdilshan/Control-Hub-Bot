"""Telegram Client Factory for dynamic multi-tenant Client Bots."""

from typing import Dict, Optional
from app.logging_config import get_logger
from app.services.bot_token_encryption_service import BotTokenEncryptionService
from app.telegram.client import TelegramClient

logger = get_logger(__name__)


class ClientBotApiFactory:
    """Creates and manages authenticated TelegramClient instances for connected client bots."""

    def __init__(self, encryption_service: Optional[BotTokenEncryptionService] = None):
        self.encryption_service = encryption_service or BotTokenEncryptionService()
        self._clients: Dict[int, TelegramClient] = {}

    def get_client(self, client_bot_id: int, encrypted_token: str) -> Optional[TelegramClient]:
        """Returns a TelegramClient for the given bot.
        
        Cached in-memory per worker process; decrypted on-demand.
        """
        if client_bot_id in self._clients:
            return self._clients[client_bot_id]

        raw_token = self.encryption_service.decrypt_token(encrypted_token)
        if not raw_token:
            logger.error(f"Cannot create TelegramClient: Failed to decrypt token for bot #{client_bot_id}")
            return None

        client = TelegramClient(token=raw_token)
        self._clients[client_bot_id] = client
        return client

    def invalidate(self, client_bot_id: int) -> None:
        """Removes a bot's client from the cache on disconnect or reconnect."""
        if client_bot_id in self._clients:
            del self._clients[client_bot_id]
            logger.debug(f"Invalidated TelegramClient cache for bot #{client_bot_id}")

    def clear(self) -> None:
        """Clears all cached clients."""
        self._clients.clear()


# Global singleton instance
bot_api_factory = ClientBotApiFactory()
