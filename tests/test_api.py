from nonebot.adapters.wxclaw.api import (
    _parse_client_version,
    build_base_info,
    build_get_headers,
    build_headers,
)

import pytest


class TestBuildHeaders:
    def test_basic(self) -> None:
        headers = build_headers(
            token="test-token",
            app_id="bot",
            channel_version="2.1.1",
        )
        assert headers["Content-Type"] == "application/json"
        assert headers["AuthorizationType"] == "ilink_bot_token"
        assert headers["Authorization"] == "Bearer test-token"
        assert headers["iLink-App-Id"] == "bot"
        assert "X-WECHAT-UIN" in headers

    def test_no_token(self) -> None:
        headers = build_headers(
            token="",
            app_id="bot",
            channel_version="2.1.1",
        )
        assert "Authorization" not in headers

    def test_client_version_encoding(self) -> None:
        headers = build_headers(
            token="t",
            app_id="bot",
            channel_version="2.1.1",
        )
        expected = (2 << 16) | (1 << 8) | 1
        assert headers["iLink-App-ClientVersion"] == str(expected)


class TestBuildGetHeaders:
    def test_basic(self) -> None:
        headers = build_get_headers(
            app_id="bot",
            channel_version="2.1.1",
        )
        assert headers["iLink-App-Id"] == "bot"
        assert "iLink-App-ClientVersion" in headers
        assert "Content-Type" not in headers
        assert "Authorization" not in headers


class TestBuildBaseInfo:
    def test_basic(self) -> None:
        info = build_base_info("2.1.1")
        assert info["channel_version"] == "2.1.1"


class TestParseClientVersion:
    @pytest.mark.parametrize(
        ("version_str", "expected"),
        [
            ("2.1.1", (2 << 16) | (1 << 8) | 1),
            ("1.0.0", 1 << 16),
            ("0.0.1", 1),
            ("3.2", (3 << 16) | (2 << 8)),
        ],
    )
    def test_versions(self, version_str: str, expected: int) -> None:
        assert _parse_client_version(version_str) == expected
