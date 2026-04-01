from typing import ClassVar
from unittest.mock import AsyncMock

from nonebot.adapters.wxclaw.bot import Bot, UploadResult
from nonebot.adapters.wxclaw.config import Config, WxClawAccountInfo
from nonebot.adapters.wxclaw.event import TextMessageEvent
from nonebot.adapters.wxclaw.message import Message, MessageSegment
from nonebot.adapters.wxclaw.models import (
    MessageItemType,
    MessageState,
    MessageType,
    UploadMediaType,
    WeixinMessage,
)

from nonebug import App
import pytest


@pytest.fixture
def account_info() -> WxClawAccountInfo:
    return WxClawAccountInfo(
        account_id="test-bot",
        token="test-token",
        base_url="https://test.weixin.qq.com",
    )


class TestBot:
    @pytest.mark.asyncio
    async def test_send(self, app: App, account_info: WxClawAccountInfo) -> None:
        from nonebot.adapters.wxclaw.adapter import Adapter

        async with app.test_api() as ctx:
            adapter = ctx.create_adapter(base=Adapter)
            bot = ctx.create_bot(
                base=Bot,
                adapter=adapter,
                self_id="test-bot",
                account_info=account_info,
            )

            event = TextMessageEvent(
                message_id=1,
                from_user_id="user1",
                to_user_id="test-bot",
                session_id="session1",
                context_token="ctx1",
                message=Message([MessageSegment.text("hello")]),
            )

            ctx.should_call_send(
                event,
                Message([MessageSegment.text("response")]),
                result=None,
            )

            await bot.send(event, Message([MessageSegment.text("response")]))

    def test_context_token_management(self, account_info: WxClawAccountInfo) -> None:
        adapter = AsyncMock()
        bot = Bot(adapter, "test-bot", account_info)

        assert bot.get_context_token("user1") == ""
        bot.update_context_token("user1", "token1")
        assert bot.get_context_token("user1") == "token1"
        bot.update_context_token("user1", "token2")
        assert bot.get_context_token("user1") == "token2"
        # empty token should not overwrite
        bot.update_context_token("user1", "")
        assert bot.get_context_token("user1") == "token2"

    def test_get_updates_buf(self, account_info: WxClawAccountInfo) -> None:
        adapter = AsyncMock()
        bot = Bot(adapter, "test-bot", account_info)
        assert bot.get_updates_buf == ""
        bot.get_updates_buf = "buf123"
        assert bot.get_updates_buf == "buf123"


class TestBotHelpers:
    """Tests for Bot helper methods: auth headers, API URL, response handling."""

    @pytest.fixture
    def bot(self, account_info: WxClawAccountInfo) -> Bot:
        adapter = AsyncMock()
        adapter.adapter_config = Config()
        return Bot(adapter, "test-bot", account_info)

    def test_get_authorization_header(self, bot: Bot) -> None:
        headers = bot.get_authorization_header()
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Bearer ")
        assert "Content-Type" in headers

    def test_get_api_url(self, bot: Bot) -> None:
        url = bot.get_api_url("ilink/bot/sendmessage")
        assert url == "https://test.weixin.qq.com/ilink/bot/sendmessage"

    def test_get_api_url_strips_trailing_slash(
        self, account_info: WxClawAccountInfo
    ) -> None:
        account_info.base_url = "https://test.weixin.qq.com/"
        adapter = AsyncMock()
        adapter.adapter_config = Config()
        bot = Bot(adapter, "test-bot", account_info)
        url = bot.get_api_url("endpoint")
        assert url == "https://test.weixin.qq.com/endpoint"

    def test_handle_response_success(self, bot: Bot) -> None:
        from nonebot.drivers import Response

        resp = Response(200, content=b'{"ret": 0, "data": "ok"}')
        result = bot._handle_response(resp, "test")
        assert result == {"ret": 0, "data": "ok"}

    def test_handle_response_http_error(self, bot: Bot) -> None:
        from nonebot.adapters.wxclaw.exception import NetworkError

        from nonebot.drivers import Response

        resp = Response(500, content=b"server error")
        with pytest.raises(NetworkError, match="HTTP 500"):
            bot._handle_response(resp, "test")

    def test_handle_response_session_expired(self, bot: Bot) -> None:
        from nonebot.adapters.wxclaw.exception import SessionExpiredError

        from nonebot.drivers import Response

        resp = Response(
            200, content=b'{"ret": -1, "errcode": -14, "errmsg": "expired"}'
        )
        with pytest.raises(SessionExpiredError):
            bot._handle_response(resp, "test")

    def test_handle_response_action_failed(self, bot: Bot) -> None:
        from nonebot.adapters.wxclaw.exception import ActionFailed

        from nonebot.drivers import Response

        resp = Response(200, content=b'{"ret": -1, "errcode": 100, "errmsg": "bad"}')
        with pytest.raises(ActionFailed):
            bot._handle_response(resp, "test")

    def test_handle_response_empty_content(self, bot: Bot) -> None:
        from nonebot.drivers import Response

        resp = Response(200, content=b"")
        assert bot._handle_response(resp, "test") is None

    def test_handle_response_none_content(self, bot: Bot) -> None:
        from nonebot.drivers import Response

        resp = Response(200, content=None)
        assert bot._handle_response(resp, "test") is None

    def test_handle_response_string_content(self, bot: Bot) -> None:
        from nonebot.drivers import Response

        resp = Response(200, content='{"ret": 0}')
        result = bot._handle_response(resp, "test")
        assert result == {"ret": 0}

    @pytest.mark.asyncio
    async def test_request_success(self, bot: Bot) -> None:
        from nonebot.drivers import Request, Response

        bot.adapter.request = AsyncMock(
            return_value=Response(200, content=b'{"ret": 0}')
        )
        request = Request("POST", "https://example.com/api")
        result = await bot._request(request, label="test")
        assert result == {"ret": 0}
        # Verify auth headers were added
        call_args = bot.adapter.request.call_args[0][0]
        assert "Authorization" in call_args.headers

    @pytest.mark.asyncio
    async def test_request_network_error(self, bot: Bot) -> None:
        from nonebot.adapters.wxclaw.exception import NetworkError

        from nonebot.drivers import Request

        bot.adapter.request = AsyncMock(side_effect=ConnectionError("refused"))
        request = Request("POST", "https://example.com/api")
        with pytest.raises(NetworkError, match="refused"):
            await bot._request(request, label="test")

    def test_getattr_raises(self, bot: Bot) -> None:
        with pytest.raises(AttributeError, match="no API named"):
            bot.nonexistent_api()


class TestSendMedia:
    """Tests for send_image, send_file, send_video convenience methods."""

    UPLOAD_RESULT: ClassVar[UploadResult] = UploadResult(
        filekey="fk123",
        download_encrypted_query_param="enc_param_abc",
        aeskey="0123456789abcdef0123456789abcdef",
        aes_key_b64="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
        file_size=100,
        file_size_ciphertext=112,
        file_md5="d41d8cd98f00b204e9800998ecf8427e",
    )

    @pytest.fixture
    def bot(self, account_info: WxClawAccountInfo) -> Bot:
        adapter = AsyncMock()
        adapter.adapter_config = Config()
        bot = Bot(adapter, "test-bot", account_info)
        bot.update_context_token("user1", "ctx-token-1")
        return bot

    @pytest.mark.asyncio
    async def test_send_image(
        self,
        bot: Bot,
    ) -> None:
        bot.prepare_and_upload_file = AsyncMock(return_value=self.UPLOAD_RESULT)
        bot.send_message = AsyncMock()  # type: ignore[method-assign]

        await bot.send_image("user1", b"fake-image-data")

        bot.prepare_and_upload_file.assert_called_once()
        call_kwargs = bot.prepare_and_upload_file.call_args[1]
        assert call_kwargs["media_type"] == UploadMediaType.IMAGE
        assert call_kwargs["to_user_id"] == "user1"

        bot.send_message.assert_called_once()
        msg: WeixinMessage = bot.send_message.call_args[1]["msg"]
        assert msg.to_user_id == "user1"
        assert msg.from_user_id == ""
        assert msg.client_id is not None
        assert msg.client_id.startswith("openclaw-weixin:")
        assert msg.message_type == MessageType.BOT
        assert msg.message_state == MessageState.FINISH
        assert msg.context_token == "ctx-token-1"
        assert msg.item_list is not None
        assert len(msg.item_list) == 1
        item = msg.item_list[0]
        assert item.type == MessageItemType.IMAGE
        assert item.image_item is not None
        assert item.image_item.media is not None
        assert item.image_item.media.encrypt_query_param == "enc_param_abc"
        # aes_key should be base64(ascii bytes of hex string)
        import base64

        expected_aes_key = base64.b64encode(
            b"0123456789abcdef0123456789abcdef"
        ).decode()
        assert item.image_item.media.aes_key == expected_aes_key
        assert item.image_item.media.encrypt_type == 1
        # mid_size must be set to ciphertext size for original image loading
        assert item.image_item.mid_size == 112

    @pytest.mark.asyncio
    async def test_send_file(
        self,
        bot: Bot,
    ) -> None:
        bot.prepare_and_upload_file = AsyncMock(return_value=self.UPLOAD_RESULT)
        bot.send_message = AsyncMock()  # type: ignore[method-assign]

        await bot.send_file("user1", b"fake-file-data", "document.pdf")

        bot.prepare_and_upload_file.assert_called_once()
        assert (
            bot.prepare_and_upload_file.call_args[1]["media_type"]
            == UploadMediaType.FILE
        )

        msg: WeixinMessage = bot.send_message.call_args[1]["msg"]
        assert msg.item_list is not None
        item = msg.item_list[0]
        assert item.type == MessageItemType.FILE
        assert item.file_item is not None
        assert item.file_item.file_name == "document.pdf"
        # len must be set to plaintext size as string
        assert item.file_item.len == "100"
        assert item.file_item.media is not None
        assert item.file_item.media.encrypt_query_param == "enc_param_abc"

    @pytest.mark.asyncio
    async def test_send_video(
        self,
        bot: Bot,
    ) -> None:
        bot.prepare_and_upload_file = AsyncMock(return_value=self.UPLOAD_RESULT)
        bot.send_message = AsyncMock()  # type: ignore[method-assign]

        await bot.send_video("user1", b"fake-video-data")

        bot.prepare_and_upload_file.assert_called_once()
        assert (
            bot.prepare_and_upload_file.call_args[1]["media_type"]
            == UploadMediaType.VIDEO
        )

        msg: WeixinMessage = bot.send_message.call_args[1]["msg"]
        assert msg.item_list is not None
        item = msg.item_list[0]
        assert item.type == MessageItemType.VIDEO
        assert item.video_item is not None
        assert item.video_item.media is not None
        # video_size must be set to ciphertext size
        assert item.video_item.video_size == 112

    @pytest.mark.asyncio
    async def test_send_image_with_explicit_context_token(
        self,
        bot: Bot,
    ) -> None:
        bot.prepare_and_upload_file = AsyncMock(return_value=self.UPLOAD_RESULT)
        bot.send_message = AsyncMock()  # type: ignore[method-assign]

        await bot.send_image("user1", b"data", context_token="explicit-token")

        msg: WeixinMessage = bot.send_message.call_args[1]["msg"]
        assert msg.context_token == "explicit-token"

    @pytest.mark.asyncio
    async def test_send_image_fallback_context_token(
        self,
        bot: Bot,
    ) -> None:
        bot.prepare_and_upload_file = AsyncMock(return_value=self.UPLOAD_RESULT)
        bot.send_message = AsyncMock()  # type: ignore[method-assign]

        await bot.send_image("unknown-user", b"data")

        msg: WeixinMessage = bot.send_message.call_args[1]["msg"]
        assert msg.context_token == ""


class TestFetchMedia:
    """Tests for explicit CDN media download via fetch_media."""

    @pytest.fixture
    def bot(self, account_info: WxClawAccountInfo) -> Bot:
        adapter = AsyncMock()
        adapter.adapter_config = Config()
        return Bot(adapter, "test-bot", account_info)

    def test_build_cdn_download_url_with_full_url(self, bot: Bot) -> None:
        from nonebot.adapters.wxclaw.models import CDNMedia

        media = CDNMedia(
            full_url="https://cdn.example.com/direct",
            encrypt_query_param="ignored",
        )
        assert bot._build_cdn_download_url(media) == "https://cdn.example.com/direct"

    def test_build_cdn_download_url_fallback(self, bot: Bot) -> None:
        from nonebot.adapters.wxclaw.models import CDNMedia

        media = CDNMedia(encrypt_query_param="param+with/special=chars")
        url = bot._build_cdn_download_url(media)
        assert "encrypted_query_param=" in url
        # Must be URL-encoded
        assert "param%2Bwith%2Fspecial%3Dchars" in url

    @pytest.mark.asyncio
    async def test_fetch_media_downloads_cdn_image(self, bot: Bot) -> None:
        from nonebot.adapters.wxclaw.models import CDNMedia

        bot.download_media = AsyncMock(return_value=b"image-data")

        msg = Message(
            [
                MessageSegment.image(
                    media=CDNMedia(
                        encrypt_query_param="old_param",
                        aes_key="old_key",
                        encrypt_type=1,
                    ),
                )
            ]
        )

        fetched = await bot.fetch_media(msg)

        bot.download_media.assert_called_once()
        assert fetched[0].type == "image"
        assert fetched[0].data["content"] == b"image-data"
        # Original message should be unchanged
        assert "content" not in msg[0].data

    @pytest.mark.asyncio
    async def test_fetch_media_downloads_cdn_file(self, bot: Bot) -> None:
        from nonebot.adapters.wxclaw.models import CDNMedia

        bot.download_media = AsyncMock(return_value=b"file-data")

        msg = Message(
            [
                MessageSegment.file(
                    media=CDNMedia(
                        encrypt_query_param="param",
                        aes_key="key",
                    ),
                    file_name="doc.pdf",
                )
            ]
        )

        fetched = await bot.fetch_media(msg)

        assert fetched[0].data["content"] == b"file-data"
        assert fetched[0].data["file_name"] == "doc.pdf"

    @pytest.mark.asyncio
    async def test_fetch_media_downloads_cdn_video(self, bot: Bot) -> None:
        from nonebot.adapters.wxclaw.models import CDNMedia

        bot.download_media = AsyncMock(return_value=b"video-data")

        msg = Message(
            [
                MessageSegment.video(
                    media=CDNMedia(
                        encrypt_query_param="param",
                        aes_key="key",
                    ),
                )
            ]
        )

        fetched = await bot.fetch_media(msg)

        assert fetched[0].data["content"] == b"video-data"

    @pytest.mark.asyncio
    async def test_fetch_media_skips_text(self, bot: Bot) -> None:
        msg = Message([MessageSegment.text("hello")])

        fetched = await bot.fetch_media(msg)

        assert fetched[0].type == "text"
        assert fetched[0].data["text"] == "hello"

    @pytest.mark.asyncio
    async def test_fetch_media_skips_already_fetched(self, bot: Bot) -> None:
        from nonebot.adapters.wxclaw.models import CDNMedia

        bot.download_media = AsyncMock()

        msg = Message(
            [
                MessageSegment.image(
                    media=CDNMedia(
                        encrypt_query_param="param",
                        aes_key="key",
                    ),
                    content=b"already-downloaded",
                )
            ]
        )

        fetched = await bot.fetch_media(msg)

        bot.download_media.assert_not_called()
        assert fetched[0].data["content"] == b"already-downloaded"

    @pytest.mark.asyncio
    async def test_fetch_media_string_passthrough(self, bot: Bot) -> None:
        fetched = await bot.fetch_media("hello")
        assert fetched[0].type == "text"

    @pytest.mark.asyncio
    async def test_send_forwards_cdn_ref_directly(self, bot: Bot) -> None:
        """CDN references can be forwarded as-is without fetch_media."""
        from nonebot.adapters.wxclaw.event import TextMessageEvent
        from nonebot.adapters.wxclaw.models import CDNMedia

        bot.send_message = AsyncMock()  # type: ignore[method-assign]

        event = TextMessageEvent(
            message_id=1,
            from_user_id="user1",
            to_user_id="test-bot",
            session_id="s1",
            context_token="ct1",
            message=Message([MessageSegment.text("hi")]),
        )

        msg = Message(
            [
                MessageSegment.image(
                    media=CDNMedia(
                        encrypt_query_param="param",
                        aes_key="key",
                    ),
                )
            ]
        )

        await bot.send(event, msg)

        bot.send_message.assert_called_once()
        sent_msg = bot.send_message.call_args[1]["msg"]
        assert sent_msg.item_list[0].image_item is not None
        assert sent_msg.item_list[0].image_item.media.encrypt_query_param == "param"
        assert sent_msg.item_list[0].image_item.media.aes_key == "key"

    @pytest.mark.asyncio
    async def test_send_with_content_uploads(self, bot: Bot) -> None:
        from nonebot.adapters.wxclaw.event import TextMessageEvent
        from nonebot.adapters.wxclaw.models import CDNMedia

        upload_result = UploadResult(
            filekey="fk_new",
            download_encrypted_query_param="new_enc_param",
            aeskey="0123456789abcdef0123456789abcdef",
            aes_key_b64="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
            file_size=100,
            file_size_ciphertext=112,
            file_md5="abc123",
        )

        bot.prepare_and_upload_file = AsyncMock(return_value=upload_result)
        bot.send_message = AsyncMock()  # type: ignore[method-assign]

        event = TextMessageEvent(
            message_id=1,
            from_user_id="user1",
            to_user_id="test-bot",
            session_id="s1",
            context_token="ct1",
            message=Message([MessageSegment.text("hi")]),
        )

        msg = Message(
            [
                MessageSegment.image(
                    media=CDNMedia(
                        encrypt_query_param="old_param",
                        aes_key="old_key",
                    ),
                    content=b"fetched-image-data",
                )
            ]
        )

        await bot.send(event, msg)

        bot.prepare_and_upload_file.assert_called_once()
        bot.send_message.assert_called_once()
        sent_msg = bot.send_message.call_args[1]["msg"]
        assert sent_msg.item_list[0].image_item is not None
        assert (
            sent_msg.item_list[0].image_item.media.encrypt_query_param
            == "new_enc_param"
        )

    @pytest.mark.asyncio
    async def test_send_raises_on_file_cdn_ref_without_content(self, bot: Bot) -> None:
        """File CDN references cannot be forwarded directly, need fetch_media."""
        from nonebot.adapters.wxclaw.event import TextMessageEvent
        from nonebot.adapters.wxclaw.models import CDNMedia

        event = TextMessageEvent(
            message_id=1,
            from_user_id="user1",
            to_user_id="test-bot",
            session_id="s1",
            context_token="ct1",
            message=Message([MessageSegment.text("hi")]),
        )

        msg = Message(
            [
                MessageSegment.file(
                    media=CDNMedia(
                        encrypt_query_param="param",
                        aes_key="key",
                    ),
                    file_name="doc.pdf",
                )
            ]
        )

        with pytest.raises(ValueError, match="fetch_media"):
            await bot.send(event, msg)

    @pytest.mark.asyncio
    async def test_send_raises_on_video_cdn_ref_without_content(self, bot: Bot) -> None:
        """Video CDN references cannot be forwarded directly, need fetch_media."""
        from nonebot.adapters.wxclaw.event import TextMessageEvent
        from nonebot.adapters.wxclaw.models import CDNMedia

        event = TextMessageEvent(
            message_id=1,
            from_user_id="user1",
            to_user_id="test-bot",
            session_id="s1",
            context_token="ct1",
            message=Message([MessageSegment.text("hi")]),
        )

        msg = Message(
            [
                MessageSegment.video(
                    media=CDNMedia(
                        encrypt_query_param="param",
                        aes_key="key",
                    ),
                )
            ]
        )

        with pytest.raises(ValueError, match="fetch_media"):
            await bot.send(event, msg)
