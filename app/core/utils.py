"""Shared core utility functions."""

from datetime import datetime, timezone
import uuid


def utc_now() -> datetime:
    """Returns the current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    """Generates a UUID4 string."""
    return str(uuid.uuid4())


def generate_public_id(prefix: str = "vid") -> str:
    """Generates a random, URL-safe public identifier."""
    return f"{prefix}_{uuid.uuid4().hex[:10]}"
