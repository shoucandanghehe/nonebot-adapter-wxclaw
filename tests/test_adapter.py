from unittest.mock import AsyncMock

from nonebot.adapters.wxclaw.adapter import Adapter
from nonebot.adapters.wxclaw.bot import Bot
from nonebot.adapters.wxclaw.config import WxClawAccountInfo
from nonebot.adapters.wxclaw.exception import ApiNotAvailable

from nonebug import App
import pytest


class TestAdapter:
    def test_get_name(self) -> None:
        assert Adapter.get_name() == "WxClaw"

    @pytest.mark.asyncio
    async def test_create_adapter(self, app: App) -> None:
        async with app.test_api() as ctx:
            adapter = ctx.create_adapter(base=Adapter)
            assert adapter is not None

    @pytest.mark.asyncio
    async def test_create_bot(self, app: App) -> None:
        account_info = WxClawAccountInfo(
            account_id="test-bot",
            token="test-token",
        )
        async with app.test_api() as ctx:
            adapter = ctx.create_adapter(base=Adapter)
            bot = ctx.create_bot(
                base=Bot,
                adapter=adapter,
                self_id="test-bot",
                account_info=account_info,
            )
            assert bot.self_id == "test-bot"
            assert bot.account_info.token == "test-token"

    @pytest.mark.asyncio
    async def test_call_api_valid(self, app: App) -> None:
        """_call_api dispatches to @API methods correctly."""
        from nonebot.adapters.wxclaw.models import (
            MessageState,
            MessageType,
            WeixinMessage,
        )

        account_info = WxClawAccountInfo(
            account_id="test-bot",
            token="test-token",
        )
        async with app.test_api() as ctx:
            adapter = ctx.create_adapter(base=Adapter)
            bot = ctx.create_bot(
                base=Bot,
                adapter=adapter,
                self_id="test-bot",
                account_info=account_info,
            )
            adapter.request = AsyncMock(
                return_value=type(
                    "Response",
                    (),
                    {"status_code": 200, "content": b'{"ret": 0}', "headers": {}},
                )()
            )

            weixin_msg = WeixinMessage(
                to_user_id="user1",
                message_type=MessageType.BOT,
                message_state=MessageState.FINISH,
                item_list=[],
            )

            # Use should_call_api so nonebug expects the call
            ctx.should_call_api("send_message", {"msg": weixin_msg}, None)
            await bot.call_api("send_message", msg=weixin_msg)

    @pytest.mark.asyncio
    async def test_call_api_invalid(self, app: App) -> None:
        """_call_api raises ApiNotAvailable for unknown APIs."""
        account_info = WxClawAccountInfo(
            account_id="test-bot",
            token="test-token",
        )
        async with app.test_api() as ctx:
            adapter = ctx.create_adapter(base=Adapter)
            bot = ctx.create_bot(
                base=Bot,
                adapter=adapter,
                self_id="test-bot",
                account_info=account_info,
            )
            # Call the real _call_api on Adapter class to bypass nonebug
            with pytest.raises(ApiNotAvailable):
                await Adapter._call_api(adapter, bot, "nonexistent_api")

    @pytest.mark.asyncio
    async def test_call_api_wrong_bot_type(self, app: App) -> None:
        """_call_api raises TypeError for non-WxClaw Bot."""
        from nonebot.adapters import Bot as BaseBot

        async with app.test_api() as ctx:
            adapter = ctx.create_adapter(base=Adapter)
            fake_bot = AsyncMock(spec=BaseBot)
            fake_bot.__class__ = BaseBot  # pyright: ignore[reportAttributeAccessIssue]
            with pytest.raises(TypeError, match="Expected WxClaw Bot"):
                await Adapter._call_api(adapter, fake_bot, "send_message")
