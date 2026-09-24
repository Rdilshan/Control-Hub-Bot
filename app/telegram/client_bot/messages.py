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


def create_video_prompt_message() -> str:
    return (
        "🎬 <b>Create Video</b>\n\n"
        "Please send <b>ONE</b> Telegram video.\n\n"
        "After the video is received, background processing will begin immediately.\n"
        "You can immediately send /createvideo again to add another video.\n\n"
        "<i>Send /cancel at any time to exit.</i>"
    )


def sponsor_required_message() -> str:
    return (
        "⚠️ <b>Sponsor Configuration Required</b>\n\n"
        "Please configure your sponsor / direct unlock link first using <b>/sponsor</b> before creating video posts."
    )


def create_video_cancelled_message() -> str:
    return "❌ <b>Video creation cancelled.</b>"


def create_video_document_warning_message() -> str:
    return (
        "⚠️ <b>Please send as a Video</b>\n\n"
        "Please send your file as a Telegram Video (not as a document/file), or send <b>/cancel</b> to exit."
    )


def create_video_non_video_warning_message() -> str:
    return "⚠️ Please send <b>ONE</b> Telegram video, or send <b>/cancel</b> to exit."


def create_video_success_message() -> str:
    return (
        "✅ <b>Video Received</b>\n\n"
        "Your video has been accepted and background processing has started in the background!\n\n"
        "You can use <b>/createvideo</b> now to add another video."
    )


def create_video_expired_message() -> str:
    return (
        "⚠️ <b>Video creation session expired.</b>\n\n"
        "Use <b>/createvideo</b> to start again."
    )


def create_video_error_message() -> str:
    return (
        "❌ <b>Could not save this video.</b>\n\n"
        "A database error occurred. Please try again with <b>/createvideo</b>."
    )


def admin_videos_list_message(videos: list) -> str:
    if not videos:
        return (
            "📁 <b>Video Library</b>\n\n"
            "No videos have been uploaded yet.\n\n"
            "Use <b>/createvideo</b> to upload your first video."
        )

    lines = ["📁 <b>Video Library (Recent Videos)</b>\n"]
    status_emojis = {
        "RECEIVED": "📥 Received",
        "PROCESSING": "⚙️ Processing",
        "READY": "✅ Ready",
        "FAILED": "❌ Failed",
        "DISABLED": "⏸ Disabled",
    }
    for idx, v in enumerate(videos, start=1):
        status_str = status_emojis.get(str(v.status.value if hasattr(v.status, 'value') else v.status), str(v.status))
        caption_snippet = (v.caption[:30] + "...") if v.caption and len(v.caption) > 30 else (v.caption or v.file_name or "Untitled Video")
        dur = f"{v.duration_seconds}s" if v.duration_seconds else "N/A"
        pub_id = getattr(v, "public_id", f"vid_{v.id}")
        lines.append(f"{idx}. <b>{caption_snippet}</b>\n   • ID: <code>{pub_id}</code> | Status: {status_str} | Duration: {dur}")

    lines.append("\n<i>Send /createvideo to add another video.</i>")
    return "\n".join(lines)


def admin_processing_list_message(videos: list) -> str:
    if not videos:
        return (
            "⏳ <b>Processing Queue</b>\n\n"
            "No active video conversions or jobs in the queue.\n\n"
            "Use <b>/createvideo</b> to upload a new video."
        )

    lines = ["⏳ <b>Processing Queue (Active Jobs)</b>\n"]
    for idx, v in enumerate(videos, start=1):
        status_val = str(v.status.value if hasattr(v.status, 'value') else v.status)
        badge = "⏳ Waiting" if status_val == "RECEIVED" else "⚙️ Converting"
        caption_snippet = (v.caption[:30] + "...") if v.caption and len(v.caption) > 30 else (v.caption or v.file_name or f"Video #{v.id}")
        pub_id = getattr(v, "public_id", f"vid_{v.id}")
        lines.append(f"{idx}. <b>{caption_snippet}</b>\n   • ID: <code>{pub_id}</code> | Stage: {badge}")

    lines.append("\n<i>Background workers process videos automatically.</i>")
    return "\n".join(lines)
