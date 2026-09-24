"""Security helpers, token encryption/decryption, and secret masking utilities."""

import base64
import hmac
from typing import Optional
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from app.config import get_settings


def _get_fernet() -> Fernet:
    """Derives a deterministic 32-byte url-safe base64 Fernet key from settings."""
    settings = get_settings()
    raw_key = settings.BOT_TOKEN_ENCRYPTION_KEY.encode("utf-8")
    
    # Use PBKDF2 to safely ensure a valid 32-byte urlsafe base64 key
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"control_hub_salt_v1",
        iterations=100_000,
    )
    derived_key = base64.urlsafe_b64encode(kdf.derive(raw_key))
    return Fernet(derived_key)


def encrypt_token(plain_token: Optional[str]) -> Optional[str]:
    """Encrypts a plaintext bot token. Returns encrypted string."""
    if not plain_token:
        return None
    fernet = _get_fernet()
    encrypted_bytes = fernet.encrypt(plain_token.strip().encode("utf-8"))
    return encrypted_bytes.decode("utf-8")


def decrypt_token(encrypted_token: Optional[str]) -> Optional[str]:
    """Decrypts an encrypted bot token. Returns plaintext string."""
    if not encrypted_token:
        return None
    fernet = _get_fernet()
    decrypted_bytes = fernet.decrypt(encrypted_token.strip().encode("utf-8"))
    return decrypted_bytes.decode("utf-8")


def mask_secret(secret: Optional[str], visible_prefix: int = 4, visible_suffix: int = 4) -> str:
    """Masks a secret string, leaving only optional prefix/suffix characters visible.
    
    Example:
        123456789:ABCDEF12345 -> 1234...2345
    """
    if not secret:
        return "[EMPTY]"
    if len(secret) <= (visible_prefix + visible_suffix):
        return "***REDACTED***"
    return f"{secret[:visible_prefix]}...***REDACTED***...{secret[-visible_suffix:]}"


def mask_bot_token(token: Optional[str]) -> str:
    """Masks Telegram bot tokens specifically, preserving bot ID prefix if available."""
    if not token:
        return "[NO_TOKEN]"
    parts = token.split(":")
    if len(parts) == 2:
        bot_id = parts[0]
        return f"{bot_id}:***REDACTED***"
    return mask_secret(token)


def verify_constant_time(secret_a: Optional[str], secret_b: Optional[str]) -> bool:
    """Constant-time string comparison to prevent timing attacks."""
    if secret_a is None or secret_b is None:
        return False
    return hmac.compare_digest(secret_a.encode("utf-8"), secret_b.encode("utf-8"))
