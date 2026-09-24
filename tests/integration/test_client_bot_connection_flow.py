"""Integration tests for the complete Client Bot Connection & Management Journey."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import ClientBotStatus, enum_val
from app.db.base import Base
from app.repositories.client import ClientRepository
from app.repositories.client_bot import ClientBotRepository
from app.telegram.client import TelegramClient
from app.telegram.control_hub.router import ControlHubRouter
from app.telegram.types import TelegramBotInfo


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
def mock_tg():
    client = TelegramClient(token="dummy")
    client.send_message = AsyncMock(return_value={"message_id": 100})
    client.edit_message_text = AsyncMock(return_value={"message_id": 100})
    client.delete_message = AsyncMock(return_value=True)
    client.answer_callback_query = AsyncMock(return_value=True)
    client.get_me = AsyncMock()
    client.set_webhook = AsyncMock(return_value=True)
    client.set_my_commands = AsyncMock(return_value=True)
    client.delete_webhook = AsyncMock(return_value=True)
    return client


@pytest.mark.asyncio
async def test_full_client_bot_connection_and_mybots_flow(db_session: AsyncSession, mock_tg: TelegramClient):
    router = ControlHubRouter(telegram_client=mock_tg)
    user_id = 555001
    chat_id = 555001

    bot_info = TelegramBotInfo(
        id=987654321,
        is_bot=True,
        first_name="Movie World",
        username="MovieWorldBot",
    )

    with patch("app.telegram.client.TelegramClient.get_me", new_callable=AsyncMock) as mock_get_me, \
         patch("app.telegram.client.TelegramClient.set_webhook", new_callable=AsyncMock) as mock_set_wh, \
         patch("app.telegram.client.TelegramClient.set_my_commands", new_callable=AsyncMock) as mock_set_cmds:

        mock_get_me.return_value = bot_info
        mock_set_wh.return_value = True
        mock_set_cmds.return_value = True

        # 1. Step 1: User enters /connectbot
        res = await router.process_update(
            update={
                "update_id": 1,
                "message": {
                    "message_id": 1,
                    "chat": {"id": chat_id, "type": "private"},
                    "from": {"id": user_id, "username": "movielover", "first_name": "Movie", "is_bot": False},
                    "text": "/connectbot",
                },
            },
            session=db_session,
        )
        assert res["action"] == "client_connectbot"

        # 2. Step 2: User clicks "I Have My Token"
        res = await router.process_update(
            update={
                "update_id": 2,
                "callback_query": {
                    "id": "cb_1",
                    "chat_instance": "ci_1",
                    "message": {"message_id": 100, "chat": {"id": chat_id, "type": "private"}},
                    "from": {"id": user_id, "username": "movielover", "first_name": "Movie", "is_bot": False},
                    "data": "client:connect:token_ready",
                },
            },
            session=db_session,
        )
        assert res["action"] == "cb_client_token_prompt"

        # 3. Step 3: User submits valid BotFather token
        valid_token = "987654321:ABCdefGHIjklMNOpqrsTUVwxyz_1234567"
        res = await router.process_update(
            update={
                "update_id": 3,
                "message": {
                    "message_id": 2,
                    "chat": {"id": chat_id, "type": "private"},
                    "from": {"id": user_id, "username": "movielover", "first_name": "Movie", "is_bot": False},
                    "text": valid_token,
                },
            },
            session=db_session,
        )
        assert res["action"] == "bot_found_confirm"

        # Verify confirmation message was sent and contains confirm button
        mock_tg.send_message.assert_called()
        sent_call = mock_tg.send_message.call_args_list[-1]
        assert "Movie World" in sent_call.kwargs["text"]
        assert "@MovieWorldBot" in sent_call.kwargs["text"]

        markup = sent_call.kwargs["reply_markup"]
        confirm_cb = markup["inline_keyboard"][0][0]["callback_data"]
        assert confirm_cb.startswith("client:connect:confirm:")

        # 4. Step 4: User clicks Confirm Connect
        res = await router.process_update(
            update={
                "update_id": 4,
                "callback_query": {
                    "id": "cb_2",
                    "chat_instance": "ci_2",
                    "message": {"message_id": 100, "chat": {"id": chat_id, "type": "private"}},
                    "from": {"id": user_id, "username": "movielover", "first_name": "Movie", "is_bot": False},
                    "data": confirm_cb,
                },
            },
            session=db_session,
        )
        assert res["action"] == "cb_client_bot_connected_success"

        # 5. Check Database: Bot must now exist and be ACTIVE
        bot_repo = ClientBotRepository(db_session)
        client_repo = ClientRepository(db_session)
        client = await client_repo.get_by_telegram_user_id(user_id)
        assert client is not None

        bots = await bot_repo.list_by_client(client.id)
        assert len(bots) == 1
        assert bots[0].telegram_bot_id == 987654321
        assert bots[0].username == "MovieWorldBot"
        assert enum_val(bots[0].status) == "ACTIVE"

        # 6. Step 5: User runs /mybots -> lists the connected bot
        res = await router.process_update(
            update={
                "update_id": 5,
                "message": {
                    "message_id": 3,
                    "chat": {"id": chat_id, "type": "private"},
                    "from": {"id": user_id, "username": "movielover", "first_name": "Movie", "is_bot": False},
                    "text": "/mybots",
                },
            },
            session=db_session,
        )
        assert res["action"] == "client_mybots"
        mybots_call = mock_tg.send_message.call_args_list[-1]
        assert "@MovieWorldBot" in mybots_call.kwargs["text"]


@pytest.mark.asyncio
async def test_duplicate_and_cross_client_rejection(db_session: AsyncSession, mock_tg: TelegramClient):
    router = ControlHubRouter(telegram_client=mock_tg)
    user_a = 666001
    user_b = 666002

    bot_info = TelegramBotInfo(
        id=1122334455,
        is_bot=True,
        first_name="Shared Bot",
        username="SharedBot",
    )

    token = "1122334455:ABCdefGHIjklMNOpqrsTUVwxyz_1234567"

    with patch("app.telegram.client.TelegramClient.get_me", new_callable=AsyncMock) as mock_get_me, \
         patch("app.telegram.client.TelegramClient.set_webhook", new_callable=AsyncMock) as mock_set_wh, \
         patch("app.telegram.client.TelegramClient.set_my_commands", new_callable=AsyncMock) as mock_set_cmds:

        mock_get_me.return_value = bot_info
        mock_set_wh.return_value = True
        mock_set_cmds.return_value = True

        # Connect bot for User A
        await router.process_update(
            update={"update_id": 1, "callback_query": {"id": "c1", "message": {"message_id": 1, "chat": {"id": user_a, "type": "private"}}, "from": {"id": user_a, "username": "user_a", "is_bot": False}, "data": "client:connect:token_ready"}},
            session=db_session,
        )
        res_a = await router.process_update(
            update={"update_id": 2, "message": {"message_id": 2, "chat": {"id": user_a, "type": "private"}, "from": {"id": user_a, "username": "user_a", "is_bot": False}, "text": token}},
            session=db_session,
        )
        confirm_cb = mock_tg.send_message.call_args.kwargs["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        await router.process_update(
            update={"update_id": 3, "callback_query": {"id": "c2", "message": {"message_id": 1, "chat": {"id": user_a, "type": "private"}}, "from": {"id": user_a, "username": "user_a", "is_bot": False}, "data": confirm_cb}},
            session=db_session,
        )

        # 1. User A tries to submit the same bot again -> Already connected
        await router.process_update(
            update={"update_id": 4, "callback_query": {"id": "c3", "message": {"message_id": 1, "chat": {"id": user_a, "type": "private"}}, "from": {"id": user_a, "username": "user_a", "is_bot": False}, "data": "client:connect:token_ready"}},
            session=db_session,
        )
        res_same = await router.process_update(
            update={"update_id": 5, "message": {"message_id": 3, "chat": {"id": user_a, "type": "private"}, "from": {"id": user_a, "username": "user_a", "is_bot": False}, "text": token}},
            session=db_session,
        )
        assert res_same["action"] == "bot_already_connected"

        # 2. User B tries to connect the same bot -> Rejected (owned by other)
        await router.process_update(
            update={"update_id": 6, "callback_query": {"id": "c4", "message": {"message_id": 2, "chat": {"id": user_b, "type": "private"}}, "from": {"id": user_b, "username": "user_b", "is_bot": False}, "data": "client:connect:token_ready"}},
            session=db_session,
        )
        res_other = await router.process_update(
            update={"update_id": 7, "message": {"message_id": 4, "chat": {"id": user_b, "type": "private"}, "from": {"id": user_b, "username": "user_b", "is_bot": False}, "text": token}},
            session=db_session,
        )
        assert res_other["action"] == "bot_owned_by_other"
