"""Telegram Actor Extractor for Client Bot runtime."""

from typing import Any, Dict, Optional


def extract_telegram_actor(update: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extracts actor information, chat details, and message/callback data from a raw update.
    
    Returns a standardized dictionary or None if update has no valid actor.
    """
    if not isinstance(update, dict):
        return None

    user: Optional[Dict[str, Any]] = None
    chat: Optional[Dict[str, Any]] = None
    text: Optional[str] = None
    message_id: Optional[int] = None
    callback_query_id: Optional[str] = None
    callback_data: Optional[str] = None
    update_type: str = "unknown"

    video: Optional[Dict[str, Any]] = None
    document: Optional[Dict[str, Any]] = None
    caption: Optional[str] = None

    if "message" in update:
        msg = update["message"]
        user = msg.get("from")
        chat = msg.get("chat")
        text = msg.get("text")
        caption = msg.get("caption")
        video = msg.get("video")
        document = msg.get("document")
        message_id = msg.get("message_id")
        update_type = "message"
    elif "callback_query" in update:
        cb = update["callback_query"]
        user = cb.get("from")
        msg = cb.get("message")
        chat = msg.get("chat") if isinstance(msg, dict) else None
        callback_query_id = cb.get("id")
        callback_data = cb.get("data")
        message_id = msg.get("message_id") if isinstance(msg, dict) else None
        update_type = "callback_query"
    elif "my_chat_member" in update:
        mcm = update["my_chat_member"]
        user = mcm.get("from")
        chat = mcm.get("chat")
        update_type = "my_chat_member"

    if not user or not user.get("id"):
        return None

    telegram_user_id = user["id"]
    chat_id = chat.get("id", telegram_user_id) if chat else telegram_user_id
    chat_type = chat.get("type", "private") if chat else "private"

    return {
        "update_type": update_type,
        "telegram_user_id": telegram_user_id,
        "chat_id": chat_id,
        "chat_type": chat_type,
        "username": user.get("username"),
        "first_name": user.get("first_name", ""),
        "last_name": user.get("last_name", ""),
        "language_code": user.get("language_code"),
        "is_bot": user.get("is_bot", False),
        "text": text.strip() if text else (caption.strip() if caption else None),
        "caption": caption.strip() if caption else None,
        "video": video,
        "document": document,
        "message_id": message_id,
        "callback_query_id": callback_query_id,
        "callback_data": callback_data,
    }
