"""Inline and reply keyboards for Client Bot runtime."""

from typing import Any, Dict


def admin_dashboard_keyboard() -> Dict[str, Any]:
    """Inline keyboard for Client Bot admin dashboard."""
    return {
        "inline_keyboard": [
            [
                {"text": "🎬 Create Video", "callback_data": "admin:createvideo"},
                {"text": "📊 Stats", "callback_data": "admin:stats"},
            ],
            [
                {"text": "📁 Videos", "callback_data": "admin:videos"},
                {"text": "⏳ Processing", "callback_data": "admin:processing"},
            ],
            [
                {"text": "👥 Viewers", "callback_data": "admin:users"},
                {"text": "📢 Broadcasts", "callback_data": "admin:broadcasts"},
            ],
            [
                {"text": "🔓 Sponsor Config", "callback_data": "admin:sponsor"},
                {"text": "💬 Custom Messages", "callback_data": "admin:messages"},
            ],
            [{"text": "Send Message", "callback_data": "admin:campaign:new"}],
        ]
    }


def admin_refresh_keyboard(refresh_callback: str) -> Dict[str, Any]:
    """Inline keyboard with a single refresh button for stats and monitoring."""
    return {
        "inline_keyboard": [
            [{"text": "🔄 Refresh", "callback_data": refresh_callback}],
        ]
    }
