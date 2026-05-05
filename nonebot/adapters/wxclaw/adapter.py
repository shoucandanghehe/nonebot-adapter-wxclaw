from asyncio import (
    CancelledError,
    Task,
    TimeoutError as AsyncioTimeoutError,
    create_task,
    gather,
    sleep,
    wait_for,
)
from collections.abc import Awaitable, Callable
from json import loads as json_loads
from typing import Any
from typing_extensions import override
from urllib.parse import quote

from nonebot import get_plugin_config
from nonebot.adapters import Adapter as BaseAdapter, Bot as BaseBot

from nonebot.compat import model_dump, type_validate_python
from nonebot.drivers import Driver, HTTPClientMixin, Request
from nonebot.message import handle_event

from .api import build_get_headers, build_headers
from .bot import Bot
from .config import Config, WxClawAccountInfo
from .event import parse_event
from .exception import (
    ActionFailed,
    ApiNotAvailable,
    HTTPStatusError,
    NetworkError,
    SessionExpiredError,
)
from .log import log
from .login import (
    DEFAULT_BOT_TYPE,
    FIXED_BASE_URL,
    MAX_QR_REFRESH_COUNT,
    QrLoginSession,
    VerifyCodeCallback,
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
        self._tasks: set[Task[None]] = set()
        self.setup()

    @classmethod
    @override
    def get_name(cls) -> str:
        return "WxClaw"

    def setup(self) -> None:
        if not isinstance(self.driver, HTTPClientMixin):
            msg = (
                f"Current driver {self.config.driver} does not support HTTP client. "
                f"WxClaw adapter requires an HTTP client driver such as ~httpx or ~aiohttp."
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
                    f"Account {account.account_id} has no token, skipping (use QR login to obtain one)",
                )
                continue
            bot = Bot(self, account.account_id, account)
            task = create_task(self._start_polling(bot))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            log("INFO", f"Started polling for account {account.account_id}")

    async def _cleanup(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await gather(*tasks, return_exceptions=True)
        self._tasks.clear()

        for bot in list(self.bots.values()):
            if isinstance(bot, Bot):
                try:
                    await bot.notify_stop()
                except Exception as e:
                    log(
                        "WARNING",
                        f"notifyStop failed for {bot.self_id} (ignored): {e}",
                    )
            self.bot_disconnect(bot)

    def _dispatch_message(self, bot: Bot, msg: WeixinMessage) -> None:
        try:
            log("TRACE", f"Raw message: {model_dump(msg, exclude_none=True)}")
            event = parse_event(msg)
            if msg.from_user_id and msg.context_token:
                bot.update_context_token(msg.from_user_id, msg.context_token)
            task = create_task(handle_event(bot, event))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        except Exception as e:
            log("ERROR", f"Failed to parse event: {e}", e)

    async def _start_polling(self, bot: Bot) -> None:  # noqa: C901, PLR0912
        try:
            await bot.notify_start()
        except Exception as e:
            log(
                "WARNING",
                f"notifyStart failed for {bot.self_id} (ignored): {e}",
            )

        retry_delay = 1.0
        max_retry_delay = 60.0

        while True:
            try:
                resp = await bot.get_updates()

                if bot.self_id not in self.bots:
                    self.bot_connect(bot)

                retry_delay = 1.0

                if resp.get_updates_buf is not None:
                    bot.get_updates_buf = resp.get_updates_buf

                for msg in resp.msgs or []:
                    if msg.message_type == MessageType.USER:
                        self._dispatch_message(bot, msg)

            except SessionExpiredError:
                log(
                    "ERROR",
                    f"Session expired for account {bot.self_id}, stopping polling. Re-login required.",
                )
                if bot.self_id in self.bots:
                    self.bot_disconnect(bot)
                return

            except HTTPStatusError as e:
                if e.status_code in (401, 403):
                    log(
                        "ERROR",
                        f"Unauthorized ({e.status_code}) for account {bot.self_id}, stopping polling. Re-login required.",
                    )
                    if bot.self_id in self.bots:
                        self.bot_disconnect(bot)
                    return
                log("ERROR", f"Polling HTTP error: {e}", e)
                await sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)

            except (NetworkError, ActionFailed) as e:
                log("ERROR", f"Polling error: {e}", e)
                await sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)

            except CancelledError:
                return

            except Exception as e:
                log("ERROR", f"Unexpected polling error: {e}", e)
                await sleep(retry_delay)
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

    async def _fetch_qr_code(  # noqa: C901
        self,
        *,
        base_url: str = FIXED_BASE_URL,
        bot_type: str = DEFAULT_BOT_TYPE,
    ) -> QRCodeResponse:
        endpoint = f"ilink/bot/get_bot_qrcode?bot_type={bot_type}"
        url = f"{base_url.rstrip('/')}/{endpoint}"
        headers = build_headers(
            token="",
            app_id=self.adapter_config.wxclaw_ilink_app_id,
            channel_version=self.adapter_config.wxclaw_channel_version,
        )

        local_token_list: list[str] = []
        for bot in list(self.bots.values()):
            if not isinstance(bot, Bot):
                continue
            token = bot.account_info.token.strip()
            if token:
                local_token_list.append(token)
                if len(local_token_list) >= 10:
                    break

        if len(local_token_list) < 10:
            for account in self.adapter_config.wxclaw_accounts:
                token = account.token.strip()
                if token and token not in local_token_list:
                    local_token_list.append(token)
                    if len(local_token_list) >= 10:
                        break

        body = {"local_token_list": local_token_list}
        request = Request(
            "POST",
            url,
            headers=headers,
            json=body,
            timeout=self.adapter_config.wxclaw_api_timeout / 1000,
        )
        log("DEBUG", f"fetchQRCode: POST {url}")

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
        return type_validate_python(QRCodeResponse, json_loads(content or b"{}"))

    async def _poll_qr_status(
        self,
        *,
        base_url: str = FIXED_BASE_URL,
        qrcode: str,
        verify_code: str = "",
    ) -> QRStatusResponse:
        endpoint = f"ilink/bot/get_qrcode_status?qrcode={quote(qrcode)}"
        if verify_code:
            endpoint += f"&verify_code={quote(verify_code)}"
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
            log(
                "DEBUG", f"pollQRStatus: HTTP {resp.status_code}, returning wait status"
            )
            return QRStatusResponse(status="wait")

        content = resp.content
        if isinstance(content, str):
            content = content.encode()
        return type_validate_python(QRStatusResponse, json_loads(content or b"{}"))

    async def start_qr_login(
        self,
        *,
        base_url: str = FIXED_BASE_URL,
        bot_type: str = DEFAULT_BOT_TYPE,
    ) -> tuple[str, str]:
        qr_resp = await self._fetch_qr_code(base_url=base_url, bot_type=bot_type)
        log("INFO", f"QR code fetched, url={qr_resp.qrcode_img_content}")
        return qr_resp.qrcode, qr_resp.qrcode_img_content

    async def wait_qr_login(
        self,
        *,
        qrcode: str,
        base_url: str = FIXED_BASE_URL,
        bot_type: str = DEFAULT_BOT_TYPE,
        timeout_ms: int = 480000,
        _on_refresh: QrRefreshCallback | None = None,
        verify_code_callback: VerifyCodeCallback | None = None,
    ) -> WxClawLoginResult:
        try:
            return await wait_for(
                self._poll_qr_until_done(
                    qrcode=qrcode,
                    base_url=base_url,
                    bot_type=bot_type,
                    _on_refresh=_on_refresh,
                    _verify_code_callback=verify_code_callback,
                ),
                timeout=timeout_ms / 1000,
            )
        except AsyncioTimeoutError:
            return WxClawLoginResult(connected=False, message="Login timed out")

    async def _poll_qr_until_done(  # noqa: C901, PLR0912, PLR0915
        self,
        *,
        qrcode: str,
        base_url: str,
        bot_type: str,
        _on_refresh: QrRefreshCallback | None,
        _verify_code_callback: VerifyCodeCallback | None = None,
    ) -> WxClawLoginResult:
        current_base_url = base_url
        current_qrcode = qrcode
        qrcode_url = ""
        qr_refresh_count = 0
        pending_verify_code = ""

        while True:
            status_resp = await self._poll_qr_status(
                base_url=current_base_url,
                qrcode=current_qrcode,
                verify_code=pending_verify_code,
            )
            status = status_resp.status

            if status == "wait":
                await sleep(1)
                continue

            if status == "scaned":
                if pending_verify_code:
                    log("INFO", "Verify code accepted")
                    pending_verify_code = ""
                log("INFO", "QR scanned, waiting for confirmation...")
                await sleep(1)
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
                    f"QR expired, refreshing ({qr_refresh_count}/{MAX_QR_REFRESH_COUNT})",
                )
                pending_verify_code = ""
                current_base_url = base_url
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
                await sleep(1)
                continue

            if status == "need_verifycode":
                if _verify_code_callback is None:
                    return WxClawLoginResult(
                        connected=False,
                        need_verify_code=True,
                        message="需要输入手机微信显示的配对数字, 但未提供 verify_code_callback",
                    )
                code = (await _verify_code_callback()).strip()
                if not code:
                    return WxClawLoginResult(
                        connected=False,
                        need_verify_code=True,
                        message="verify_code_callback 返回了空值",
                    )
                pending_verify_code = code
                continue

            if status == "verify_code_blocked":
                pending_verify_code = ""
                current_base_url = base_url
                qr_refresh_count += 1
                if qr_refresh_count >= MAX_QR_REFRESH_COUNT:
                    return WxClawLoginResult(
                        connected=False,
                        message="多次输入错误, 连接流程已停止",
                    )
                log(
                    "INFO",
                    f"Verify code blocked, refreshing QR ({qr_refresh_count}/{MAX_QR_REFRESH_COUNT})",
                )
                current_qrcode, qrcode_url = await self.start_qr_login(
                    base_url=base_url,
                    bot_type=bot_type,
                )
                if _on_refresh is not None:
                    await _on_refresh(current_qrcode, qrcode_url)
                continue

            if status == "binded_redirect":
                return WxClawLoginResult(
                    connected=False,
                    message="该微信已绑定此实例, 无需重复连接",
                )

            await sleep(1)

    def qr_login(
        self,
        *,
        base_url: str = FIXED_BASE_URL,
        bot_type: str = DEFAULT_BOT_TYPE,
        timeout_ms: int = 480000,
        auto_connect: bool = False,
        verify_code_callback: VerifyCodeCallback | None = None,
    ) -> QrLoginSession:
        return QrLoginSession(
            _adapter=self,
            _base_url=base_url,
            _bot_type=bot_type,
            _timeout_ms=timeout_ms,
            _auto_connect=auto_connect,
            _verify_code_callback=verify_code_callback,
        )

    def connect_login_result(self, result: WxClawLoginResult, base_url: str) -> None:
        account_info = WxClawAccountInfo(
            account_id=result.account_id,
            token=result.token,
            base_url=result.base_url or base_url,
        )
        bot = Bot(self, result.account_id, account_info)
        task = create_task(self._start_polling(bot))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        log("INFO", f"Account {result.account_id} logged in via QR")
