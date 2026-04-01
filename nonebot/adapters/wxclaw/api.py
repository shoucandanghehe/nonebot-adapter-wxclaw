import base64
import os
from typing import Any

from nonebot.compat import model_dump

from .models import BaseInfo


def build_base_info(channel_version: str) -> dict[str, Any]:
    return model_dump(BaseInfo(channel_version=channel_version))


def _random_wechat_uin() -> str:
    uint32 = int.from_bytes(os.urandom(4), "big")
    return base64.b64encode(str(uint32).encode()).decode()


def _parse_client_version(channel_version: str) -> int:
    parts = [*channel_version.split("."), "0", "0", "0"][:3]
    major, minor, patch = (int(x) for x in parts)
    return ((major & 0xFF) << 16) | ((minor & 0xFF) << 8) | (patch & 0xFF)


def build_headers(
    *,
    token: str,
    app_id: str,
    channel_version: str,
) -> dict[str, str]:
    client_version = _parse_client_version(channel_version)

    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "X-WECHAT-UIN": _random_wechat_uin(),
        "iLink-App-Id": app_id,
        "iLink-App-ClientVersion": str(client_version),
    }
    if token.strip():
        headers["Authorization"] = f"Bearer {token.strip()}"
    return headers


def build_get_headers(
    *,
    app_id: str,
    channel_version: str,
) -> dict[str, str]:
    client_version = _parse_client_version(channel_version)
    return {
        "iLink-App-Id": app_id,
        "iLink-App-ClientVersion": str(client_version),
    }
