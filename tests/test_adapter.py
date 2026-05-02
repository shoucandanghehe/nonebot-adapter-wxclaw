import asyncio
from unittest.mock import AsyncMock, patch

from nonebot.adapters.wxclaw.adapter import Adapter
from nonebot.adapters.wxclaw.bot import Bot
from nonebot.adapters.wxclaw.config import Config, WxClawAccountInfo
from nonebot.adapters.wxclaw.exception import (
    ApiNotAvailable,
    NetworkError,
    SessionExpiredError,
)
from nonebot.adapters.wxclaw.models import (
    GetUpdatesResponse,
    MessageItem,
    MessageItemType,
    MessageState,
    MessageType,
    TextItem,
    WeixinMessage,
)

from nonebug import App
import pytest

ACCOUNT_INFO = WxClawAccountInfo(
    account_id="test-bot",
    token="test-token",
    base_url="https://test.weixin.qq.com",
)


class TestAdapterBasic:
    def test_get_name(self) -> None:
        assert Adapter.get_name() == "WxClaw"

    @pytest.mark.asyncio
    async def test_create_adapter_and_bot(self, app: App) -> None:
        async with app.test_api() as ctx:
            adapter = ctx.create_adapter(base=Adapter)
            bot = ctx.create_bot(
                base=Bot,
                adapter=adapter,
                self_id="test-bot",
                account_info=ACCOUNT_INFO,
            )
            assert bot.self_id == "test-bot"
            assert bot.account_info.token == "test-token"

    def test_setup_rejects_non_http_driver(self) -> None:
        driver = AsyncMock()
        driver.__class__ = type("FakeDriver", (), {})  # pyright: ignore[reportAttributeAccessIssue]
        with pytest.raises(TypeError, match="does not support HTTP client"):
            Adapter(driver)


class TestCallApi:
    @pytest.mark.asyncio
    async def test_dispatches_to_api_method(self, app: App) -> None:
        async with app.test_api() as ctx:
            adapter = ctx.create_adapter(base=Adapter)
            bot = ctx.create_bot(
                base=Bot, adapter=adapter, self_id="test-bot",
                account_info=ACCOUNT_INFO,
            )
            adapter.request = AsyncMock(
                return_value=type(
                    "R", (), {"status_code": 200, "content": b'{"ret": 0}', "headers": {}},
                )(),
            )
            msg = WeixinMessage(
                to_user_id="u1", message_type=MessageType.BOT,
                message_state=MessageState.FINISH, item_list=[],
            )
            ctx.should_call_api("send_message", {"msg": msg}, None)
            await bot.call_api("send_message", msg=msg)

    @pytest.mark.asyncio
    async def test_raises_on_unknown_api(self, app: App) -> None:
        async with app.test_api() as ctx:
            adapter = ctx.create_adapter(base=Adapter)
            bot = ctx.create_bot(
                base=Bot, adapter=adapter, self_id="test-bot",
                account_info=ACCOUNT_INFO,
            )
            with pytest.raises(ApiNotAvailable):
                await Adapter._call_api(adapter, bot, "nonexistent_api")

    @pytest.mark.asyncio
    async def test_raises_on_wrong_bot_type(self, app: App) -> None:
        from nonebot.adapters import Bot as BaseBot

        async with app.test_api() as ctx:
            adapter = ctx.create_adapter(base=Adapter)
            fake_bot = AsyncMock(spec=BaseBot)
            fake_bot.__class__ = BaseBot  # pyright: ignore[reportAttributeAccessIssue]
            with pytest.raises(TypeError, match="Expected WxClaw Bot"):
                await Adapter._call_api(adapter, fake_bot, "send_message")


class FakeAdapter:
    """Minimal adapter stand-in for lifecycle tests. Avoids AsyncMock(spec=) issues."""

    def __init__(self) -> None:
        self.adapter_config = Config(wxclaw_accounts=[ACCOUNT_INFO])
        self.bots: dict[str, Bot] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def bot_connect(self, bot: Bot) -> None:
        self.bots[bot.self_id] = bot

    def bot_disconnect(self, bot: Bot) -> None:
        self.bots.pop(bot.self_id, None)

    _setup = Adapter._setup
    _cleanup = Adapter._cleanup
    _dispatch_message = Adapter._dispatch_message
    _start_polling = Adapter._start_polling
    _track_task = Adapter._track_task
    connect_login_result = Adapter.connect_login_result


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_setup_creates_bots_and_starts_polling(self) -> None:
        adapter = FakeAdapter()
        adapter._start_polling = AsyncMock()

        await adapter._setup()

        assert len(adapter._tasks) == 1

    @pytest.mark.asyncio
    async def test_setup_skips_disabled_account(self) -> None:
        adapter = FakeAdapter()
        adapter.adapter_config = Config(
            wxclaw_accounts=[
                WxClawAccountInfo(
                    account_id="test-bot", token="t", base_url="http://x", enabled=False,
                ),
            ],
        )
        adapter._start_polling = AsyncMock()

        await adapter._setup()

        assert len(adapter._tasks) == 0

    @pytest.mark.asyncio
    async def test_setup_skips_account_without_token(self) -> None:
        adapter = FakeAdapter()
        adapter.adapter_config = Config(
            wxclaw_accounts=[
                WxClawAccountInfo(
                    account_id="test-bot", token="", base_url="http://x",
                ),
            ],
        )
        adapter._start_polling = AsyncMock()

        await adapter._setup()

        assert len(adapter._tasks) == 0

    @pytest.mark.asyncio
    async def test_cleanup_cancels_tasks_and_disconnects(self) -> None:
        adapter = FakeAdapter()
        adapter._start_polling = AsyncMock()

        await adapter._setup()
        assert len(adapter._tasks) == 1

        await adapter._cleanup()
        assert len(adapter.bots) == 0
        assert len(adapter._tasks) == 0


class TestPolling:
    @pytest.mark.asyncio
    async def test_session_expired_disconnects_bot(self) -> None:
        adapter = FakeAdapter()
        bot = Bot(adapter, "test-bot", ACCOUNT_INFO)  # pyright: ignore[reportArgumentType]

        call_count = 0

        async def fake_get_updates() -> GetUpdatesResponse:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return GetUpdatesResponse(ret=0, msgs=[])
            raise SessionExpiredError(ret=-1, errcode=-14)

        bot.get_updates = AsyncMock(side_effect=fake_get_updates)

        await adapter._start_polling(bot)

        assert "test-bot" not in adapter.bots

    @pytest.mark.asyncio
    async def test_network_error_retries(self) -> None:
        adapter = FakeAdapter()
        bot = Bot(adapter, "test-bot", ACCOUNT_INFO)  # pyright: ignore[reportArgumentType]

        call_count = 0

        async def fake_get_updates() -> GetUpdatesResponse:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                msg = "timeout"
                raise NetworkError(msg)
            raise asyncio.CancelledError

        bot.get_updates = AsyncMock(side_effect=fake_get_updates)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await adapter._start_polling(bot)

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_dispatch_message_creates_event(self) -> None:
        adapter = FakeAdapter()
        bot = Bot(adapter, "test-bot", ACCOUNT_INFO)  # pyright: ignore[reportArgumentType]
        adapter.bots["test-bot"] = bot

        msg = WeixinMessage(
            message_id=1,
            from_user_id="user1",
            to_user_id="test-bot",
            session_id="s1",
            message_type=MessageType.USER,
            context_token="ct1",
            item_list=[
                MessageItem(
                    type=MessageItemType.TEXT,
                    text_item=TextItem(text="hello"),
                ),
            ],
        )

        with patch("nonebot.adapters.wxclaw.adapter.handle_event", new_callable=AsyncMock) as mock_handle:
            adapter._dispatch_message(bot, msg)

            # Wait for the task to complete
            await asyncio.gather(*adapter._tasks, return_exceptions=True)

        mock_handle.assert_called_once()
        event = mock_handle.call_args[0][1]
        assert event.get_plaintext() == "hello"
        assert bot.get_context_token("user1") == "ct1"

    @pytest.mark.asyncio
    async def test_polling_processes_user_messages(self) -> None:
        adapter = FakeAdapter()
        bot = Bot(adapter, "test-bot", ACCOUNT_INFO)  # pyright: ignore[reportArgumentType]

        call_count = 0

        async def fake_get_updates() -> GetUpdatesResponse:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return GetUpdatesResponse(
                    ret=0,
                    get_updates_buf="buf1",
                    msgs=[
                        WeixinMessage(
                            message_id=1,
                            from_user_id="u1",
                            message_type=MessageType.USER,
                            item_list=[
                                MessageItem(
                                    type=MessageItemType.TEXT,
                                    text_item=TextItem(text="hi"),
                                ),
                            ],
                        ),
                    ],
                )
            raise asyncio.CancelledError

        bot.get_updates = AsyncMock(side_effect=fake_get_updates)

        with patch("nonebot.adapters.wxclaw.adapter.handle_event", new_callable=AsyncMock):
            await adapter._start_polling(bot)

        assert bot.get_updates_buf == "buf1"

    @pytest.mark.asyncio
    async def test_polling_skips_bot_messages(self) -> None:
        adapter = FakeAdapter()
        bot = Bot(adapter, "test-bot", ACCOUNT_INFO)  # pyright: ignore[reportArgumentType]

        call_count = 0

        async def fake_get_updates() -> GetUpdatesResponse:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return GetUpdatesResponse(
                    ret=0,
                    msgs=[
                        WeixinMessage(
                            message_id=1,
                            from_user_id="bot",
                            message_type=MessageType.BOT,
                            item_list=[],
                        ),
                    ],
                )
            raise asyncio.CancelledError

        bot.get_updates = AsyncMock(side_effect=fake_get_updates)

        with patch("nonebot.adapters.wxclaw.adapter.handle_event", new_callable=AsyncMock) as mock_handle:
            await adapter._start_polling(bot)

        mock_handle.assert_not_called()


class TestConnectLoginResult:
    @pytest.mark.asyncio
    async def test_creates_bot_and_starts_polling(self) -> None:
        adapter = FakeAdapter()
        adapter._start_polling = AsyncMock()

        from nonebot.adapters.wxclaw.login import WxClawLoginResult

        result = WxClawLoginResult(
            connected=True,
            account_id="new-bot",
            token="new-token",
            base_url="https://api.weixin.qq.com",
        )
        adapter.connect_login_result(result, "https://ilinkai.weixin.qq.com")

        assert len(adapter._tasks) == 1
