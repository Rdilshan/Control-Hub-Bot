"""Async Telegram Bot API client and token validation foundation."""

from typing import Any, Dict, List, Optional
import httpx
from app.config import get_settings
from app.core.security import mask_bot_token
from app.logging_config import get_logger
from app.telegram.errors import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramInvalidTokenError,
    TelegramNetworkError,
    TelegramRateLimitError,
)
from app.telegram.types import TelegramBotInfo

logger = get_logger(__name__)


class TelegramClient:
    """Reusable async client for interacting with Telegram Bot API."""

    def __init__(
        self,
        token: str,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        settings = get_settings()
        self.token = token.strip() if token else ""
        self.base_url = (base_url or settings.TELEGRAM_API_BASE_URL).rstrip("/")
        self.timeout = timeout or settings.TELEGRAM_REQUEST_TIMEOUT
        self._external_client = http_client
        self._client: Optional[httpx.AsyncClient] = http_client

    async def __aenter__(self) -> "TelegramClient":
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._client and not self._external_client:
            await self._client.aclose()
            self._client = None

    def _get_url(self, method: str) -> str:
        return f"{self.base_url}/bot{self.token}/{method}"

    async def request(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Makes an authenticated HTTP request to Telegram Bot API with error normalization."""
        if not self.token:
            raise TelegramInvalidTokenError("Telegram bot token is empty or not provided.")

        url = self._get_url(method)
        masked_tok = mask_bot_token(self.token)

        owns_client = False
        client = self._client
        if client is None:
            client = httpx.AsyncClient(timeout=self.timeout)
            owns_client = True

        try:
            logger.debug(f"Telegram API request {method} for bot {masked_tok}")
            response = await client.post(url, params=params, json=json_data)
            data = response.json()
        except httpx.TimeoutException as exc:
            logger.error(f"Telegram API timeout for {method} ({masked_tok}): {exc}")
            raise TelegramNetworkError(f"Telegram API request timed out: {exc}") from exc
        except httpx.RequestError as exc:
            logger.error(f"Telegram API network error for {method} ({masked_tok}): {exc}")
            raise TelegramNetworkError(f"Telegram API connection error: {exc}") from exc
        except Exception as exc:
            logger.error(f"Unexpected error calling Telegram {method} ({masked_tok}): {exc}")
            raise TelegramAPIError(f"Failed to communicate with Telegram: {exc}") from exc
        finally:
            if owns_client:
                await client.aclose()

        # Handle Telegram API logical errors
        if not data.get("ok"):
            error_code = data.get("error_code", response.status_code)
            description = data.get("description", "Unknown Telegram error")

            logger.warning(
                f"Telegram API returned error [{error_code}] for {method} ({masked_tok}): {description}"
            )

            if error_code in (401, 404):
                raise TelegramInvalidTokenError(
                    message=f"Invalid Telegram bot token: {description}",
                    description=description,
                )
            elif error_code == 429:
                retry_after = data.get("parameters", {}).get("retry_after", 30)
                raise TelegramRateLimitError(
                    message=f"Rate limited by Telegram: {description}",
                    retry_after=retry_after,
                    description=description,
                )
            elif error_code == 403:
                raise TelegramForbiddenError(
                    message=f"Telegram action forbidden: {description}",
                    description=description,
                )
            else:
                raise TelegramAPIError(
                    message=f"Telegram API error: {description}",
                    error_code=error_code,
                    description=description,
                )

        return data.get("result", {})

    async def get_me(self) -> TelegramBotInfo:
        """Calls getMe API and returns parsed TelegramBotInfo."""
        result = await self.request("getMe")
        return TelegramBotInfo(
            id=result["id"],
            is_bot=result.get("is_bot", True),
            first_name=result.get("first_name", ""),
            username=result.get("username"),
            can_join_groups=result.get("can_join_groups"),
            can_read_all_group_messages=result.get("can_read_all_group_messages"),
            supports_inline_queries=result.get("supports_inline_queries"),
        )

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        parse_mode: Optional[str] = "HTML",
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Sends a text message to a specific Telegram chat."""
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup

        return await self.request("sendMessage", json_data=payload)

    async def edit_message_text(
        self,
        chat_id: int | str,
        message_id: int,
        text: str,
        parse_mode: Optional[str] = "HTML",
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Edits an existing text message."""
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup

        return await self.request("editMessageText", json_data=payload)

    async def delete_message(self, chat_id: int | str, message_id: int) -> bool:
        """Attempts to delete a message from a chat for security/cleanup."""
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
        }
        try:
            result = await self.request("deleteMessage", json_data=payload)
            return bool(result)
        except Exception:
            return False

    async def answer_callback_query(
        self,
        callback_query_id: str,
        text: Optional[str] = None,
        show_alert: bool = False,
    ) -> bool:
        """Acknowledges an incoming callback query to dismiss the client loading state."""
        payload: Dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        if show_alert:
            payload["show_alert"] = show_alert

        result = await self.request("answerCallbackQuery", json_data=payload)
        return bool(result)

    async def set_my_commands(
        self,
        commands: List[Dict[str, str]],
        scope: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Configures the bot command menu with Telegram."""
        payload: Dict[str, Any] = {"commands": commands}
        if scope:
            payload["scope"] = scope
        result = await self.request("setMyCommands", json_data=payload)
        return bool(result)

    async def set_webhook(
        self,
        url: str,
        secret_token: Optional[str] = None,
        allowed_updates: Optional[List[str]] = None,
        drop_pending_updates: bool = False,
    ) -> bool:
        """Sets the Telegram webhook URL."""
        payload: Dict[str, Any] = {
            "url": url,
            "drop_pending_updates": drop_pending_updates,
        }
        if secret_token:
            payload["secret_token"] = secret_token
        if allowed_updates:
            payload["allowed_updates"] = allowed_updates

        result = await self.request("setWebhook", json_data=payload)
        return bool(result)

    async def delete_webhook(self, drop_pending_updates: bool = False) -> bool:
        """Deletes the active webhook (needed before switching to polling)."""
        payload = {"drop_pending_updates": drop_pending_updates}
        result = await self.request("deleteWebhook", json_data=payload)
        return bool(result)

    async def get_webhook_info(self) -> Dict[str, Any]:
        """Gets current webhook status from Telegram."""
        return await self.request("getWebhookInfo")

    async def get_updates(
        self,
        offset: Optional[int] = None,
        limit: int = 100,
        timeout: int = 20,
    ) -> List[Dict[str, Any]]:
        """Retrieves incoming updates via long-polling."""
        payload: Dict[str, Any] = {"limit": limit, "timeout": timeout}
        if offset is not None:
            payload["offset"] = offset

        result = await self.request("getUpdates", json_data=payload)
        return result if isinstance(result, list) else []

    async def get_file(self, file_id: str) -> Dict[str, Any]:
        """Gets basic info about a file and prepares it for downloading."""
        return await self.request("getFile", json_data={"file_id": file_id})

    async def download_file(self, file_path: str) -> bytes:
        """Downloads a small file (such as a thumbnail) from Telegram file storage."""
        url = f"{self.base_url}/file/bot{self.token}/{file_path.lstrip('/')}"
        masked_tok = mask_bot_token(self.token)

        owns_client = False
        client = self._client
        if client is None:
            client = httpx.AsyncClient(timeout=self.timeout)
            owns_client = True

        try:
            logger.debug(f"Downloading file from Telegram ({masked_tok}): {file_path}")
            response = await client.get(url)
            response.raise_for_status()
            return response.content
        except Exception as exc:
            logger.error(f"Failed to download file from Telegram ({masked_tok}): {exc}")
            raise TelegramNetworkError(f"File download failed: {exc}") from exc
        finally:
            if owns_client:
                await client.aclose()

    async def send_photo(
        self,
        chat_id: int | str,
        photo: str | bytes,
        caption: Optional[str] = None,
        parse_mode: Optional[str] = "HTML",
        reply_markup: Optional[Dict[str, Any]] = None,
        file_name: str = "preview.jpg",
    ) -> Dict[str, Any]:
        """Sends a photo using either a file_id/URL or raw image bytes."""
        if isinstance(photo, str):
            payload: Dict[str, Any] = {"chat_id": chat_id, "photo": photo}
            if caption:
                payload["caption"] = caption
            if parse_mode:
                payload["parse_mode"] = parse_mode
            if reply_markup:
                payload["reply_markup"] = reply_markup
            return await self.request("sendPhoto", json_data=payload)

        # Multipart form data upload for raw image bytes
        url = self._get_url("sendPhoto")
        masked_tok = mask_bot_token(self.token)
        data: Dict[str, Any] = {"chat_id": str(chat_id)}
        if caption:
            data["caption"] = caption
        if parse_mode:
            data["parse_mode"] = parse_mode
        if reply_markup:
            import json
            data["reply_markup"] = json.dumps(reply_markup)

        files = {"photo": (file_name, photo, "image/jpeg")}

        owns_client = False
        client = self._client
        if client is None:
            client = httpx.AsyncClient(timeout=self.timeout)
            owns_client = True

        try:
            logger.debug(f"Uploading photo to Telegram ({masked_tok})")
            response = await client.post(url, data=data, files=files)
            resp_data = response.json()
        except Exception as exc:
            logger.error(f"Failed to upload photo to Telegram ({masked_tok}): {exc}")
            raise TelegramNetworkError(f"Photo upload failed: {exc}") from exc
        finally:
            if owns_client:
                await client.aclose()

        if not resp_data.get("ok"):
            error_code = resp_data.get("error_code", response.status_code)
            description = resp_data.get("description", "Unknown Telegram error")
            if error_code in (401, 404):
                raise TelegramInvalidTokenError(f"Invalid Telegram bot token: {description}")
            raise TelegramAPIError(f"Telegram photo upload error: {description}", error_code=error_code)

        return resp_data.get("result", {})

    async def send_video(
        self,
        chat_id: int | str,
        video: str,
        caption: Optional[str] = None,
        parse_mode: Optional[str] = "HTML",
        reply_markup: Optional[Dict[str, Any]] = None,
        duration: Optional[int] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        supports_streaming: bool = True,
    ) -> Dict[str, Any]:
        """Sends a video to a chat using a saved Telegram file_id without downloading the full video."""
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "video": video,
            "supports_streaming": supports_streaming,
        }
        if caption:
            payload["caption"] = caption
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if duration:
            payload["duration"] = duration
        if width:
            payload["width"] = width
        if height:
            payload["height"] = height

        return await self.request("sendVideo", json_data=payload)

    async def send_content(
        self, chat_id: int, content: Dict[str, Any], file_id: Optional[str] = None,
        file_bytes: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        """Send a normalized campaign message, optionally uploading media bytes."""
        from app.services.message_content import MEDIA_METHODS

        kind = content["kind"]
        if kind == "text":
            payload = {"chat_id": chat_id, "text": content["text"]}
            if content.get("entities"):
                payload["entities"] = content["entities"]
            return await self.request("sendMessage", json_data=payload)

        method = MEDIA_METHODS[kind]
        payload = {"chat_id": chat_id}
        if kind != "sticker":
            if content.get("caption"):
                payload["caption"] = content["caption"]
            if content.get("caption_entities"):
                payload["caption_entities"] = content["caption_entities"]
        if file_bytes is None:
            payload[kind] = file_id or content["file_id"]
            return await self.request(method, json_data=payload)

        import json
        form = {"chat_id": str(chat_id)}
        if payload.get("caption"):
            form["caption"] = payload["caption"]
        if payload.get("caption_entities"):
            form["caption_entities"] = json.dumps(payload["caption_entities"])
        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        try:
            response = await client.post(
                self._get_url(method), data=form,
                files={kind: (content.get("file_name", f"campaign.{kind}"), file_bytes, content.get("mime_type", "application/octet-stream"))},
            )
            data = response.json()
        except httpx.RequestError as exc:
            raise TelegramNetworkError(f"Campaign upload failed: {exc}") from exc
        finally:
            if self._client is None:
                await client.aclose()
        if not data.get("ok"):
            code = data.get("error_code", response.status_code)
            description = data.get("description", "Telegram upload failed")
            if code == 403:
                raise TelegramForbiddenError(description)
            if code == 429:
                raise TelegramRateLimitError(description, retry_after=data.get("parameters", {}).get("retry_after", 30))
            raise TelegramAPIError(description, error_code=code)
        return data.get("result", {})


async def validate_bot_token(
    token: str,
    base_url: Optional[str] = None,
    http_client: Optional[httpx.AsyncClient] = None,
) -> TelegramBotInfo:
    """Validates a Telegram bot token by making a test getMe call."""
    client = TelegramClient(token=token, base_url=base_url, http_client=http_client)
    return await client.get_me()
