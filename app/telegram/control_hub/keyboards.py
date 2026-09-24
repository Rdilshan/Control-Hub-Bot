"""Inline keyboard builders for Control Hub Bot."""

from typing import Any, Dict, List


def owner_home_keyboard() -> Dict[str, Any]:
    """Builds the Platform Owner Home inline menu."""
    return {
        "inline_keyboard": [
            [
                {"text": "👤 Clients", "callback_data": "owner:clients"},
                {"text": "🤖 Bots", "callback_data": "owner:bots"},
            ],
            [
                {"text": "⚙️ Jobs", "callback_data": "owner:jobs"},
                {"text": "📤 Broadcasts", "callback_data": "owner:broadcasts"},
            ],
            [
                {"text": "📊 System Stats", "callback_data": "owner:systemstats"},
            ],
        ]
    }


def client_home_keyboard() -> Dict[str, Any]:
    """Builds the Existing Client Home inline menu."""
    return {
        "inline_keyboard": [
            [
                {"text": "🤖 My Bots", "callback_data": "client:mybots"},
                {"text": "➕ Connect Bot", "callback_data": "client:connectbot"},
            ],
            [
                {"text": "👤 Account", "callback_data": "client:account"},
                {"text": "❓ Help", "callback_data": "client:help"},
            ],
        ]
    }


def new_client_keyboard() -> Dict[str, Any]:
    """Builds the New Client Welcome inline menu."""
    return {
        "inline_keyboard": [
            [
                {"text": "🤖 Connect My Bot", "callback_data": "client:connectbot"},
            ],
            [
                {"text": "❓ How It Works", "callback_data": "client:help"},
            ],
        ]
    }


def back_to_owner_home_keyboard() -> Dict[str, Any]:
    """Back button returning to Owner Home."""
    return {
        "inline_keyboard": [
            [
                {"text": "⬅ Back to Home", "callback_data": "nav:owner_home"},
            ]
        ]
    }


def back_to_client_home_keyboard() -> Dict[str, Any]:
    """Back button returning to Client Home."""
    return {
        "inline_keyboard": [
            [
                {"text": "⬅ Back to Home", "callback_data": "nav:client_home"},
            ]
        ]
    }


def mybots_keyboard() -> Dict[str, Any]:
    """Keyboard for My Bots section."""
    return {
        "inline_keyboard": [
            [
                {"text": "➕ Connect New Bot", "callback_data": "client:connectbot"},
            ],
            [
                {"text": "⬅ Back to Home", "callback_data": "nav:client_home"},
            ],
        ]
    }


def connectbot_entry_keyboard() -> Dict[str, Any]:
    """Keyboard for Connect Bot entry screen."""
    return {
        "inline_keyboard": [
            [
                {"text": "🤖 Continue in Bot Connection", "callback_data": "client:connectbot_start"},
            ],
            [
                {"text": "⬅ Back", "callback_data": "nav:client_home"},
            ],
        ]
    }
