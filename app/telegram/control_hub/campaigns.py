"""Control Hub owner campaign compose and progress screens."""

from sqlalchemy import select
from app.core.enums import ClientBotStatus
from app.db.models.client_bot import ClientBot
from app.services.message_campaign_service import MessageCampaignService
from app.services.message_content import extract_content, validate_cross_bot_content
from app.telegram.campaign_flow import clear_draft, draft_keyboard, get_draft, progress_text, set_draft

SCOPE = "hub"


def audience_keyboard():
    return {"inline_keyboard": [
        [{"text": "Client owners", "callback_data": "owner:campaign:owners"}],
        [{"text": "All bot viewers", "callback_data": "owner:campaign:all"}],
        [{"text": "One bot's viewers", "callback_data": "owner:campaign:botlist:1"}],
    ]}


async def start(chat_id, client):
    await client.send_message(chat_id, "Choose who receives your message.", reply_markup=audience_keyboard())
    return {"ok": True, "action": "campaign_audience"}


async def receive(user_id, chat_id, message, client):
    draft = await get_draft(SCOPE, user_id)
    if not draft or not draft.get("audience"):
        return None
    try:
        content = extract_content(message)
        if draft["audience"] != "OWNERS" and content["kind"] != "text":
            info = await client.get_file(content["file_id"])
            content["file_size"] = info.get("file_size") or content["file_size"]
            validate_cross_bot_content(content)
            if not content["file_size"]:
                content["file_size"] = len(await client.download_file(info["file_path"]))
                validate_cross_bot_content(content)
    except ValueError as exc:
        await client.send_message(chat_id, str(exc))
        return {"ok": True, "action": "campaign_unsupported"}
    draft["content"] = content
    draft["source_message_id"] = message.get("message_id")
    await set_draft(SCOPE, user_id, draft)
    await client.send_message(chat_id, "Preview of your broadcast:")
    await client.send_content(chat_id, content)
    await client.send_message(chat_id, "Send this broadcast?", reply_markup=draft_keyboard("owner"))
    return {"ok": True, "action": "campaign_preview"}


async def callback(user_id, chat_id, data, client, session):
    if data == "owner:campaign:start":
        return await start(chat_id, client)
    if data == "owner:campaign:list":
        return await list_campaigns(user_id, chat_id, client, session)
    if data == "owner:campaign:cancel":
        await clear_draft(SCOPE, user_id)
        await client.send_message(chat_id, "Broadcast cancelled.")
        return {"ok": True, "action": "campaign_cancelled"}
    if data == "owner:campaign:owners":
        await set_draft(SCOPE, user_id, {"audience": "OWNERS"})
        await client.send_message(chat_id, "Send the message for all active client owners. Use /cancel to stop.")
        return {"ok": True, "action": "campaign_waiting_for_content"}
    if data == "owner:campaign:all":
        await set_draft(SCOPE, user_id, {"audience": "ALL_VIEWERS"})
        await client.send_message(chat_id, "Send the message for viewers of all active bots. Use /cancel to stop.")
        return {"ok": True, "action": "campaign_waiting_for_content"}
    if data.startswith("owner:campaign:botlist:"):
        page = max(1, int(data.rsplit(":", 1)[1]))
        bots = list((await session.execute(select(ClientBot).where(ClientBot.status == ClientBotStatus.ACTIVE).order_by(ClientBot.id).offset((page - 1) * 10).limit(11))).scalars())
        rows = [[{"text": bot.username or f"Bot #{bot.id}", "callback_data": f"owner:campaign:bot:{bot.id}"}] for bot in bots[:10]]
        nav = []
        if page > 1:
            nav.append({"text": "Previous", "callback_data": f"owner:campaign:botlist:{page - 1}"})
        if len(bots) > 10:
            nav.append({"text": "Next", "callback_data": f"owner:campaign:botlist:{page + 1}"})
        if nav:
            rows.append(nav)
        await client.send_message(chat_id, "Select a bot:", reply_markup={"inline_keyboard": rows})
        return {"ok": True, "action": "campaign_bot_list"}
    if data.startswith("owner:campaign:bot:"):
        bot_id = int(data.rsplit(":", 1)[1])
        bot = await session.get(ClientBot, bot_id)
        if not bot or bot.status != ClientBotStatus.ACTIVE:
            await client.send_message(chat_id, "Bot is unavailable.")
            return {"ok": True, "action": "campaign_bot_unavailable"}
        await set_draft(SCOPE, user_id, {"audience": "ONE_BOT", "bot_id": bot_id})
        await client.send_message(chat_id, f"Send the message for @{bot.username or bot.id}. Use /cancel to stop.")
        return {"ok": True, "action": "campaign_waiting_for_content"}
    if data == "owner:campaign:confirm":
        draft = await get_draft(SCOPE, user_id)
        if not draft or not draft.get("content"):
            await client.send_message(chat_id, "Draft expired. Start again.")
            return {"ok": True, "action": "campaign_expired"}
        try:
            campaign = await MessageCampaignService(session).create(
                creator_telegram_user_id=user_id, audience=draft["audience"],
                content=draft["content"], source_bot="HUB", client_bot_id=draft.get("bot_id"),
                idempotency_key=f"hub:{user_id}:{draft['source_message_id']}" if draft.get("source_message_id") else None,
            )
            await session.commit()
        except ValueError as exc:
            await session.rollback()
            await client.send_message(chat_id, str(exc))
            return {"ok": True, "action": "campaign_invalid"}
        await clear_draft(SCOPE, user_id)
        await client.send_message(chat_id, f"Broadcast #{campaign.id} queued.", reply_markup={"inline_keyboard": [[{"text": "View progress", "callback_data": f"owner:campaign:view:{campaign.id}"}]]})
        return {"ok": True, "action": "campaign_created", "id": campaign.id}
    if data.startswith("owner:campaign:view:"):
        campaign_id = int(data.rsplit(":", 1)[1])
        detail = await MessageCampaignService(session).detail(campaign_id, creator_telegram_user_id=user_id)
        if not detail:
            await client.send_message(chat_id, "Broadcast not found.")
            return {"ok": True, "action": "campaign_not_found"}
        await client.send_message(chat_id, progress_text(detail), reply_markup={"inline_keyboard": [[{"text": "Refresh", "callback_data": data}]]})
        return {"ok": True, "action": "campaign_detail"}
    return {"ok": False}


async def list_campaigns(user_id, chat_id, client, session):
    service = MessageCampaignService(session)
    items = await service.list_campaigns(user_id)
    if not items:
        await client.send_message(chat_id, "No custom broadcasts yet.")
        return {"ok": True, "action": "campaign_list_empty"}
    rows = []
    for item in items:
        detail = await service.detail(item.id)
        rows.append([{"text": f"#{item.id} {detail['status']} {detail['sent']}/{detail['total']}", "callback_data": f"owner:campaign:view:{item.id}"}])
    await client.send_message(chat_id, "Custom broadcasts", reply_markup={"inline_keyboard": rows})
    return {"ok": True, "action": "campaign_list"}
