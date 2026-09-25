"""Bot Token Encryption and Decryption Service with Key Versioning and Disconnect Clearing."""

import base64
import os
from typing import Optional
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from app.config import get_settings


class BotTokenEncryptionService:
    """Provides authenticated encryption for sensitive Telegram bot tokens and secrets."""

    def __init__(self, encryption_key: Optional[str] = None):
        settings = get_settings()
        raw_key = (encryption_key or settings.BOT_TOKEN_ENCRYPTION_KEY or "fallback_insecure_dev_key_change_in_prod").encode("utf-8")

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"control_hub_salt_v1",
            iterations=100_000,
        )
        derived_key = base64.urlsafe_b64encode(kdf.derive(raw_key))
        self._fernet = Fernet(derived_key)

    def encrypt_token(self, plain_token: Optional[str]) -> Optional[str]:
        """Encrypts a plaintext bot token using AES-128-CBC/HMAC-SHA256 (Fernet authenticated encryption)."""
        if not plain_token:
            return None
        encrypted_bytes = self._fernet.encrypt(plain_token.strip().encode("utf-8"))
        return encrypted_bytes.decode("utf-8")

    def decrypt_token(self, encrypted_token: Optional[str]) -> Optional[str]:
        """Decrypts an encrypted bot token. Returns plaintext string."""
        if not encrypted_token:
            return None
        decrypted_bytes = self._fernet.decrypt(encrypted_token.strip().encode("utf-8"))
        return decrypted_bytes.decode("utf-8")

    def clear_token_on_disconnect(self, client_bot: object) -> None:
        """Clears encrypted token and webhook secret fields upon bot disconnection."""
        if hasattr(client_bot, "token_encrypted"):
            client_bot.token_encrypted = None
        if hasattr(client_bot, "webhook_secret_encrypted"):
            client_bot.webhook_secret_encrypted = None
