"""Service for managing Client Bot sponsor configurations and validations."""

from typing import Optional
from urllib.parse import urlparse
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.sponsor_config import SponsorConfig
from app.exceptions import NotFoundError, ValidationError
from app.logging_config import logger
from app.repositories.sponsor import SponsorRepository


class ClientBotSponsorService:
    """Provides business logic for viewing, configuring, and toggling per-bot sponsors."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.sponsor_repo = SponsorRepository(session)

    @staticmethod
    def validate_sponsor_url(url: str) -> str:
        """Validates that a sponsor direct-link URL is safe and valid."""
        if not url or not url.strip():
            raise ValidationError("Sponsor URL cannot be empty")

        clean_url = url.strip()
        parsed = urlparse(clean_url)

        if parsed.scheme.lower() not in ("http", "https"):
            raise ValidationError("Sponsor URL must use http:// or https:// protocol")

        if not parsed.netloc:
            raise ValidationError("Sponsor URL must contain a valid domain name")

        # Reject dangerous schemes
        if any(clean_url.lower().startswith(bad) for bad in ("javascript:", "data:", "file:", "vbscript:")):
            raise ValidationError("Invalid sponsor URL format")

        if len(clean_url) > 2000:
            raise ValidationError("Sponsor URL is too long (max 2000 characters)")

        return clean_url

    async def get_sponsor(self, client_bot_id: int) -> Optional[SponsorConfig]:
        """Gets the sponsor configuration for a given client bot."""
        return await self.sponsor_repo.get_by_bot_id(client_bot_id)

    async def set_sponsor_url(
        self,
        client_bot_id: int,
        sponsor_url: str,
        enable: bool = True,
    ) -> SponsorConfig:
        """Validates and updates the sponsor URL for a client bot."""
        valid_url = self.validate_sponsor_url(sponsor_url)

        sponsor = await self.sponsor_repo.get_by_bot_id(client_bot_id)
        if not sponsor:
            sponsor = SponsorConfig(
                client_bot_id=client_bot_id,
                sponsor_url=valid_url,
                is_enabled=enable,
            )
            self.session.add(sponsor)
            await self.session.flush()
        else:
            await self.sponsor_repo.update_sponsor(
                client_bot_id=client_bot_id,
                sponsor_url=valid_url,
                is_enabled=enable,
            )
        logger.info("Updated sponsor URL for client_bot_id=%d (enabled=%s)", client_bot_id, enable)
        return sponsor

    async def enable_sponsor(self, client_bot_id: int) -> SponsorConfig:
        """Enables the sponsor configuration for a client bot."""
        sponsor = await self.sponsor_repo.get_by_bot_id(client_bot_id)
        if not sponsor or not sponsor.sponsor_url:
            raise ValidationError("Cannot enable sponsor without a configured sponsor URL")

        await self.sponsor_repo.set_enabled(client_bot_id, True)
        logger.info("Enabled sponsor for client_bot_id=%d", client_bot_id)
        return sponsor

    async def disable_sponsor(self, client_bot_id: int) -> SponsorConfig:
        """Disables the sponsor configuration for a client bot."""
        sponsor = await self.sponsor_repo.get_by_bot_id(client_bot_id)
        if not sponsor:
            raise NotFoundError("Sponsor configuration not found")

        await self.sponsor_repo.set_enabled(client_bot_id, False)
        logger.info("Disabled sponsor for client_bot_id=%d", client_bot_id)
        return sponsor
