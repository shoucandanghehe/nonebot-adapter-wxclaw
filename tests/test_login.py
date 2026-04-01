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
