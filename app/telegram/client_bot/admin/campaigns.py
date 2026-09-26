"""Client bot owner custom broadcast controls."""

from sqlalchemy.ext.asyncio import AsyncSession
from app.core.enums import BotAdminRole
from app.db.models.client_bot_admin import ClientBotAdmin
from app.services.message_campaign_service import MessageCampaignService
from app.services.message_content import extract_content
from app.telegram.campaign_flow import clear_draft, draft_keyboard, get_draft, progress_text, set_draft


async def owner_allowed(session: AsyncSession, admin_id: int, bot_id: int) -> bool:
    admin = await session.get(ClientBotAdmin, admin_id) if admin_id else None
    return bool(admin and admin.client_bot_id == bot_id and admin.is_active and admin.role == BotAdminRole.OWNER)


async def start(bot_id, user_id, chat_id, telegram_client, session):
    await set_draft(str(bot_id), user_id, {"audience": "ONE_BOT", "bot_id": bot_id})
    await telegram_client.send_message(chat_id, "Send the message you want to broadcast. Use /cancel to stop.")
    return {"ok": True, "action": "campaign_waiting_for_content"}


async def receive(bot_id, user_id, chat_id, message, telegram_client):
    try:
        content = extract_content(message)
    except ValueError as exc:
        await telegram_client.send_message(chat_id, str(exc))
        return {"ok": True, "action": "campaign_unsupported"}
    await set_draft(str(bot_id), user_id, {"audience": "ONE_BOT", "bot_id": bot_id, "content": content, "source_message_id": message.get("message_id")})
    await telegram_client.send_message(chat_id, "Preview of your broadcast:")
    await telegram_client.send_content(chat_id, content)
    await telegram_client.send_message(chat_id, "Send this to all active viewers?", reply_markup=draft_keyboard("admin"))
    return {"ok": True, "action": "campaign_preview"}


async def callback(bot_id, user_id, chat_id, data, telegram_client, session):
    scope = str(bot_id)
    if data == "admin:campaign:new":
        return await start(bot_id, user_id, chat_id, telegram_client, session)
    if data == "admin:campaign:cancel":
        await clear_draft(scope, user_id)
        await telegram_client.send_message(chat_id, "Broadcast cancelled.")
        return {"ok": True, "action": "campaign_cancelled"}
    if data == "admin:campaign:confirm":
        draft = await get_draft(scope, user_id)
        if not draft or not draft.get("content"):
            await telegram_client.send_message(chat_id, "Draft expired. Start again.")
            return {"ok": True, "action": "campaign_expired"}
        try:
            campaign = await MessageCampaignService(session).create(
                creator_telegram_user_id=user_id, audience="ONE_BOT", content=draft["content"],
                source_bot="CLIENT", client_bot_id=bot_id,
                idempotency_key=f"client:{bot_id}:{user_id}:{draft['source_message_id']}" if draft.get("source_message_id") else None,
            )
            await session.commit()
        except ValueError as exc:
            await session.rollback()
            await telegram_client.send_message(chat_id, str(exc))
            return {"ok": True, "action": "campaign_invalid"}
        await clear_draft(scope, user_id)
        await telegram_client.send_message(chat_id, f"Broadcast #{campaign.id} queued.")
        return {"ok": True, "action": "campaign_created", "id": campaign.id}
    if data.startswith("admin:campaign:view:"):
        campaign_id = int(data.rsplit(":", 1)[1])
        detail = await MessageCampaignService(session).detail(campaign_id, creator_telegram_user_id=user_id)
        if not detail:
            await telegram_client.send_message(chat_id, "Broadcast not found.")
            return {"ok": True, "action": "campaign_not_found"}
        await telegram_client.send_message(chat_id, progress_text(detail), reply_markup={"inline_keyboard": [[{"text": "Refresh", "callback_data": data}]]})
        return {"ok": True, "action": "campaign_detail"}
    return {"ok": False}
