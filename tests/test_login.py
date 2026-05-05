import json
from unittest.mock import AsyncMock

from nonebot.adapters.wxclaw.adapter import Adapter
from nonebot.adapters.wxclaw.config import Config

from nonebot.drivers import Response
import pytest


def make_adapter_with_responses(*responses: dict) -> Adapter:
    """Create a mock adapter with pre-configured HTTP responses."""
    adapter = AsyncMock(spec=Adapter)
    adapter.adapter_config = Config()
    adapter.bots = {}
    adapter.request = AsyncMock(
        side_effect=[
            Response(status_code=200, content=json.dumps(r).encode()) for r in responses
        ]
    )
    # Bind the real methods
    adapter._fetch_qr_code = Adapter._fetch_qr_code.__get__(adapter)
    adapter._poll_qr_status = Adapter._poll_qr_status.__get__(adapter)
    adapter.start_qr_login = Adapter.start_qr_login.__get__(adapter)
    adapter.wait_qr_login = Adapter.wait_qr_login.__get__(adapter)
    adapter._poll_qr_until_done = Adapter._poll_qr_until_done.__get__(adapter)
    adapter.qr_login = Adapter.qr_login.__get__(adapter)
    return adapter


class TestStartQrLogin:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        adapter = make_adapter_with_responses(
            {"qrcode": "qr123", "qrcode_img_content": "https://qr/img"}
        )
        qrcode, qrcode_url = await adapter.start_qr_login()
        assert qrcode == "qr123"
        assert qrcode_url == "https://qr/img"
        # 验证请求是 POST 且 body 含 local_token_list
        req = adapter.request.call_args.args[0]
        assert req.method == "POST"
        assert req.json is not None
        assert "local_token_list" in req.json
        assert req.json["local_token_list"] == []

    @pytest.mark.asyncio
    async def test_post_with_local_tokens(self) -> None:
        """已有连接 bot 时,local_token_list 应包含其 token"""
        from nonebot.adapters.wxclaw.bot import Bot
        from nonebot.adapters.wxclaw.config import WxClawAccountInfo

        adapter = make_adapter_with_responses(
            {"qrcode": "qr123", "qrcode_img_content": "https://qr/img"}
        )
        bot = AsyncMock(spec=Bot)
        bot.account_info = WxClawAccountInfo(
            account_id="b1", token="tok1", base_url="https://api"
        )
        adapter.bots = {"b1": bot}
        await adapter.start_qr_login()
        req = adapter.request.call_args.args[0]
        assert req.method == "POST"
        assert req.json == {"local_token_list": ["tok1"]}


class TestWaitQrLogin:
    @pytest.mark.asyncio
    async def test_confirmed(self) -> None:
        adapter = make_adapter_with_responses(
            {
                "status": "confirmed",
                "bot_token": "token123",
                "ilink_bot_id": "bot1",
                "baseurl": "https://api.weixin.qq.com",
                "ilink_user_id": "user1",
            }
        )
        result = await adapter.wait_qr_login(
            qrcode="qr123",
            timeout_ms=5000,
        )
        assert result.connected
        assert result.account_id == "bot1"
        assert result.token == "token123"
        assert result.user_id == "user1"

    @pytest.mark.asyncio
    async def test_confirmed_no_bot_id(self) -> None:
        adapter = make_adapter_with_responses(
            {"status": "confirmed", "bot_token": "tok"}
        )
        result = await adapter.wait_qr_login(
            qrcode="qr123",
            timeout_ms=5000,
        )
        assert not result.connected
        assert "ilink_bot_id" in result.message

    @pytest.mark.asyncio
    async def test_expired_refreshes(self) -> None:
        adapter = make_adapter_with_responses(
            {"status": "expired"},
            # refresh QR code
            {"qrcode": "qr_new", "qrcode_img_content": "https://qr/new"},
            # confirmed on new QR
            {
                "status": "confirmed",
                "bot_token": "tok",
                "ilink_bot_id": "bot1",
                "baseurl": "https://api",
                "ilink_user_id": "u1",
            },
        )
        result = await adapter.wait_qr_login(
            qrcode="qr123",
            timeout_ms=10000,
        )
        assert result.connected
        assert result.account_id == "bot1"

    @pytest.mark.asyncio
    async def test_redirect(self) -> None:
        adapter = make_adapter_with_responses(
            {"status": "scaned_but_redirect", "redirect_host": "newhost.weixin.qq.com"},
            {
                "status": "confirmed",
                "bot_token": "tok",
                "ilink_bot_id": "bot1",
                "baseurl": "https://api",
                "ilink_user_id": "u1",
            },
        )
        result = await adapter.wait_qr_login(
            qrcode="qr123",
            timeout_ms=10000,
        )
        assert result.connected


class TestQrLogin:
    @pytest.mark.asyncio
    async def test_context_manager_basic(self) -> None:
        adapter = make_adapter_with_responses(
            # fetch QR
            {"qrcode": "qr123", "qrcode_img_content": "https://qr/img"},
            # confirmed
            {
                "status": "confirmed",
                "bot_token": "tok",
                "ilink_bot_id": "bot1",
                "baseurl": "https://api",
                "ilink_user_id": "u1",
            },
        )
        async with adapter.qr_login(timeout_ms=5000) as session:
            assert session.qrcode == "qr123"
            assert session.qrcode_url == "https://qr/img"
            result = await session.wait()
        assert result.connected
        assert result.account_id == "bot1"
        assert result.qrcode_url == "https://qr/img"

    @pytest.mark.asyncio
    async def test_qr_refresh_updates_session(self) -> None:
        adapter = make_adapter_with_responses(
            # initial QR
            {"qrcode": "qr1", "qrcode_img_content": "https://qr/1"},
            # expired → refresh
            {"status": "expired"},
            {"qrcode": "qr2", "qrcode_img_content": "https://qr/2"},
            # confirmed
            {
                "status": "confirmed",
                "bot_token": "tok",
                "ilink_bot_id": "bot1",
                "baseurl": "https://api",
                "ilink_user_id": "u1",
            },
        )
        async with adapter.qr_login(timeout_ms=10000) as session:
            assert session.qrcode == "qr1"
            result = await session.wait()
            # After refresh, session fields should be updated
            assert session.qrcode == "qr2"
            assert session.qrcode_url == "https://qr/2"
        assert result.connected


class TestQrNewStatuses:
    @pytest.mark.asyncio
    async def test_need_verifycode_with_callback(self) -> None:
        """提供回调时,need_verifycode 后携带 verify_code 继续轮询"""
        adapter = make_adapter_with_responses(
            {"status": "need_verifycode"},
            # 携带 verify_code 后服务端返回 scaned（验证通过）
            {"status": "scaned"},
            # 确认登录
            {
                "status": "confirmed",
                "bot_token": "tok",
                "ilink_bot_id": "b1",
                "baseurl": "https://api",
                "ilink_user_id": "u1",
            },
        )
        callback = AsyncMock(return_value="1234")
        result = await adapter.wait_qr_login(
            qrcode="qr1",
            timeout_ms=5000,
            verify_code_callback=callback,
        )
        assert result.connected
        callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_need_verifycode_no_callback(self) -> None:
        """无回调时返回 need_verify_code=True"""
        adapter = make_adapter_with_responses({"status": "need_verifycode"})
        result = await adapter.wait_qr_login(qrcode="qr1", timeout_ms=5000)
        assert not result.connected
        assert result.need_verify_code

    @pytest.mark.asyncio
    async def test_need_verifycode_empty_callback(self) -> None:
        """回调返回空字符串时返回 need_verify_code=True"""
        adapter = make_adapter_with_responses({"status": "need_verifycode"})
        callback = AsyncMock(return_value="  ")
        result = await adapter.wait_qr_login(
            qrcode="qr1", timeout_ms=5000, verify_code_callback=callback,
        )
        assert not result.connected
        assert result.need_verify_code
        assert "空值" in result.message

    @pytest.mark.asyncio
    async def test_verify_code_blocked_refreshes(self) -> None:
        """verify_code_blocked 触发二维码刷新"""
        adapter = make_adapter_with_responses(
            {"status": "verify_code_blocked"},
            # 刷新二维码
            {"qrcode": "qr2", "qrcode_img_content": "https://qr/2"},
            # 确认登录
            {
                "status": "confirmed",
                "bot_token": "tok",
                "ilink_bot_id": "b1",
                "baseurl": "https://api",
                "ilink_user_id": "u1",
            },
        )
        result = await adapter.wait_qr_login(qrcode="qr1", timeout_ms=10000)
        assert result.connected
        assert result.account_id == "b1"

    @pytest.mark.asyncio
    async def test_verify_code_blocked_max_refresh(self) -> None:
        """verify_code_blocked 达到刷新上限后停止"""
        from nonebot.adapters.wxclaw.login import MAX_QR_REFRESH_COUNT

        responses: list[dict] = []
        for _ in range(MAX_QR_REFRESH_COUNT):
            responses.append({"status": "verify_code_blocked"})
            responses.append({"qrcode": "qr_new", "qrcode_img_content": "https://qr/new"})
        adapter = make_adapter_with_responses(*responses)
        result = await adapter.wait_qr_login(qrcode="qr1", timeout_ms=10000)
        assert not result.connected
        assert "错误" in result.message

    @pytest.mark.asyncio
    async def test_binded_redirect(self) -> None:
        """binded_redirect 直接返回未连接"""
        adapter = make_adapter_with_responses({"status": "binded_redirect"})
        result = await adapter.wait_qr_login(qrcode="qr1", timeout_ms=5000)
        assert not result.connected
        assert "已绑定" in result.message

    @pytest.mark.asyncio
    async def test_verify_code_passed_to_poll(self) -> None:
        """verify_code 应作为查询参数传递给 pollQRStatus"""
        adapter = make_adapter_with_responses(
            {"status": "need_verifycode"},
            # 返回 confirmed（模拟验证后直接通过）
            {
                "status": "confirmed",
                "bot_token": "tok",
                "ilink_bot_id": "b1",
                "baseurl": "https://api",
                "ilink_user_id": "u1",
            },
        )
        callback = AsyncMock(return_value="5678")
        result = await adapter.wait_qr_login(
            qrcode="qr1",
            timeout_ms=5000,
            verify_code_callback=callback,
        )
        assert result.connected
        # 第二次 request 调用（pollQRStatus）应包含 verify_code 参数
        second_call = adapter.request.call_args_list[1]
        req = second_call.args[0]
        assert "verify_code=5678" in str(req.url)

    @pytest.mark.asyncio
    async def test_qr_login_session_with_verify_callback(self) -> None:
        """QrLoginSession 应透传 verify_code_callback"""
        adapter = make_adapter_with_responses(
            # fetch QR
            {"qrcode": "qr1", "qrcode_img_content": "https://qr/img"},
            # need_verifycode
            {"status": "need_verifycode"},
            # confirmed after verify
            {
                "status": "confirmed",
                "bot_token": "tok",
                "ilink_bot_id": "b1",
                "baseurl": "https://api",
                "ilink_user_id": "u1",
            },
        )
        callback = AsyncMock(return_value="9999")
        async with adapter.qr_login(
            timeout_ms=5000, verify_code_callback=callback
        ) as session:
            assert session.qrcode == "qr1"
            result = await session.wait()
        assert result.connected
        callback.assert_called_once()
