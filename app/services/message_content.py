"""Normalize Telegram messages for durable custom campaigns."""

from typing import Any

MEDIA_METHODS = {
    "photo": "sendPhoto", "video": "sendVideo", "audio": "sendAudio",
    "voice": "sendVoice", "document": "sendDocument",
    "animation": "sendAnimation", "sticker": "sendSticker",
}
MAX_CROSS_BOT_BYTES = 20_000_000
MAX_CROSS_BOT_PHOTO_BYTES = 10_000_000


def extract_content(message: dict[str, Any]) -> dict[str, Any]:
    if message.get("text"):
        return {"kind": "text", "text": message["text"], "entities": message.get("entities") or []}
    for kind in MEDIA_METHODS:
        media = message.get(kind)
        if not media:
            continue
        if kind == "photo":
            media = media[-1]
        file_id = media.get("file_id") if isinstance(media, dict) else None
        if not file_id:
            break
        suffixes = {"photo": ("jpg", "image/jpeg"), "video": ("mp4", "video/mp4"),
                    "audio": ("mp3", "audio/mpeg"), "voice": ("ogg", "audio/ogg"),
                    "animation": ("mp4", "video/mp4"), "sticker": ("webp", "image/webp")}
        suffix, mime = suffixes.get(kind, ("bin", "application/octet-stream"))
        if kind == "sticker" and media.get("is_animated"):
            suffix, mime = "tgs", "application/x-tgsticker"
        elif kind == "sticker" and media.get("is_video"):
            suffix, mime = "webm", "video/webm"
        return {
            "kind": kind, "file_id": file_id,
            "file_size": media.get("file_size") or 0,
            "file_name": media.get("file_name") or f"campaign.{suffix}",
            "mime_type": media.get("mime_type") or mime,
            "caption": message.get("caption") or "",
            "caption_entities": message.get("caption_entities") or [],
        }
    raise ValueError("This message type cannot be broadcast. Send text, photo, video, audio, voice, document, animation, or sticker.")


def validate_cross_bot_content(content: dict[str, Any]) -> None:
    if content["kind"] == "text":
        return
    limit = MAX_CROSS_BOT_PHOTO_BYTES if content["kind"] == "photo" else MAX_CROSS_BOT_BYTES
    if content.get("file_size", 0) > limit:
        raise ValueError(f"This {content['kind']} is too large to send through client bots (limit: {limit // 1_000_000} MB).")
