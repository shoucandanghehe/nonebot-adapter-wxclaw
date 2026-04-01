import base64
from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
import os
import time
from typing import TYPE_CHECKING, Any, ClassVar, NoReturn
from typing_extensions import override
import urllib.parse

from nonebot.adapters import (
    Bot as BaseBot,
    Event as BaseEvent,
    Message as BaseMessage,
    MessageSegment as BaseMessageSegment,
)

from nonebot.compat import model_dump, type_validate_python
from nonebot.drivers import Request, Response

from .api import build_base_info, build_headers
from .cdn import (
    aes_ecb_decrypt,
    aes_ecb_encrypt,
    calculate_ciphertext_size,
    parse_aes_key,
)
from .config import WxClawAccountInfo
from .event import Event
from .exception import ActionFailed, NetworkError, SessionExpiredError
from .log import log
from .message import Message, MessageSegment, message_to_item_list
from .models import (
    CDNMedia,
    FileItem,
    GetConfigResponse,
    GetUpdatesResponse,
    GetUploadUrlRequest,
    GetUploadUrlResponse,
    ImageItem,
    MessageItem,
    MessageItemType,
    MessageState,
    MessageType,
    SendMessageRequest,
    SendTypingRequest,
    TypingStatus,
    UploadMediaType,
    VideoItem,
    WeixinMessage,
)
from .utils import API

if TYPE_CHECKING:
    from .adapter import Adapter


@dataclass
class UploadResult:
    filekey: str
    download_encrypted_query_param: str
    aeskey: str
    aes_key_b64: str
    file_size: int
    file_size_ciphertext: int
    file_md5: str


def _generate_client_id() -> str:
    return f"openclaw-weixin:{int(time.time() * 1000)}-{os.urandom(4).hex()}"


class Bot(BaseBot):
    adapter: "Adapter"  # pyright: ignore[reportIncompatibleVariableOverride]

    @override
    def __init__(
        self,
        adapter: "Adapter",
        self_id: str,
        account_info: WxClawAccountInfo,
    ) -> None:
        super().__init__(adapter, self_id)
        self.account_info = account_info
        self.context_tokens: dict[str, str] = {}
        self.get_updates_buf: str = ""

    @override
    def __getattr__(self, name: str) -> NoReturn:
        msg = f"{self.__class__.__name__} has no API named {name!r}"
        raise AttributeError(msg)

    def update_context_token(self, user_id: str, context_token: str) -> None:
        if context_token:
            self.context_tokens[user_id] = context_token

    def get_context_token(self, user_id: str) -> str:
        return self.context_tokens.get(user_id, "")

    def get_authorization_header(self) -> dict[str, str]:
        return build_headers(
            token=self.account_info.token,
            app_id=self.adapter.adapter_config.wxclaw_ilink_app_id,
            channel_version=self.adapter.adapter_config.wxclaw_channel_version,
        )

    def get_api_url(self, endpoint: str) -> str:
        base = self.account_info.base_url.rstrip("/")
        return f"{base}/{endpoint}"

    def _handle_response(self, response: Response, label: str) -> Any:
        if response.status_code != 200:
            msg = f"{label} HTTP {response.status_code}"
            raise NetworkError(msg)

        content = response.content
        if content is None:
            return None
        if isinstance(content, str):
            content = content.encode()
        if not content:
            return None

        data = json.loads(content)
        if isinstance(data, dict):
            errcode = data.get("errcode")
            if errcode == -14:
                raise SessionExpiredError(
                    ret=data.get("ret"),
                    errcode=errcode,
                    errmsg=data.get("errmsg"),
                )
            ret = data.get("ret")
            if ret is not None and ret != 0:
                log(
                    "WARNING",
                    f"{label}: server error response: {data}",
                )
                raise ActionFailed(
                    ret=ret,
                    errcode=errcode,
                    errmsg=data.get("errmsg"),
                )
        return data

    async def _request(self, request: Request, *, label: str = "api") -> Any:
        request.headers.update(self.get_authorization_header())
        log("DEBUG", f"{label}: {request.method} {request.url}")

        try:
            response = await self.adapter.request(request)
        except Exception as e:
            msg = f"{label}: {e}"
            raise NetworkError(msg) from e

        return self._handle_response(response, label)

    @API
    async def get_updates(self) -> GetUpdatesResponse:
        body: dict[str, Any] = {
            "get_updates_buf": self.get_updates_buf,
            "base_info": build_base_info(
                self.adapter.adapter_config.wxclaw_channel_version,
            ),
        }
        request = Request(
            "POST",
            self.get_api_url("ilink/bot/getupdates"),
            json=body,
            timeout=self.adapter.adapter_config.wxclaw_long_poll_timeout / 1000,
        )
        try:
            data = await self._request(request, label="getUpdates")
        except NetworkError:
            log(
                "DEBUG",
                "getUpdates: timeout or network error, returning empty response",
            )
            return GetUpdatesResponse(
                ret=0,
                msgs=[],
                get_updates_buf=self.get_updates_buf,
            )

        return type_validate_python(GetUpdatesResponse, data)

    @API
    async def send_message(self, *, msg: WeixinMessage) -> None:
        body = model_dump(SendMessageRequest(msg=msg), exclude_none=True)
        body["base_info"] = build_base_info(
            self.adapter.adapter_config.wxclaw_channel_version,
        )
        log("TRACE", f"sendMessage body: {body}")
        request = Request(
            "POST",
            self.get_api_url("ilink/bot/sendmessage"),
            json=body,
            timeout=self.adapter.adapter_config.wxclaw_api_timeout / 1000,
        )
        await self._request(request, label="sendMessage")

    @API
    async def send_typing(
        self,
        *,
        to_user_id: str,
        typing_ticket: str = "",
        status: int = TypingStatus.TYPING,
    ) -> None:
        req = SendTypingRequest(
            ilink_user_id=to_user_id,
            typing_ticket=typing_ticket,
            status=status,
        )
        body = model_dump(req, exclude_none=True)
        body["base_info"] = build_base_info(
            self.adapter.adapter_config.wxclaw_channel_version,
        )
        request = Request(
            "POST",
            self.get_api_url("ilink/bot/sendtyping"),
            json=body,
            timeout=self.adapter.adapter_config.wxclaw_api_timeout / 1000,
        )
        await self._request(request, label="sendTyping")

    @API
    async def get_config(
        self,
        *,
        user_id: str,
        context_token: str = "",
    ) -> GetConfigResponse:
        ct = context_token or self.get_context_token(user_id)
        body: dict[str, Any] = {
            "ilink_user_id": user_id,
            "context_token": ct,
            "base_info": build_base_info(
                self.adapter.adapter_config.wxclaw_channel_version,
            ),
        }
        request = Request(
            "POST",
            self.get_api_url("ilink/bot/getconfig"),
            json=body,
            timeout=self.adapter.adapter_config.wxclaw_api_timeout / 1000,
        )
        data = await self._request(request, label="getConfig")
        return type_validate_python(GetConfigResponse, data)

    @API
    async def get_upload_url(
        self,
        *,
        req: GetUploadUrlRequest,
    ) -> GetUploadUrlResponse:
        body = model_dump(req, exclude_none=True)
        body["base_info"] = build_base_info(
            self.adapter.adapter_config.wxclaw_channel_version,
        )
        request = Request(
            "POST",
            self.get_api_url("ilink/bot/getuploadurl"),
            json=body,
            timeout=self.adapter.adapter_config.wxclaw_api_timeout / 1000,
        )
        data = await self._request(request, label="getUploadUrl")
        return type_validate_python(GetUploadUrlResponse, data)

    async def upload_to_cdn(
        self,
        *,
        upload_url: str,
        encrypted_data: bytes,
        label: str = "cdnUpload",
        max_retries: int = 3,
    ) -> str:
        for attempt in range(1, max_retries + 1):
            try:
                request = Request(
                    "POST",
                    upload_url,
                    headers={"Content-Type": "application/octet-stream"},
                    content=encrypted_data,
                )
                resp = await self.adapter.request(request)

                if 400 <= resp.status_code < 500:
                    msg = f"{label}: CDN client error {resp.status_code}"
                    raise NetworkError(msg)
                if resp.status_code != 200:
                    msg = f"{label}: CDN server error {resp.status_code}"
                    raise NetworkError(msg)

                download_param = resp.headers.get("x-encrypted-param", "")
                if not download_param:
                    msg = f"{label}: CDN response missing x-encrypted-param"
                    raise NetworkError(msg)

                log("DEBUG", f"{label}: upload success on attempt {attempt}")
                return download_param

            except NetworkError:
                if attempt >= max_retries:
                    raise
                log(
                    "WARNING",
                    f"{label}: attempt {attempt} failed, retrying...",
                )

        msg = f"{label}: upload failed after {max_retries} attempts"
        raise NetworkError(msg)

    async def download_from_cdn(
        self,
        *,
        url: str,
        aes_key_base64: str,
        label: str = "cdnDownload",
    ) -> bytes:
        request = Request("GET", url)
        try:
            resp = await self.adapter.request(request)
        except Exception as e:
            msg = f"{label}: {e}"
            raise NetworkError(msg) from e

        if resp.status_code != 200:
            msg = f"{label}: CDN download {resp.status_code}"
            raise NetworkError(msg)

        content = resp.content
        if isinstance(content, str):
            content = content.encode()
        if content is None:
            content = b""

        key = parse_aes_key(aes_key_base64)
        return aes_ecb_decrypt(content, key)

    async def prepare_and_upload_file(
        self,
        *,
        file_data: bytes,
        media_type: UploadMediaType,
        to_user_id: str,
    ) -> UploadResult:
        rawsize = len(file_data)
        rawfilemd5 = hashlib.md5(file_data).hexdigest()  # noqa: S324
        filesize = calculate_ciphertext_size(rawsize)
        filekey = os.urandom(16).hex()
        aeskey = os.urandom(16)

        req = GetUploadUrlRequest(
            filekey=filekey,
            media_type=media_type,
            to_user_id=to_user_id,
            rawsize=rawsize,
            rawfilemd5=rawfilemd5,
            filesize=filesize,
            no_need_thumb=True,
            aeskey=aeskey.hex(),
        )
        upload_resp = await self.get_upload_url(req=req)

        cdn_base = self.adapter.adapter_config.wxclaw_cdn_base_url
        upload_url = (upload_resp.upload_full_url or "").strip()
        if not upload_url and upload_resp.upload_param:
            param = urllib.parse.quote(upload_resp.upload_param, safe="")
            fk = urllib.parse.quote(filekey, safe="")
            upload_url = f"{cdn_base}/upload?encrypted_query_param={param}&filekey={fk}"
        if not upload_url:
            msg = "getUploadUrl returned no upload URL"
            raise NetworkError(msg)

        encrypted_data = aes_ecb_encrypt(file_data, aeskey)

        download_param = await self.upload_to_cdn(
            upload_url=upload_url,
            encrypted_data=encrypted_data,
            label=f"cdnUpload[{filekey}]",
        )

        aeskey_hex = aeskey.hex()
        return UploadResult(
            filekey=filekey,
            download_encrypted_query_param=download_param,
            aeskey=aeskey_hex,
            aes_key_b64=base64.b64encode(aeskey_hex.encode("ascii")).decode("ascii"),
            file_size=rawsize,
            file_size_ciphertext=filesize,
            file_md5=rawfilemd5,
        )

    def _build_cdn_download_url(self, media: CDNMedia) -> str:
        if media.full_url:
            return media.full_url
        cdn_base = self.adapter.adapter_config.wxclaw_cdn_base_url
        param = urllib.parse.quote(media.encrypt_query_param or "", safe="")
        return f"{cdn_base}/download?encrypted_query_param={param}"

    async def download_media(self, media: CDNMedia) -> bytes:
        url = self._build_cdn_download_url(media)
        return await self.download_from_cdn(
            url=url,
            aes_key_base64=media.aes_key or "",
        )

    _SEGMENT_MEDIA_TYPE_MAP: ClassVar[dict[str, UploadMediaType]] = {
        "image": UploadMediaType.IMAGE,
        "file": UploadMediaType.FILE,
        "video": UploadMediaType.VIDEO,
    }

    async def fetch_media(
        self,
        message: Message | str,
    ) -> Message:
        if isinstance(message, str):
            return Message(message)

        new_msg = Message()
        for seg in message:
            if seg.type in self._SEGMENT_MEDIA_TYPE_MAP:
                media: CDNMedia | None = seg.data.get("media")
                if (
                    media
                    and (media.encrypt_query_param or media.full_url)
                    and media.aes_key
                    and seg.data.get("content") is None
                ):
                    content = await self.download_media(media)
                    new_data = dict(seg.data)
                    new_data["content"] = content
                    new_msg.append(MessageSegment(seg.type, new_data))
                    continue
            new_msg.append(seg)
        return new_msg

    async def _prepare_segment(
        self,
        seg: MessageSegment,
        to_user_id: str,
    ) -> MessageSegment:
        if seg.type not in self._SEGMENT_MEDIA_TYPE_MAP:
            return seg

        content: bytes | None = seg.data.get("content")
        if content is None:
            if seg.type == "image":
                return seg
            media: CDNMedia | None = seg.data.get("media")
            if media and (media.encrypt_query_param or media.full_url):
                msg = (
                    f"{seg.type} segment has CDN reference but no content; "
                    "call `await bot.fetch_media(message)` first"
                )
                raise ValueError(msg)
            return seg

        media = seg.data.get("media")
        result = await self.prepare_and_upload_file(
            file_data=content,
            media_type=self._SEGMENT_MEDIA_TYPE_MAP[seg.type],
            to_user_id=to_user_id,
        )
        cdn_media = CDNMedia(
            encrypt_query_param=result.download_encrypted_query_param,
            aes_key=result.aes_key_b64,
            encrypt_type=(media.encrypt_type if media else None) or 1,
        )
        return self._build_uploaded_segment(seg, cdn_media, result)

    def _build_uploaded_segment(
        self,
        seg: MessageSegment,
        cdn_media: CDNMedia,
        result: UploadResult,
    ) -> MessageSegment:
        if seg.type == "image":
            return MessageSegment.image(
                image_item=ImageItem(
                    media=cdn_media,
                    mid_size=result.file_size_ciphertext,
                ),
            )
        if seg.type == "file":
            return MessageSegment.file(
                file_item=FileItem(
                    media=cdn_media,
                    file_name=seg.data.get("file_name", ""),
                    md5=result.file_md5,
                    len=str(result.file_size),
                ),
            )
        if seg.type == "video":
            return MessageSegment.video(
                video_item=VideoItem(
                    media=cdn_media,
                    video_size=result.file_size_ciphertext,
                ),
            )
        return seg

    @override
    async def send(
        self,
        event: BaseEvent,
        message: str | BaseMessage | BaseMessageSegment,
        **kwargs: Any,
    ) -> Any:
        if isinstance(message, str):
            msg_obj = Message(message)
        elif isinstance(message, MessageSegment):
            msg_obj = Message([message])
        elif isinstance(message, BaseMessageSegment):
            msg_obj = Message(str(message))
        elif isinstance(message, Message):
            msg_obj = message
        else:
            msg_obj = Message(str(message))

        item_list = message_to_item_list(msg_obj)

        if not isinstance(event, Event):
            msg_err = "WxClaw adapter requires a WxClaw Event"
            raise TypeError(msg_err)

        to_user_id = event.from_user_id

        prepared = Message()
        for seg in msg_obj:
            prepared.append(await self._prepare_segment(seg, to_user_id))
        item_list = message_to_item_list(prepared)

        context_token = kwargs.get("context_token") or event.context_token

        weixin_msg = self._build_outgoing_msg(
            event.from_user_id,
            item_list,
            session_id=event.session_id,
            context_token=context_token,
        )
        await self.send_message(msg=weixin_msg)

    async def send_text(
        self,
        to_user_id: str,
        text: str,
        *,
        session_id: str = "",
        context_token: str = "",
    ) -> None:
        message = Message([MessageSegment.text(text)])
        item_list = message_to_item_list(message)

        msg = self._build_outgoing_msg(
            to_user_id,
            item_list,
            session_id=session_id,
            context_token=context_token,
        )
        await self.send_message(msg=msg)

    def _build_outgoing_msg(
        self,
        to_user_id: str,
        item_list: list[MessageItem],
        *,
        session_id: str = "",
        context_token: str = "",
    ) -> WeixinMessage:
        ct = context_token or self.get_context_token(to_user_id)
        return WeixinMessage(
            from_user_id="",
            to_user_id=to_user_id,
            client_id=_generate_client_id(),
            session_id=session_id or to_user_id,
            message_type=MessageType.BOT,
            message_state=MessageState.FINISH,
            item_list=item_list,
            context_token=ct,
        )

    async def _upload_and_send(
        self,
        to_user_id: str,
        file_data: bytes,
        media_type: UploadMediaType,
        item_builder: Callable[[CDNMedia, UploadResult], MessageItem],
        *,
        session_id: str = "",
        context_token: str = "",
    ) -> None:
        result = await self.prepare_and_upload_file(
            file_data=file_data,
            media_type=media_type,
            to_user_id=to_user_id,
        )
        cdn_media = CDNMedia(
            encrypt_query_param=result.download_encrypted_query_param,
            aes_key=result.aes_key_b64,
            encrypt_type=1,
        )
        item = item_builder(cdn_media, result)
        msg = self._build_outgoing_msg(
            to_user_id,
            [item],
            session_id=session_id,
            context_token=context_token,
        )
        await self.send_message(msg=msg)

    async def send_image(
        self,
        to_user_id: str,
        file_data: bytes,
        *,
        session_id: str = "",
        context_token: str = "",
    ) -> None:
        await self._upload_and_send(
            to_user_id,
            file_data,
            UploadMediaType.IMAGE,
            lambda m, u: MessageItem(
                type=MessageItemType.IMAGE,
                image_item=ImageItem(
                    media=m,
                    mid_size=u.file_size_ciphertext,
                ),
            ),
            session_id=session_id,
            context_token=context_token,
        )

    async def send_file(
        self,
        to_user_id: str,
        file_data: bytes,
        file_name: str,
        *,
        session_id: str = "",
        context_token: str = "",
    ) -> None:
        await self._upload_and_send(
            to_user_id,
            file_data,
            UploadMediaType.FILE,
            lambda m, u: MessageItem(
                type=MessageItemType.FILE,
                file_item=FileItem(
                    media=m,
                    file_name=file_name,
                    md5=u.file_md5,
                    len=str(u.file_size),
                ),
            ),
            session_id=session_id,
            context_token=context_token,
        )

    async def send_video(
        self,
        to_user_id: str,
        file_data: bytes,
        *,
        session_id: str = "",
        context_token: str = "",
    ) -> None:
        await self._upload_and_send(
            to_user_id,
            file_data,
            UploadMediaType.VIDEO,
            lambda m, u: MessageItem(
                type=MessageItemType.VIDEO,
                video_item=VideoItem(
                    media=m,
                    video_size=u.file_size_ciphertext,
                ),
            ),
            session_id=session_id,
            context_token=context_token,
        )
