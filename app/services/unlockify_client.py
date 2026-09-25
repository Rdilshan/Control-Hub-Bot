"""Unlockify API client for creating video unlock links."""

from typing import List, Optional
import httpx
from app.config import settings
from app.exceptions import (
    UnlockifyError,
    UnlockifyInvalidResponseError,
    UnlockifyNetworkError,
    UnlockifyRequestRejectedError,
    UnlockifyTimeoutError,
    ValidationError,
)
from app.logging_config import logger
from app.schemas.unlockify import UnlockifyCreateLinkRequest, UnlockifyCreateLinkResponse, UnlockifyLinkData


class UnlockifyClient:
    """HTTP Client for Unlockify link creation."""

    def __init__(
        self,
        base_url: str = settings.UNLOCKIFY_API_BASE_URL,
        connect_timeout: float = 10.0,
        read_timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = httpx.Timeout(read_timeout, connect=connect_timeout)

    async def create_link(
        self,
        title: str,
        advertisement_urls: List[str],
        destination_url: str,
    ) -> UnlockifyLinkData:
        """Create a new unlock link on Unlockify.

        Args:
            title: Title of the video.
            advertisement_urls: Sponsor/direct URLs for monetization.
            destination_url: Destination URL where user is redirected after unlocking.

        Returns:
            UnlockifyLinkData with id, title, ads_count, unlock_url.

        Raises:
            ValidationError: If inputs are invalid.
            UnlockifyTimeoutError: If request timed out.
            UnlockifyNetworkError: If connection failed.
            UnlockifyRequestRejectedError: If provider returns 4xx error.
            UnlockifyInvalidResponseError: If response format is invalid or missing required fields.
            UnlockifyError: For other HTTP/service errors.
        """
        if not title or not title.strip():
            raise ValidationError("Title cannot be empty for Unlockify link creation")
        if not advertisement_urls:
            raise ValidationError("At least one advertisement URL is required for Unlockify link creation")
        if not destination_url or not destination_url.strip():
            raise ValidationError("Destination URL cannot be empty for Unlockify link creation")

        req_payload = UnlockifyCreateLinkRequest(
            title=title.strip(),
            advertisement_urls=[url.strip() for url in advertisement_urls if url.strip()],
            destination_url=destination_url.strip(),
        )

        endpoint = f"{self.base_url}/links"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }

        logger.info(
            "Calling Unlockify API to create link",
            extra={
                "endpoint": endpoint,
                "title": req_payload.title,
                "ads_count": len(req_payload.advertisement_urls),
            },
        )

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    endpoint,
                    json=req_payload.model_dump(),
                    headers=headers,
                )
            except httpx.TimeoutException as exc:
                logger.error("Unlockify request timed out: %s", exc)
                raise UnlockifyTimeoutError(f"Unlockify request timed out: {exc}") from exc
            except (httpx.NetworkError, httpx.ConnectError) as exc:
                logger.error("Unlockify network error: %s", exc)
                raise UnlockifyNetworkError(f"Unlockify network error: {exc}") from exc
            except Exception as exc:
                logger.error("Unexpected error connecting to Unlockify: %s", exc)
                raise UnlockifyError(f"Failed to communicate with Unlockify: {exc}") from exc

        # Handle HTTP Status
        if response.status_code >= 400:
            status = response.status_code
            text = response.text
            logger.warning("Unlockify API returned HTTP %d: %s", status, text)
            if 400 <= status < 500 and status != 429:
                raise UnlockifyRequestRejectedError(
                    f"Unlockify rejected link creation (HTTP {status}): {text}",
                    details={"status_code": status, "response_body": text},
                )
            raise UnlockifyError(
                f"Unlockify returned HTTP {status}: {text}",
                code="UNLOCKIFY_HTTP_ERROR",
                status_code=status,
                details={"status_code": status, "response_body": text},
            )

        # Parse JSON
        try:
            raw_json = response.json()
        except Exception as exc:
            logger.error("Unlockify response is not valid JSON: %s", exc)
            raise UnlockifyInvalidResponseError(
                f"Failed to parse Unlockify JSON response: {exc}",
                details={"raw_response": response.text},
            ) from exc

        try:
            parsed = UnlockifyCreateLinkResponse.model_validate(raw_json)
        except Exception as exc:
            logger.error("Unlockify response schema validation failed: %s (response: %s)", exc, raw_json)
            raise UnlockifyInvalidResponseError(
                f"Invalid Unlockify response structure: {exc}",
                details={"raw_json": raw_json},
            ) from exc

        if not parsed.success or not parsed.data or not parsed.data.unlock_url:
            logger.error("Unlockify response indicated failure or missing unlock_url: %s", raw_json)
            raise UnlockifyInvalidResponseError(
                "Unlockify response indicated failure or missing unlock_url",
                details={"raw_json": raw_json},
            )

        logger.info(
            "Successfully created Unlockify link",
            extra={
                "link_id": parsed.data.id,
                "unlock_url": parsed.data.unlock_url,
            },
        )
        return parsed.data
