"""Control Hub inline keyboard layouts and navigation buttons."""

from typing import Any, Dict, List, Optional


# ==============================================================================
# 👑 Platform Owner Keyboards
# ==============================================================================

def owner_home_keyboard() -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "👤 Clients", "callback_data": "owner:clients"},
                {"text": "🤖 Bots", "callback_data": "owner:bots"},
            ],
            [
                {"text": "⚙️ Jobs", "callback_data": "owner:jobs"},
                {"text": "⏳ Queue", "callback_data": "owner:queue"},
            ],
            [
                {"text": "📤 Broadcasts", "callback_data": "owner:broadcasts"},
                {"text": "📊 System Stats", "callback_data": "owner:systemstats"},
            ],
        ]
    }


def back_to_owner_home_keyboard() -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "🏠 Home", "callback_data": "nav:owner_home"}]
        ]
    }


# --- Clients Keyboards ---

def owner_clients_summary_keyboard() -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "📋 View Clients", "callback_data": "owner:clients:page:1"},
                {"text": "🔎 Search Client", "callback_data": "owner:clients:search"},
            ],
            [{"text": "🏠 Home", "callback_data": "nav:owner_home"}],
        ]
    }


def owner_clients_list_keyboard(page: int, total_pages: int, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    keyboard: List[List[Dict[str, Any]]] = []

    # Individual client selection buttons (2 per row)
    row: List[Dict[str, Any]] = []
    for item in items:
        c = item["client"]
        label = f"@{c.username}" if c.username else f"Client #{c.id}"
        row.append({"text": f"👤 {label}", "callback_data": f"owner:client:view:{c.id}"})
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    # Pagination row
    nav_row: List[Dict[str, Any]] = []
    if page > 1:
        nav_row.append({"text": "◀ Previous", "callback_data": f"owner:clients:page:{page - 1}"})
    if page < total_pages:
        nav_row.append({"text": "Next ▶", "callback_data": f"owner:clients:page:{page + 1}"})
    if nav_row:
        keyboard.append(nav_row)

    # Search and back buttons
    keyboard.append([
        {"text": "🔎 Search", "callback_data": "owner:clients:search"},
        {"text": "⬅ Back", "callback_data": "owner:clients"},
        {"text": "🏠 Home", "callback_data": "nav:owner_home"},
    ])
    return {"inline_keyboard": keyboard}


def owner_client_detail_keyboard(client_id: int, is_suspended: bool) -> Dict[str, Any]:
    suspend_btn = (
        {"text": "▶️ Reactivate Client", "callback_data": f"owner:client:reactivate:{client_id}"}
        if is_suspended
        else {"text": "⏸ Suspend Client", "callback_data": f"owner:client:suspend:{client_id}"}
    )
    return {
        "inline_keyboard": [
            [{"text": "🤖 View Connected Bots", "callback_data": f"owner:bots:client:{client_id}"}],
            [suspend_btn],
            [
                {"text": "⬅ Back", "callback_data": "owner:clients:page:1"},
                {"text": "🏠 Home", "callback_data": "nav:owner_home"},
            ],
        ]
    }


def owner_client_suspend_confirm_keyboard(client_id: int) -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "❌ Cancel", "callback_data": f"owner:client:view:{client_id}"},
                {"text": "⏸ Suspend", "callback_data": f"owner:client:suspend_confirm:{client_id}"},
            ]
        ]
    }


def owner_client_reactivate_confirm_keyboard(client_id: int) -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "❌ Cancel", "callback_data": f"owner:client:view:{client_id}"},
                {"text": "▶️ Reactivate", "callback_data": f"owner:client:reactivate_confirm:{client_id}"},
            ]
        ]
    }


# --- Bots Keyboards ---

def owner_bots_summary_keyboard() -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "📋 View All Bots", "callback_data": "owner:bots:page:1"},
                {"text": "🔎 Search Bot", "callback_data": "owner:bots:search"},
            ],
            [{"text": "🏠 Home", "callback_data": "nav:owner_home"}],
        ]
    }


def owner_bots_list_keyboard(page: int, total_pages: int, items: List[Dict[str, Any]], client_filter: Optional[int] = None) -> Dict[str, Any]:
    keyboard: List[List[Dict[str, Any]]] = []

    # Bot buttons (2 per row)
    row: List[Dict[str, Any]] = []
    for item in items:
        b = item["bot"]
        label = f"@{b.username}" if b.username else f"Bot #{b.telegram_bot_id}"
        row.append({"text": f"🤖 {label}", "callback_data": f"owner:bot:view:{b.id}"})
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    # Pagination row
    nav_row: List[Dict[str, Any]] = []
    prefix = f"owner:bots:client:{client_filter}:page" if client_filter else "owner:bots:page"
    if page > 1:
        nav_row.append({"text": "◀ Previous", "callback_data": f"{prefix}:{page - 1}"})
    if page < total_pages:
        nav_row.append({"text": "Next ▶", "callback_data": f"{prefix}:{page + 1}"})
    if nav_row:
        keyboard.append(nav_row)

    back_cb = f"owner:client:view:{client_filter}" if client_filter else "owner:bots"
    keyboard.append([
        {"text": "🔎 Search", "callback_data": "owner:bots:search"},
        {"text": "⬅ Back", "callback_data": back_cb},
        {"text": "🏠 Home", "callback_data": "nav:owner_home"},
    ])
    return {"inline_keyboard": keyboard}


def owner_bot_detail_keyboard(bot_id: int, client_id: Optional[int] = None) -> Dict[str, Any]:
    buttons: List[List[Dict[str, Any]]] = []
    if client_id:
        buttons.append([{"text": "👤 View Owner", "callback_data": f"owner:client:view:{client_id}"}])
    buttons.append([
        {"text": "⬅ Back", "callback_data": "owner:bots:page:1"},
        {"text": "🏠 Home", "callback_data": "nav:owner_home"},
    ])
    return {"inline_keyboard": buttons}


# --- Jobs Keyboards ---

def owner_jobs_summary_keyboard() -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "▶️ Running Jobs", "callback_data": "owner:jobs:running:1"},
                {"text": "❌ Failed Jobs", "callback_data": "owner:jobs:failed:1"},
            ],
            [
                {"text": "📋 All Jobs", "callback_data": "owner:jobs:all:1"},
                {"text": "🏠 Home", "callback_data": "nav:owner_home"},
            ],
        ]
    }


def owner_jobs_list_keyboard(page: int, total_pages: int, items: List[Dict[str, Any]], status_filter: str = "all") -> Dict[str, Any]:
    keyboard: List[List[Dict[str, Any]]] = []

    for item in items:
        j = item["job"]
        keyboard.append([
            {"text": f"⚙️ #{j.id} {j.job_type.value} ({j.status.value})", "callback_data": f"owner:job:view:{j.id}"}
        ])

    nav_row: List[Dict[str, Any]] = []
    if page > 1:
        nav_row.append({"text": "◀ Previous", "callback_data": f"owner:jobs:{status_filter}:{page - 1}"})
    if page < total_pages:
        nav_row.append({"text": "Next ▶", "callback_data": f"owner:jobs:{status_filter}:{page + 1}"})
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([
        {"text": "⬅ Back", "callback_data": "owner:jobs"},
        {"text": "🏠 Home", "callback_data": "nav:owner_home"},
    ])
    return {"inline_keyboard": keyboard}


def owner_job_detail_keyboard(job_id: int, is_retryable: bool = False) -> Dict[str, Any]:
    buttons: List[List[Dict[str, Any]]] = []
    if is_retryable:
        buttons.append([{"text": "🔄 Retry Job", "callback_data": f"owner:job:retry:{job_id}"}])
    buttons.append([
        {"text": "⬅ Back", "callback_data": "owner:jobs"},
        {"text": "🏠 Home", "callback_data": "nav:owner_home"},
    ])
    return {"inline_keyboard": buttons}


def owner_job_retry_confirm_keyboard(job_id: int) -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "❌ Cancel", "callback_data": f"owner:job:view:{job_id}"},
                {"text": "🔄 Retry", "callback_data": f"owner:job:retry_confirm:{job_id}"},
            ]
        ]
    }


# --- Queue Keyboards ---

def owner_queue_keyboard() -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "🔄 Refresh", "callback_data": "owner:queue:refresh"},
                {"text": "⚙️ View Jobs", "callback_data": "owner:jobs"},
            ],
            [{"text": "🏠 Home", "callback_data": "nav:owner_home"}],
        ]
    }


# --- Broadcasts Keyboards ---

def owner_broadcasts_summary_keyboard() -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "▶️ Running", "callback_data": "owner:broadcasts:running:1"},
                {"text": "❌ Failed", "callback_data": "owner:broadcasts:failed:1"},
            ],
            [
                {"text": "📋 All Broadcasts", "callback_data": "owner:broadcasts:all:1"},
                {"text": "🏠 Home", "callback_data": "nav:owner_home"},
            ],
        ]
    }


def owner_broadcasts_list_keyboard(page: int, total_pages: int, items: List[Dict[str, Any]], status_filter: str = "all") -> Dict[str, Any]:
    keyboard: List[List[Dict[str, Any]]] = []

    for item in items:
        b = item["broadcast"]
        keyboard.append([
            {"text": f"📤 Broadcast #{b.id} ({b.status.value})", "callback_data": f"owner:broadcast:view:{b.id}"}
        ])

    nav_row: List[Dict[str, Any]] = []
    if page > 1:
        nav_row.append({"text": "◀ Previous", "callback_data": f"owner:broadcasts:{status_filter}:{page - 1}"})
    if page < total_pages:
        nav_row.append({"text": "Next ▶", "callback_data": f"owner:broadcasts:{status_filter}:{page + 1}"})
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([
        {"text": "⬅ Back", "callback_data": "owner:broadcasts"},
        {"text": "🏠 Home", "callback_data": "nav:owner_home"},
    ])
    return {"inline_keyboard": keyboard}


def owner_broadcast_detail_keyboard(broadcast_id: int) -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "🔄 Refresh", "callback_data": f"owner:broadcast:view:{broadcast_id}"}],
            [
                {"text": "⬅ Back", "callback_data": "owner:broadcasts"},
                {"text": "🏠 Home", "callback_data": "nav:owner_home"},
            ],
        ]
    }


# --- System Stats Keyboards ---

def owner_systemstats_keyboard() -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "🔄 Refresh", "callback_data": "owner:systemstats:refresh"},
                {"text": "🏠 Home", "callback_data": "nav:owner_home"},
            ]
        ]
    }


def cancel_search_keyboard() -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "❌ Cancel Search", "callback_data": "owner:search:cancel"}]
        ]
    }


# ==============================================================================
# 👤 Client Keyboards
# ==============================================================================

def client_home_keyboard() -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "🤖 My Bots", "callback_data": "client:mybots"}],
            [{"text": "➕ Connect Bot", "callback_data": "client:connectbot"}],
            [
                {"text": "👤 Account", "callback_data": "client:account"},
                {"text": "❓ Help", "callback_data": "client:help"},
            ],
        ]
    }


def new_client_keyboard() -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "🤖 Connect My Bot", "callback_data": "client:connectbot_start"}],
            [{"text": "❓ How It Works", "callback_data": "client:help"}],
        ]
    }


def connectbot_entry_keyboard() -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "⬅ Back to Home", "callback_data": "nav:client_home"}]
        ]
    }


def mybots_keyboard() -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "➕ Connect Another Bot", "callback_data": "client:connectbot"}],
            [{"text": "🏠 Home", "callback_data": "nav:client_home"}],
        ]
    }


def back_to_client_home_keyboard() -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "🏠 Home", "callback_data": "nav:client_home"}]
        ]
    }
