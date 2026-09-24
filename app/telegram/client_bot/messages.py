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


def admin_stats_message(summary: dict) -> str:
    users = summary.get("users", {})
    videos = summary.get("videos", {})
    bcasts = summary.get("broadcasts", {})

    u_total = f"{users.get('total', 0):,}"
    u_active = f"{users.get('active', 0):,}"
    u_blocked = f"{users.get('blocked', 0):,}"
    u_today = f"{users.get('new_today', 0):,}"

    v_total = f"{videos.get('total', 0):,}"
    v_ready = f"{videos.get('ready', 0):,}"
    v_proc = f"{videos.get('processing', 0):,}"
    v_failed = f"{videos.get('failed', 0):,}"

    b_live_run = f"{bcasts.get('live_running', 0):,}"
    b_live_wait = f"{bcasts.get('live_waiting', 0):,}"
    b_catch_run = f"{bcasts.get('catchup_running', 0):,}"
    b_catch_wait = f"{bcasts.get('catchup_waiting', 0):,}"

    return (
        "📊 <b>Bot Statistics</b>\n\n"
        "👥 <b>Users</b>\n"
        f"• Total: <b>{u_total}</b>\n"
        f"• 🟢 Active: <b>{u_active}</b>\n"
        f"• 🚫 Blocked: <b>{u_blocked}</b>\n"
        f"• 🆕 New Today: <b>{u_today}</b>\n\n"
        "🎬 <b>Videos</b>\n"
        f"• Total: <b>{v_total}</b>\n"
        f"• ✅ Ready: <b>{v_ready}</b>\n"
        f"• ⚙️ Processing: <b>{v_proc}</b>\n"
        f"• ❌ Failed: <b>{v_failed}</b>\n\n"
        "📤 <b>Broadcasts (LIVE)</b>\n"
        f"• ▶️ Running: <b>{b_live_run}</b>\n"
        f"• ⏳ Waiting: <b>{b_live_wait}</b>\n\n"
        "📥 <b>Catch-Up</b>\n"
        f"• ▶️ Running: <b>{b_catch_run}</b>\n"
        f"• ⏳ Waiting: <b>{b_catch_wait}</b>"
    )


def admin_users_message(users: dict) -> str:
    total = f"{users.get('total', 0):,}"
    active = f"{users.get('active', 0):,}"
    blocked = f"{users.get('blocked', 0):,}"
    today = f"{users.get('new_today', 0):,}"
    seven_days = f"{users.get('new_7_days', 0):,}"

    return (
        "👥 <b>Audience & Subscribers</b>\n\n"
        f"• Total Users: <b>{total}</b>\n"
        f"• 🟢 Active: <b>{active}</b>\n"
        f"• 🚫 Blocked: <b>{blocked}</b>\n"
        f"• 🆕 New Today: <b>{today}</b>\n"
        f"• 📅 Last 7 Days: <b>{seven_days}</b>\n\n"
        "<i>Audience members are tracked automatically as they interact with your bot.</i>"
    )


def admin_processing_summary_message(proc: dict) -> str:
    received = f"{proc.get('received', 0):,}"
    preview = f"{proc.get('preview', 0):,}"
    unlockify = f"{proc.get('unlockify', 0):,}"
    ready_today = f"{proc.get('ready_today', 0):,}"
    failed = f"{proc.get('failed', 0):,}"

    return (
        "⚙️ <b>Video Processing Pipeline</b>\n\n"
        f"• 📥 Received: <b>{received}</b>\n"
        f"• 🖼 Preview Generation: <b>{preview}</b>\n"
        f"• 🔗 Unlockify Link Creation: <b>{unlockify}</b>\n"
        f"• ✅ Ready Today: <b>{ready_today}</b>\n"
        f"• ❌ Failed: <b>{failed}</b>\n\n"
        "<i>Background workers process videos continuously.</i>"
    )


def admin_broadcasts_summary_message(bcasts: dict) -> str:
    live_run = f"{bcasts.get('live_running', 0):,}"
    live_wait = f"{bcasts.get('live_waiting', 0):,}"
    live_comp = f"{bcasts.get('live_completed_today', 0):,}"
    live_fail = f"{bcasts.get('live_failed', 0):,}"

    cu_run = f"{bcasts.get('catchup_running', 0):,}"
    cu_wait = f"{bcasts.get('catchup_waiting', 0):,}"
    cu_comp = f"{bcasts.get('catchup_completed_today', 0):,}"
    cu_fail = f"{bcasts.get('catchup_failed', 0):,}"

    return (
        "📤 <b>Broadcasts & Delivery Status</b>\n\n"
        "<b>LIVE Broadcasts</b>\n"
        f"• ▶️ Running: <b>{live_run}</b>\n"
        f"• ⏳ Waiting: <b>{live_wait}</b>\n"
        f"• ✅ Completed Today: <b>{live_comp}</b>\n"
        f"• ❌ Failed: <b>{live_fail}</b>\n\n"
        "<b>Catch-Up Delivery</b>\n"
        f"• ▶️ Running Viewers: <b>{cu_run}</b>\n"
        f"• ⏳ Waiting Viewers: <b>{cu_wait}</b>\n"
        f"• ✅ Completed Today: <b>{cu_comp}</b>\n"
        f"• ❌ Failed: <b>{cu_fail}</b>"
    )
