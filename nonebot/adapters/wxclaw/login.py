from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from typing_extensions import Self

if TYPE_CHECKING:
    from .adapter import Adapter

FIXED_BASE_URL = "https://ilinkai.weixin.qq.com"
DEFAULT_BOT_TYPE = "3"
MAX_QR_REFRESH_COUNT = 3


@dataclass
class WxClawLoginResult:
    connected: bool = False
    account_id: str = ""
    token: str = ""
    base_url: str = ""
    user_id: str = ""
    qrcode_url: str = ""
    message: str = ""


@dataclass
class QrLoginSession:
    _adapter: Adapter = field(repr=False)
    _base_url: str = FIXED_BASE_URL
    _bot_type: str = DEFAULT_BOT_TYPE
    _timeout_ms: int = 480000
    _auto_connect: bool = False

    qrcode: str = ""
    qrcode_url: str = ""

    async def __aenter__(self) -> Self:
        self.qrcode, self.qrcode_url = await self._adapter.start_qr_login(
            base_url=self._base_url,
            bot_type=self._bot_type,
        )
        return self

    async def __aexit__(self, *_args: object) -> None:
        pass

    async def wait(self) -> WxClawLoginResult:
        async def _on_refresh(qrcode: str, qrcode_url: str) -> None:
            self.qrcode = qrcode
            self.qrcode_url = qrcode_url

        result = await self._adapter.wait_qr_login(
            qrcode=self.qrcode,
            base_url=self._base_url,
            bot_type=self._bot_type,
            timeout_ms=self._timeout_ms,
            _on_refresh=_on_refresh,
        )
        result.qrcode_url = self.qrcode_url

        if self._auto_connect and result.connected:
            self._adapter.connect_login_result(result, self._base_url)

        return result
