"""Control Hub message templates with HTML formatting and escaping."""

import html
from typing import Any, Dict, List, Optional
from app.db.models.client_bot import ClientBot


def escape(text: Optional[str]) -> str:
    """Safely escapes HTML characters for Telegram HTML parse mode."""
    if not text:
        return ""
    return html.escape(str(text))


# --- Owner Messages ---

def owner_home_message() -> str:
    return (
        "👑 <b>Control Hub — Management</b>\n\n"
        "Welcome back, Platform Owner.\n"
        "Platform overview and management tools are available below."
    )


def owner_clients_message(total: int = 0, active: int = 0, paused: int = 0, disconnected: int = 0) -> str:
    return (
        "👤 <b>Clients Overview</b>\n\n"
        f"• Total Clients: <b>{total}</b>\n"
        f"• Active: <b>{active}</b>\n"
        f"• Paused: <b>{paused}</b>\n"
        f"• Disconnected: <b>{disconnected}</b>\n\n"
        "<i>Use buttons below to navigate.</i>"
    )


def owner_bots_message(total: int = 0, active: int = 0, paused: int = 0, disconnected: int = 0) -> str:
    return (
        "🤖 <b>Connected Bots Overview</b>\n\n"
        f"• Total Bots: <b>{total}</b>\n"
        f"• Active: <b>{active}</b>\n"
        f"• Paused: <b>{paused}</b>\n"
        f"• Disconnected: <b>{disconnected}</b>\n\n"
        "<i>Bot details and inspection available from this panel.</i>"
    )


def owner_jobs_message(running: int = 0, queued: int = 0, failed: int = 0) -> str:
    return (
        "⚙️ <b>Background Jobs</b>\n\n"
        f"• Running: <b>{running}</b>\n"
        f"• Queued: <b>{queued}</b>\n"
        f"• Failed: <b>{failed}</b>\n\n"
        "<i>All asynchronous tasks are tracked in PostgreSQL.</i>"
    )


def owner_queue_message() -> str:
    return (
        "⏳ <b>Queue Status</b>\n\n"
        "• Video Processing: <b>0</b>\n"
        "• Unlock Link Jobs: <b>0</b>\n"
        "• Broadcast Deliveries: <b>0</b>\n"
        "• Catch-Up Deliveries: <b>0</b>\n"
    )


def owner_broadcasts_message(running: int = 0, waiting: int = 0, completed: int = 0, failed: int = 0) -> str:
    return (
        "📤 <b>Broadcast Activity</b>\n\n"
        f"• Running Now: <b>{running}</b>\n"
        f"• Waiting: <b>{waiting}</b>\n"
        f"• Completed: <b>{completed}</b>\n"
        f"• Failed: <b>{failed}</b>\n"
    )


def owner_systemstats_message(stats: Dict[str, Any]) -> str:
    return (
        "🌐 <b>Control Hub Statistics</b>\n\n"
        f"👤 Clients: <b>{stats.get('total_clients', 0)}</b>\n"
        f"🤖 Connected Bots: <b>{stats.get('total_bots', 0)}</b> (Active: {stats.get('active_bots', 0)})\n"
        f"👥 Total Viewers: <b>{stats.get('total_viewers', 0)}</b>\n"
        f"🎬 Total Videos: <b>{stats.get('total_videos', 0)}</b>\n\n"
        f"⚙️ Processing Now: <b>{stats.get('processing_jobs', 0)}</b>\n"
        f"📤 Broadcasts Running: <b>{stats.get('running_broadcasts', 0)}</b>\n"
        f"❌ Failed Items: <b>{stats.get('failed_items', 0)}</b>"
    )


def owner_help_message() -> str:
    return (
        "❓ <b>Platform Owner Commands</b>\n\n"
        "/clients — View registered clients summary\n"
        "/bots — View connected client bots summary\n"
        "/jobs — View active background jobs\n"
        "/queue — View waiting queue status\n"
        "/broadcasts — View broadcast delivery progress\n"
        "/systemstats — View platform-wide statistics\n"
        "/help — Show this help menu"
    )


# --- Client Messages ---

def client_home_message(username: Optional[str] = None, bot_count: int = 0) -> str:
    name_str = f" @{escape(username)}" if username else ""
    return (
        f"👋 <b>Welcome back to Control Hub{name_str}</b>\n\n"
        f"You have <b>{bot_count}</b> connected bot(s).\n"
        "Manage your video bots and audience from the options below."
    )


def new_client_welcome_message() -> str:
    return (
        "👋 <b>Welcome to Control Hub</b>\n\n"
        "Create and manage your own Telegram video bot.\n"
        "You currently have no connected bots.\n\n"
        "To get started, create a bot using @BotFather and connect it below!"
    )


def client_connectbot_entry_message() -> str:
    return (
        "🤖 <b>Connect a Telegram Bot</b>\n\n"
        "1. Open @BotFather on Telegram.\n"
        "2. Create a new bot with <code>/newbot</code>.\n"
        "3. Copy the HTTP API token BotFather gives you.\n\n"
        "<i>Full interactive token connection will guide you in the next step.</i>"
    )


def client_mybots_message(bots: List[ClientBot]) -> str:
    if not bots:
        return (
            "🤖 <b>My Connected Bots</b>\n\n"
            "You do not have any connected bots yet.\n"
            "Tap <b>Connect Bot</b> below to link your first bot."
        )

    lines = ["🤖 <b>My Connected Bots</b>\n"]
    for idx, bot in enumerate(bots, start=1):
        raw_status = bot.status.value if hasattr(bot.status, "value") else str(bot.status)
        status_icon = "✅" if raw_status == "ACTIVE" else "⏸" if raw_status == "PAUSED" else "❌"
        bot_handle = f"@{escape(bot.username)}" if bot.username else f"Bot #{bot.telegram_bot_id}"
        lines.append(f"{idx}. <b>{bot_handle}</b> — {status_icon} {raw_status}")

    lines.append("\n<i>Tap Connect Bot to add another bot.</i>")
    return "\n".join(lines)



def client_account_message(username: Optional[str], bot_count: int, status: str) -> str:
    return (
        "👤 <b>My Control Hub Account</b>\n\n"
        f"• Telegram: <b>@{escape(username or 'Unknown')}</b>\n"
        f"• Connected Bots: <b>{bot_count}</b>\n"
        f"• Account Status: <b>✅ {escape(status)}</b>\n"
    )


def client_help_message() -> str:
    return (
        "❓ <b>Control Hub Help</b>\n\n"
        "Control Hub lets you connect and manage multiple Telegram video bots.\n\n"
        "<b>Available Commands:</b>\n"
        "/start — Open main menu\n"
        "/connectbot — Connect a new BotFather bot\n"
        "/mybots — View your connected bots\n"
        "/account — View account details\n"
        "/help — Show this help message\n\n"
        "<i>After connecting a bot, open that bot on Telegram to manage videos and sponsors.</i>"
    )


# --- Common & Guard Messages ---

def unauthorized_message() -> str:
    return "⛔ <b>Access Denied</b>\n\nThis command is not available for your account."


def unknown_command_message(is_owner: bool = False) -> str:
    if is_owner:
        return (
            "❓ <b>Unknown Control Hub Command</b>\n\n"
            "Use /help or the management menu below to see available owner tools."
        )
    return (
        "❓ <b>Unknown Command</b>\n\n"
        "I don't recognize that command. Use /help to see available Control Hub commands."
    )


def normal_text_reply_message(is_owner: bool = False) -> str:
    if is_owner:
        return "👑 <b>Control Hub</b>\nPlease use the management commands or menu below."
    return "👋 <b>Control Hub</b>\nPlease use the menu buttons below to manage your bots."


def private_chat_only_message() -> str:
    return (
        "🔒 <b>Private Chat Only</b>\n\n"
        "Control Hub only operates in direct private chat for security.\n"
        "Please message me privately."
    )


def generic_error_message() -> str:
    return "⚠️ <b>Something went wrong</b>\n\nPlease try again shortly."
