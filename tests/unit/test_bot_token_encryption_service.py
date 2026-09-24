"""Unit tests for BotTokenEncryptionService."""

import pytest
from app.services.bot_token_encryption_service import BotTokenEncryptionService


def test_encryption_and_decryption_roundtrip():
    service = BotTokenEncryptionService()
    raw_token = "123456789:ABCdefGHIjklMNOpqrsTUVwxyz_1234567"

    encrypted = service.encrypt_token(raw_token)
    assert encrypted is not None
    assert encrypted != raw_token
    assert len(encrypted) > len(raw_token)

    decrypted = service.decrypt_token(encrypted)
    assert decrypted == raw_token


def test_encryption_handles_none_and_empty():
    service = BotTokenEncryptionService()

    assert service.encrypt_token(None) is None
    assert service.encrypt_token("") is None
    assert service.decrypt_token(None) is None
    assert service.decrypt_token("") is None
