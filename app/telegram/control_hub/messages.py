"""Control Hub message templates with HTML formatting and escaping."""

import html
from typing import Any, Dict, List, Optional
from app.db.models.client_bot import ClientBot


def escape(text: Optional[str]) -> str:
    """Safely escapes HTML characters for Telegram HTML parse mode."""
    if not text:
        return ""
    return html.escape(str(text))


def fmt_num(val: Any) -> str:
    """Formats numeric values with comma separators."""
    if isinstance(val, (int, float)):
        return f"{val:,}"
    try:
        return f"{int(val):,}"
    except (ValueError, TypeError):
        return str(val) if val is not None else "0"


# ==============================================================================
# 👑 Platform Owner Messages
# ==============================================================================

def owner_home_message() -> str:
    return (
        "👑 <b>Control Hub — Management</b>\n\n"
        "Welcome back, Platform Owner.\n"
        "Platform overview and management tools are available below."
    )


# --- 1. Clients ---

def owner_clients_summary_message(stats: Dict[str, Any]) -> str:
    total = stats.get("total", 0)
    if total == 0:
        return (
            "👤 <b>Clients Overview</b>\n\n"
            "No clients have joined yet."
        )

    return (
        "👤 <b>Clients Overview</b>\n\n"
        f"• Total: <b>{fmt_num(total)}</b>\n"
        f"• ✅ Active: <b>{fmt_num(stats.get('active', 0))}</b>\n"
        f"• ⏸ Suspended: <b>{fmt_num(stats.get('suspended', 0))}</b>\n"
        f"• ❌ Disabled: <b>{fmt_num(stats.get('disabled', 0))}</b>\n\n"
        f"• 🆕 New Today: <b>{fmt_num(stats.get('new_today', 0))}</b>"
    )


def owner_clients_list_message(items: List[Dict[str, Any]], page: int, total_pages: int) -> str:
    if not items:
        return "👤 <b>Clients List</b>\n\nNo clients found."

    lines = [f"👤 <b>Clients — Page {page}/{total_pages}</b>\n"]
    for idx, item in enumerate(items, start=1 + (page - 1) * 10):
        c = item["client"]
        bot_count = item["bot_count"]
        status_icon = "✅" if c.status.value == "ACTIVE" else "⏸" if c.status.value == "SUSPENDED" else "❌"
        username_str = f"@{escape(c.username)}" if c.username else f"Client #{c.id}"
        lines.append(f"{idx}. <b>{username_str}</b>\n   {status_icon} {c.status.value} | 🤖 {bot_count} bot(s)\n")

    return "\n".join(lines)


def owner_client_detail_message(detail: Dict[str, Any]) -> str:
    c = detail["client"]
    status_icon = "✅" if c.status.value == "ACTIVE" else "⏸" if c.status.value == "SUSPENDED" else "❌"
    username_str = f"@{escape(c.username)}" if c.username else "None"
    first_name_str = escape(c.first_name or "None")
    joined_str = c.created_at.strftime("%Y-%m-%d %H:%M UTC") if c.created_at else "Unknown"
    last_seen_str = c.last_seen_at.strftime("%Y-%m-%d %H:%M UTC") if c.last_seen_at else "Never"

    return (
        "👤 <b>Client Details</b>\n\n"
        f"• Username: <b>{username_str}</b>\n"
        f"• Name: <b>{first_name_str}</b>\n"
        f"• Telegram ID: <code>{c.telegram_user_id}</code>\n"
        f"• Status: {status_icon} <b>{c.status.value}</b>\n\n"
        f"• 🤖 Connected Bots: <b>{fmt_num(detail.get('total_bots', 0))}</b>\n"
        f"• 👥 Total Viewers: <b>{fmt_num(detail.get('total_viewers', 0))}</b>\n"
        f"• 🎬 Total Videos: <b>{fmt_num(detail.get('total_videos', 0))}</b>\n\n"
        f"• Joined: <code>{joined_str}</code>\n"
        f"• Last Seen: <code>{last_seen_str}</code>"
    )


def owner_client_search_prompt_message() -> str:
    return (
        "🔎 <b>Search Client</b>\n\n"
        "Send the Telegram username (e.g. <code>@username</code>), numeric Telegram User ID, or internal Client ID.\n\n"
        "<i>Send /cancel to return.</i>"
    )


def owner_client_search_result_message(items: List[Dict[str, Any]], query: str) -> str:
    if not items:
        return f"🔎 <b>Search Results for '<code>{escape(query)}</code>'</b>\n\nNo matching clients found."

    lines = [f"🔎 <b>Search Results for '<code>{escape(query)}</code>'</b>\n"]
    for idx, item in enumerate(items, start=1):
        c = item["client"]
        status_icon = "✅" if c.status.value == "ACTIVE" else "⏸" if c.status.value == "SUSPENDED" else "❌"
        username_str = f"@{escape(c.username)}" if c.username else f"Client #{c.id}"
        lines.append(f"{idx}. <b>{username_str}</b> (ID: {c.telegram_user_id})\n   Status: {status_icon} {c.status.value} | 🤖 {item['bot_count']} bot(s)\n")

    return "\n".join(lines)


def owner_client_suspend_confirm_message(username: Optional[str]) -> str:
    name_str = f"@{escape(username)}" if username else "this client"
    return (
        f"⚠️ <b>Suspend {name_str}?</b>\n\n"
        "This will temporarily prevent the client from using Control Hub management features.\n\n"
        "Their saved bots, videos, viewers and history will remain intact."
    )


def owner_client_suspended_message(username: Optional[str]) -> str:
    name_str = f"@{escape(username)}" if username else "Client"
    return f"⏸ <b>{name_str} has been suspended.</b>"


def owner_client_reactivate_confirm_message(username: Optional[str]) -> str:
    name_str = f"@{escape(username)}" if username else "this client"
    return f"▶️ <b>Reactivate {name_str}?</b>\n\nThe client will regain access to Control Hub."


def owner_client_reactivated_message(username: Optional[str]) -> str:
    name_str = f"@{escape(username)}" if username else "Client"
    return f"✅ <b>{name_str} has been reactivated.</b>"


# --- 2. Bots ---

def owner_bots_summary_message(stats: Dict[str, Any]) -> str:
    total = stats.get("total", 0)
    if total == 0:
        return "🤖 <b>Connected Bots Overview</b>\n\nNo bots have been connected yet."

    return (
        "🤖 <b>Connected Bots Overview</b>\n\n"
        f"• Total: <b>{fmt_num(total)}</b>\n\n"
        f"• ✅ Active: <b>{fmt_num(stats.get('active', 0))}</b>\n"
        f"• ⏸ Paused: <b>{fmt_num(stats.get('paused', 0))}</b>\n"
        f"• ❌ Disconnected: <b>{fmt_num(stats.get('disconnected', 0))}</b>\n"
        f"• ⚠️ Invalid Token: <b>{fmt_num(stats.get('invalid_token', 0))}</b>"
    )


def owner_bots_list_message(items: List[Dict[str, Any]], page: int, total_pages: int) -> str:
    if not items:
        return "🤖 <b>Bots List</b>\n\nNo bots found."

    lines = [f"🤖 <b>Bots — Page {page}/{total_pages}</b>\n"]
    for idx, item in enumerate(items, start=1 + (page - 1) * 10):
        b = item["bot"]
        owner = item.get("owner")
        owner_name = f"@{escape(owner.username)}" if owner and owner.username else f"Client #{b.client_id}"
        status_icon = "✅" if b.status.value == "ACTIVE" else "⏸" if b.status.value == "PAUSED" else "❌"
        bot_handle = f"@{escape(b.username)}" if b.username else f"Bot #{b.telegram_bot_id}"
        lines.append(f"{idx}. <b>{bot_handle}</b>\n   Status: {status_icon} {b.status.value} | Owner: {owner_name}\n")

    return "\n".join(lines)


def owner_bot_detail_message(detail: Dict[str, Any]) -> str:
    b = detail["bot"]
    owner = detail.get("owner")
    owner_str = f"@{escape(owner.username)}" if owner and owner.username else f"Client #{b.client_id}"
    status_icon = "✅" if b.status.value == "ACTIVE" else "⏸" if b.status.value == "PAUSED" else "❌"
    bot_handle = f"@{escape(b.username)}" if b.username else f"Bot #{b.telegram_bot_id}"
    connected_str = b.connected_at.strftime("%Y-%m-%d %H:%M UTC") if b.connected_at else "Unknown"
    verified_str = b.last_verified_at.strftime("%Y-%m-%d %H:%M UTC") if b.last_verified_at else "Never"

    return (
        "🤖 <b>Bot Details</b>\n\n"
        f"• Bot: <b>{bot_handle}</b>\n"
        f"• Telegram Bot ID: <code>{b.telegram_bot_id}</code>\n"
        f"• Status: {status_icon} <b>{b.status.value}</b>\n"
        f"• Owner: <b>{owner_str}</b>\n\n"
        f"• 👥 Users/Viewers: <b>{fmt_num(detail.get('users_count', 0))}</b>\n"
        f"• 🎬 Videos Created: <b>{fmt_num(detail.get('videos_count', 0))}</b>\n"
        f"• 📤 Running Broadcasts: <b>{fmt_num(detail.get('running_broadcasts', 0))}</b>\n\n"
        f"• Connected: <code>{connected_str}</code>\n"
        f"• Last Verified: <code>{verified_str}</code>"
    )


def owner_bot_search_prompt_message() -> str:
    return (
        "🔎 <b>Search Bot</b>\n\n"
        "Send the Bot username (e.g. <code>@MyBot</code>), Telegram Bot ID, or internal Bot ID.\n\n"
        "<i>Send /cancel to return.</i>"
    )


def owner_bot_search_result_message(items: List[Dict[str, Any]], query: str) -> str:
    if not items:
        return f"🔎 <b>Search Results for '<code>{escape(query)}</code>'</b>\n\nNo matching bots found."

    lines = [f"🔎 <b>Search Results for '<code>{escape(query)}</code>'</b>\n"]
    for idx, item in enumerate(items, start=1):
        b = item["bot"]
        owner = item.get("owner")
        owner_name = f"@{escape(owner.username)}" if owner and owner.username else f"Client #{b.client_id}"
        status_icon = "✅" if b.status.value == "ACTIVE" else "⏸" if b.status.value == "PAUSED" else "❌"
        bot_handle = f"@{escape(b.username)}" if b.username else f"Bot #{b.telegram_bot_id}"
        lines.append(f"{idx}. <b>{bot_handle}</b>\n   Status: {status_icon} {b.status.value} | Owner: {owner_name}\n")

    return "\n".join(lines)


# --- 3. Background Jobs ---

def owner_jobs_summary_message(stats: Dict[str, Any]) -> str:
    return (
        "⚙️ <b>Background Jobs</b>\n\n"
        f"• ⏳ Queued: <b>{fmt_num(stats.get('queued', 0))}</b>\n"
        f"• ▶️ Running: <b>{fmt_num(stats.get('running', 0))}</b>\n"
        f"• 🔄 Retrying: <b>{fmt_num(stats.get('retrying', 0))}</b>\n\n"
        f"• ✅ Completed Today: <b>{fmt_num(stats.get('completed_today', 0))}</b>\n"
        f"• ❌ Failed: <b>{fmt_num(stats.get('failed', 0))}</b>"
    )


def owner_jobs_list_message(items: List[Dict[str, Any]], title: str, page: int, total_pages: int) -> str:
    if not items:
        return f"⚙️ <b>{title}</b>\n\nNo jobs found in this status."

    lines = [f"⚙️ <b>{title} — Page {page}/{total_pages}</b>\n"]
    for idx, item in enumerate(items, start=1 + (page - 1) * 10):
        j = item["job"]
        bot = item.get("bot")
        bot_handle = f"@{escape(bot.username)}" if bot and bot.username else "System"
        status_icon = "▶️" if j.status.value == "RUNNING" else "❌" if j.status.value == "FAILED" else "⏳"
        lines.append(f"{idx}. <b>{j.job_type.value}</b> (ID: #{j.id})\n   {status_icon} {j.status.value} | Bot: {bot_handle} | Attempts: {j.attempt_count}/{j.max_attempts}\n")

    return "\n".join(lines)


def owner_job_detail_message(detail: Dict[str, Any]) -> str:
    j = detail["job"]
    bot = detail.get("bot")
    bot_handle = f"@{escape(bot.username)}" if bot and bot.username else "None"
    status_icon = "▶️" if j.status.value == "RUNNING" else "❌" if j.status.value == "FAILED" else "⏳"
    created_str = j.created_at.strftime("%Y-%m-%d %H:%M UTC") if j.created_at else "Unknown"
    err_str = escape(j.last_error_message or "None")

    return (
        "⚙️ <b>Job Details</b>\n\n"
        f"• Job ID: <code>#{j.id}</code>\n"
        f"• Type: <b>{j.job_type.value}</b>\n"
        f"• Status: {status_icon} <b>{j.status.value}</b>\n"
        f"• Bot: <b>{bot_handle}</b>\n\n"
        f"• Attempts: <b>{j.attempt_count} / {j.max_attempts}</b>\n"
        f"• Queue: <code>{escape(j.queue_name)}</code>\n"
        f"• Created: <code>{created_str}</code>\n\n"
        f"• Last Error:\n<code>{err_str}</code>"
    )


def owner_job_retry_confirm_message(job_id: int, job_type: str) -> str:
    return f"⚠️ <b>Retry Job #{job_id} ({escape(job_type)})?</b>\n\nThis will requeue the job for execution."


def owner_job_retried_message(success: bool, msg: str) -> str:
    icon = "✅" if success else "⚠️"
    return f"{icon} <b>{escape(msg)}</b>"


# --- 4. Queue Status ---

def owner_queue_message(stats: Dict[str, Any]) -> str:
    return (
        "⏳ <b>Queue Status</b>\n\n"
        f"• 🎬 Video Processing: <b>{fmt_num(stats.get('video_processing', 0))}</b>\n"
        f"• 🔗 Unlock Links: <b>{fmt_num(stats.get('unlock_links', 0))}</b>\n"
        f"• 📤 Broadcast Deliveries: <b>{fmt_num(stats.get('broadcasts', 0))}</b>\n"
        f"• 🆕 Catch-Up Deliveries: <b>{fmt_num(stats.get('catchup', 0))}</b>\n"
        f"• 🔄 Retry Queue: <b>{fmt_num(stats.get('retrying', 0))}</b>\n\n"
        f"• ⏱ Oldest Waiting Job: <b>{stats.get('oldest_waiting', 'None')}</b>"
    )


# --- 5. Broadcasts ---

def owner_broadcasts_summary_message(stats: Dict[str, Any]) -> str:
    return (
        "📤 <b>Broadcast Activity</b>\n\n"
        f"• ▶️ Running: <b>{fmt_num(stats.get('running', 0))}</b>\n"
        f"• ⏳ Waiting: <b>{fmt_num(stats.get('waiting', 0))}</b>\n"
        f"• ✅ Completed Today: <b>{fmt_num(stats.get('completed_today', 0))}</b>\n"
        f"• ⚠️ Partial: <b>{fmt_num(stats.get('partial', 0))}</b>\n"
        f"• ❌ Failed: <b>{fmt_num(stats.get('failed', 0))}</b>"
    )


def owner_broadcasts_list_message(items: List[Dict[str, Any]], title: str, page: int, total_pages: int) -> str:
    if not items:
        return f"📤 <b>{title}</b>\n\nNo broadcasts found in this status."

    lines = [f"📤 <b>{title} — Page {page}/{total_pages}</b>\n"]
    for idx, item in enumerate(items, start=1 + (page - 1) * 10):
        b = item["broadcast"]
        bot = item.get("bot")
        bot_handle = f"@{escape(bot.username)}" if bot and bot.username else f"Bot #{b.client_bot_id}"
        status_icon = "▶️" if b.status.value == "RUNNING" else "✅" if b.status.value == "COMPLETED" else "❌"
        pct = (b.sent_count * 100 // b.total_targets) if b.total_targets > 0 else 0
        lines.append(f"{idx}. <b>Broadcast #{b.id}</b> ({bot_handle})\n   {status_icon} {b.status.value} | Sent: {fmt_num(b.sent_count)}/{fmt_num(b.total_targets)} ({pct}%)\n")

    return "\n".join(lines)


def owner_broadcast_detail_message(detail: Dict[str, Any]) -> str:
    b = detail["broadcast"]
    bot = detail.get("bot")
    bot_handle = f"@{escape(bot.username)}" if bot and bot.username else f"Bot #{b.client_bot_id}"
    status_icon = "▶️" if b.status.value == "RUNNING" else "✅" if b.status.value == "COMPLETED" else "❌"
    remaining = max(0, b.total_targets - (b.sent_count + b.failed_count + b.blocked_count))
    pct = (b.sent_count * 100 // b.total_targets) if b.total_targets > 0 else 0
    started_str = b.started_at.strftime("%Y-%m-%d %H:%M UTC") if b.started_at else "Not started"
    completed_str = b.completed_at.strftime("%Y-%m-%d %H:%M UTC") if b.completed_at else "In progress"

    return (
        "📤 <b>Broadcast Details</b>\n\n"
        f"• Broadcast ID: <code>#{b.id}</code>\n"
        f"• Bot: <b>{bot_handle}</b>\n"
        f"• Video ID: <code>#{b.video_id}</code>\n"
        f"• Status: {status_icon} <b>{b.status.value}</b> ({pct}%)\n\n"
        f"• 🎯 Total Targets: <b>{fmt_num(b.total_targets)}</b>\n"
        f"• ✅ Sent: <b>{fmt_num(b.sent_count)}</b>\n"
        f"• 🚫 Blocked Viewers: <b>{fmt_num(b.blocked_count)}</b>\n"
        f"• ❌ Failed: <b>{fmt_num(b.failed_count)}</b>\n"
        f"• ⏳ Remaining: <b>{fmt_num(remaining)}</b>\n\n"
        f"• Started: <code>{started_str}</code>\n"
        f"• Completed: <code>{completed_str}</code>"
    )


# --- 6. Platform System Stats ---

def owner_systemstats_message(stats: Dict[str, Any]) -> str:
    return (
        "🌐 <b>Control Hub Statistics</b>\n\n"
        f"👤 Clients: <b>{fmt_num(stats.get('total_clients', 0))}</b>\n"
        f"🤖 Connected Bots: <b>{fmt_num(stats.get('total_bots', 0))}</b>\n"
        f"👥 Total Viewers: <b>{fmt_num(stats.get('total_viewers', 0))}</b>\n"
        f"🎬 Total Videos: <b>{fmt_num(stats.get('total_videos', 0))}</b>\n\n"
        f"⚙️ Jobs Running: <b>{fmt_num(stats.get('running_jobs', 0))}</b>\n"
        f"⏳ Jobs Queued: <b>{fmt_num(stats.get('queued_jobs', 0))}</b>\n"
        f"📤 Broadcasts Running: <b>{fmt_num(stats.get('running_broadcasts', 0))}</b>\n"
        f"❌ Failed Jobs: <b>{fmt_num(stats.get('failed_jobs', 0))}</b>\n\n"
        "<b>Today:</b>\n"
        f"• 🆕 New Clients: <b>{fmt_num(stats.get('new_clients_today', 0))}</b>\n"
        f"• 🤖 New Bots: <b>{fmt_num(stats.get('new_bots_today', 0))}</b>\n"
        f"• 👥 New Viewers: <b>{fmt_num(stats.get('new_viewers_today', 0))}</b>\n"
        f"• 🎬 Videos Created: <b>{fmt_num(stats.get('videos_created_today', 0))}</b>"
    )


def owner_help_message() -> str:
    return (
        "❓ <b>Platform Owner Commands</b>\n\n"
        "/clients — View registered clients summary & list\n"
        "/bots — View connected client bots summary\n"
        "/jobs — View active & failed background jobs\n"
        "/queue — View waiting queue status\n"
        "/broadcasts — View broadcast delivery progress\n"
        "/systemstats — View platform-wide statistics\n"
        "/help — Show this help menu"
    )


# ==============================================================================
# 👤 Client Messages
# ==============================================================================

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


def client_suspended_message() -> str:
    return (
        "⏸ <b>Your Control Hub account is temporarily suspended.</b>\n\n"
        "Please contact platform support."
    )


def client_help_message() -> str:
    return (
        "❓ <b>Control Hub Help</b>\n\n"
        "Control Hub lets you connect and manage multiple Telegram video bots.\n\n"
        "<b>Available Commands:</b>\n"
        "/start — Open main menu\n"
        "/connectbot — Connect a new bot\n"
        "/mybots — Manage your connected bots\n"
        "/account — View your account details\n"
        "/help — View this help information"
    )


# ==============================================================================
# 🛡️ Common / Guard Messages
# ==============================================================================

def private_chat_only_message() -> str:
    return "⚠️ <b>Control Hub Bot is only available in private chat.</b>"


def unauthorized_message() -> str:
    return (
        "⛔ <b>Access Denied</b>\n\n"
        "This command is not available for your account."
    )


def unknown_command_message(is_owner: bool = False) -> str:
    help_cmd = "/help"
    return (
        "❓ <b>Unknown Command</b>\n\n"
        f"Type {help_cmd} to see available commands or use the menu below."
    )


def normal_text_reply_message(is_owner: bool = False) -> str:
    if is_owner:
        return "👋 Hello Platform Owner. Please select an option from the menu below."
    return "👋 Hello! Please use the buttons below or send /help to navigate Control Hub."
