"""Client Bot message templates and UI formatters."""

from typing import Optional


def admin_welcome_message(bot_username: Optional[str], display_name: Optional[str], client_first_name: Optional[str] = None) -> str:
    handle = f"@{bot_username}" if bot_username else (display_name or "Your Bot")
    name = f" <b>{client_first_name}</b>" if client_first_name else ""
    return (
        f"👑 <b>Admin Dashboard — {handle}</b>\n\n"
        f"Welcome back{name}! You are the authorized administrator of this bot.\n\n"
        f"<b>Quick Actions:</b>\n"
        f"• 🎬 <b>/createvideo</b> — Upload and publish a new video\n"
        f"• 📊 <b>/stats</b> — View viewer count & video metrics\n"
        f"• 📁 <b>/videos</b> — Manage published video posts\n"
        f"• ⏳ <b>/processing</b> — Inspect active video processing queue\n"
        f"• 👥 <b>/users</b> — View subscriber growth and activity\n"
        f"• 📢 <b>/broadcasts</b> — Launch message broadcasts\n"
        f"• 🔓 <b>/sponsor</b> — Configure Unlockify sponsor links\n"
        f"• 💬 <b>/startmessage</b> — Edit custom /start text\n"
        f"• 🔁 <b>/defaultmessage</b> — Edit fallback reply message\n\n"
        f"<i>Tap an option below or use the commands menu.</i>"
    )


def viewer_welcome_message(custom_start_message: Optional[str] = None, bot_username: Optional[str] = None) -> str:
    if custom_start_message and custom_start_message.strip():
        return custom_start_message.strip()
    handle = f"@{bot_username}" if bot_username else "our channel"
    return (
        f"👋 <b>Welcome to {handle}!</b>\n\n"
        f"You will receive exclusive content, video posts, and updates directly here.\n\n"
        f"Use <b>/help</b> for more details."
    )


def viewer_help_message(bot_username: Optional[str] = None) -> str:
    handle = f"@{bot_username}" if bot_username else "This bot"
    return (
        f"ℹ️ <b>About {handle}</b>\n\n"
        f"• Whenever new content is posted, you'll receive a notification here.\n"
        f"• Videos with sponsor unlocks can be watched using the direct button.\n"
        f"• Use <b>/start</b> at any time to refresh your session."
    )


def admin_only_command_message() -> str:
    return (
        "⛔ <b>Access Denied</b>\n\n"
        "This command is only available to the bot owner and authorized administrators."
    )


def private_chat_only_message() -> str:
    return "⚠️ This bot only operates in private 1-on-1 chats. Please message the bot directly."


def bot_paused_viewer_message() -> str:
    return (
        "⏸ <b>Bot Temporarily Paused</b>\n\n"
        "This bot is currently paused for maintenance. Please check back later!"
    )


def bot_paused_admin_message(bot_username: Optional[str] = None) -> str:
    handle = f"@{bot_username}" if bot_username else "This bot"
    return (
        f"⏸ <b>{handle} is Currently Paused</b>\n\n"
        f"Normal viewer traffic and video delivery are suspended.\n"
        f"Open the <b>Control Hub Bot</b> to resume this bot when ready."
    )


def bot_inactive_message() -> str:
    return (
        "⚠️ <b>Service Unavailable</b>\n\n"
        "This bot is currently inactive. Please contact the administrator."
    )


def default_reply_message(custom_default: Optional[str] = None) -> str:
    if custom_default and custom_default.strip():
        return custom_default.strip()
    return "👋 Hello! Please use the video posts and unlock buttons to access content."
