import asyncio
from collections.abc import Awaitable, Callable
import json
from typing import Any
from typing_extensions import override
from urllib.parse import quote

from nonebot import get_plugin_config
from nonebot.adapters import Adapter as BaseAdapter, Bot as BaseBot

from nonebot.compat import model_dump, type_validate_python
from nonebot.drivers import Driver, HTTPClientMixin, Request
from nonebot.message import handle_event

from .api import build_get_headers
from .bot import Bot
from .config import Config, WxClawAccountInfo
from .event import parse_event
from .exception import (
    ActionFailed,
    ApiNotAvailable,
    NetworkError,
    SessionExpiredError,
)
from .log import log
from .login import (
    DEFAULT_BOT_TYPE,
    FIXED_BASE_URL,
    MAX_QR_REFRESH_COUNT,
    QrLoginSession,
    WxClawLoginResult,
)
from .models import MessageType, QRCodeResponse, QRStatusResponse, WeixinMessage
from .utils import API

QrRefreshCallback = Callable[[str, str], Awaitable[None]]


class Adapter(BaseAdapter):
    @override
    def __init__(self, driver: Driver, **kwargs: Any) -> None:
        super().__init__(driver, **kwargs)
        self.adapter_config = get_plugin_config(Config)
        self._tasks: list[asyncio.Task[None]] = []
        self.setup()

    @classmethod
    @override
    def get_name(cls) -> str:
        return "WxClaw"

    def setup(self) -> None:
        if not isinstance(self.driver, HTTPClientMixin):
            msg = (
                f"Current driver {self.config.driver} does not support HTTP client."
                " WxClaw adapter requires an HTTP client driver such as"
                " ~httpx or ~aiohttp."
            )
            raise TypeError(msg)
        self.on_ready(self._setup)
        self.driver.on_shutdown(self._cleanup)

    async def _setup(self) -> None:
        for account in self.adapter_config.wxclaw_accounts:
            if not account.enabled:
                continue
            if not account.token:
                log(
                    "WARNING",
                    f"Account {account.account_id} has no token, skipping"
                    " (use QR login to obtain one)",
                )
                continue
            bot = Bot(self, account.account_id, account)
            self.bot_connect(bot)
            task = asyncio.create_task(self._start_polling(bot))
            self._tasks.append(task)
            log("INFO", f"Started polling for account {account.account_id}")

    async def _cleanup(self) -> None:
        for task in self._tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        for bot in list(self.bots.values()):
            self.bot_disconnect(bot)

    def _dispatch_message(self, bot: Bot, msg: WeixinMessage) -> None:
        try:
            log("TRACE", f"Raw message: {model_dump(msg, exclude_none=True)}")
            event = parse_event(msg)
            if msg.from_user_id and msg.context_token:
                bot.update_context_token(msg.from_user_id, msg.context_token)
            task = asyncio.create_task(handle_event(bot, event))
            self._tasks.append(task)
        except Exception as e:
            log("ERROR", f"Failed to parse event: {e}", e)

    async def _start_polling(self, bot: Bot) -> None:
        retry_delay = 1.0
        max_retry_delay = 60.0

        while True:
            try:
                resp = await bot.get_updates()

                retry_delay = 1.0

                if resp.get_updates_buf:
                    bot.get_updates_buf = resp.get_updates_buf

                for msg in resp.msgs or []:
                    if msg.message_type == MessageType.USER:
                        self._dispatch_message(bot, msg)

            except SessionExpiredError:
                log(
                    "ERROR",
                    f"Session expired for account {bot.self_id},"
                    " stopping polling. Re-login required.",
                )
                self.bot_disconnect(bot)
                return

            except (NetworkError, ActionFailed) as e:
                log("ERROR", f"Polling error: {e}", e)
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)

            except asyncio.CancelledError:
                return

            except Exception as e:
                log("ERROR", f"Unexpected polling error: {e}", e)
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)

    @override
    async def _call_api(self, bot: BaseBot, api: str, **data: Any) -> Any:
        if not isinstance(bot, Bot):
            msg = f"Expected WxClaw Bot, got {type(bot)}"
            raise TypeError(msg)

        log("DEBUG", f"Bot {bot.self_id} calling API <y>{api}</y>")
        api_handler = getattr(bot.__class__, api, None)
        if not isinstance(api_handler, API):
            raise ApiNotAvailable(api)
        return await api_handler(bot, **data)

    async def _fetch_qr_code(
        self,
        *,
        base_url: str = FIXED_BASE_URL,
        bot_type: str = DEFAULT_BOT_TYPE,
    ) -> QRCodeResponse:
        endpoint = f"ilink/bot/get_bot_qrcode?bot_type={bot_type}"
        url = f"{base_url.rstrip('/')}/{endpoint}"
        headers = build_get_headers(
            app_id=self.adapter_config.wxclaw_ilink_app_id,
            channel_version=self.adapter_config.wxclaw_channel_version,
        )
        request = Request("GET", url, headers=headers, timeout=5.0)
        log("DEBUG", f"fetchQRCode: GET {url}")

        try:
            resp = await self.request(request)
        except Exception as e:
            msg = f"fetchQRCode: {e}"
            raise NetworkError(msg) from e

        if resp.status_code != 200:
            msg = f"fetchQRCode HTTP {resp.status_code}"
            raise NetworkError(msg)

        content = resp.content
        if isinstance(content, str):
            content = content.encode()
        return type_validate_python(QRCodeResponse, json.loads(content or b"{}"))

    async def _poll_qr_status(
        self,
        *,
        base_url: str = FIXED_BASE_URL,
        qrcode: str,
    ) -> QRStatusResponse:
        endpoint = f"ilink/bot/get_qrcode_status?qrcode={quote(qrcode)}"
        url = f"{base_url.rstrip('/')}/{endpoint}"
        headers = build_get_headers(
            app_id=self.adapter_config.wxclaw_ilink_app_id,
            channel_version=self.adapter_config.wxclaw_channel_version,
        )
        request = Request("GET", url, headers=headers, timeout=35.0)
        log("DEBUG", f"pollQRStatus: GET {url}")

        try:
            resp = await self.request(request)
        except Exception:
            log("DEBUG", "pollQRStatus: timeout/network error, returning wait status")
            return QRStatusResponse(status="wait")

        if resp.status_code != 200:
            log("DEBUG", "pollQRStatus: timeout/network error, returning wait status")
            return QRStatusResponse(status="wait")

        content = resp.content
        if isinstance(content, str):
            content = content.encode()
        return type_validate_python(QRStatusResponse, json.loads(content or b"{}"))

    async def start_qr_login(
        self,
        *,
        base_url: str = FIXED_BASE_URL,
        bot_type: str = DEFAULT_BOT_TYPE,
    ) -> tuple[str, str]:
        qr_resp = await self._fetch_qr_code(base_url=base_url, bot_type=bot_type)
        log("INFO", f"QR code fetched, url={qr_resp.qrcode_img_content}")
        return qr_resp.qrcode, qr_resp.qrcode_img_content

    async def wait_qr_login(  # noqa: C901
        self,
        *,
        qrcode: str,
        base_url: str = FIXED_BASE_URL,
        bot_type: str = DEFAULT_BOT_TYPE,
        timeout_ms: int = 480000,
        _on_refresh: QrRefreshCallback | None = None,
    ) -> WxClawLoginResult:
        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        current_base_url = base_url
        current_qrcode = qrcode
        qrcode_url = ""
        qr_refresh_count = 0

        while asyncio.get_event_loop().time() < deadline:
            status_resp = await self._poll_qr_status(
                base_url=current_base_url,
                qrcode=current_qrcode,
            )
            status = status_resp.status

            if status == "wait":
                await asyncio.sleep(1)
                continue

            if status == "scaned":
                log("INFO", "QR scanned, waiting for confirmation...")
                await asyncio.sleep(1)
                continue

            if status == "confirmed":
                if not status_resp.ilink_bot_id:
                    return WxClawLoginResult(
                        connected=False,
                        message="Login confirmed but ilink_bot_id missing",
                    )
                log(
                    "INFO",
                    f"Login confirmed! account_id={status_resp.ilink_bot_id}",
                )
                return WxClawLoginResult(
                    connected=True,
                    account_id=status_resp.ilink_bot_id,
                    token=status_resp.bot_token or "",
                    base_url=status_resp.baseurl or base_url,
                    user_id=status_resp.ilink_user_id or "",
                    qrcode_url=qrcode_url,
                    message="Login successful",
                )

            if status == "expired":
                qr_refresh_count += 1
                if qr_refresh_count >= MAX_QR_REFRESH_COUNT:
                    return WxClawLoginResult(
                        connected=False,
                        message="QR code expired too many times",
                    )
                log(
                    "INFO",
                    f"QR expired, refreshing"
                    f" ({qr_refresh_count}/{MAX_QR_REFRESH_COUNT})",
                )
                current_qrcode, qrcode_url = await self.start_qr_login(
                    base_url=base_url,
                    bot_type=bot_type,
                )
                if _on_refresh is not None:
                    await _on_refresh(current_qrcode, qrcode_url)
                continue

            if status == "scaned_but_redirect":
                if status_resp.redirect_host:
                    current_base_url = f"https://{status_resp.redirect_host}"
                    log("INFO", f"Redirecting polling to {current_base_url}")
                await asyncio.sleep(1)
                continue

            await asyncio.sleep(1)

        return WxClawLoginResult(connected=False, message="Login timed out")

    def qr_login(
        self,
        *,
        base_url: str = FIXED_BASE_URL,
        bot_type: str = DEFAULT_BOT_TYPE,
        timeout_ms: int = 480000,
        auto_connect: bool = False,
    ) -> QrLoginSession:
        return QrLoginSession(
            _adapter=self,
            _base_url=base_url,
            _bot_type=bot_type,
            _timeout_ms=timeout_ms,
            _auto_connect=auto_connect,
        )

    def connect_login_result(self, result: WxClawLoginResult, base_url: str) -> None:
        account_info = WxClawAccountInfo(
            account_id=result.account_id,
            token=result.token,
            base_url=result.base_url or base_url,
        )
        bot = Bot(self, result.account_id, account_info)
        self.bot_connect(bot)
        task = asyncio.create_task(self._start_polling(bot))
        self._tasks.append(task)
        log("INFO", f"Account {result.account_id} logged in via QR")
