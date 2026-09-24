"""Bot Token Encryption Service."""

from typing import Optional
from app.core.security import decrypt_token, encrypt_token


class BotTokenEncryptionService:
    """Service providing safe encapsulation for bot token encryption & decryption."""

    def encrypt_token(self, token: Optional[str]) -> Optional[str]:
        """Encrypts a plaintext bot token."""
        return encrypt_token(token)

    def decrypt_token(self, encrypted_token: Optional[str]) -> Optional[str]:
        """Decrypts an encrypted bot token."""
        return decrypt_token(encrypted_token)
