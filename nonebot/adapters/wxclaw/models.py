from enum import IntEnum
from typing import Optional

from nonebot.compat import PYDANTIC_V2, ConfigDict
from pydantic import BaseModel


class _BaseModel(BaseModel):
    if PYDANTIC_V2:
        model_config = ConfigDict(extra="allow")
    else:

        class Config(ConfigDict):
            extra = "allow"  # type: ignore[assignment]


class MessageItemType(IntEnum):
    NONE = 0
    TEXT = 1
    IMAGE = 2
    VOICE = 3
    FILE = 4
    VIDEO = 5


class MessageType(IntEnum):
    NONE = 0
    USER = 1
    BOT = 2


class MessageState(IntEnum):
    NEW = 0
    GENERATING = 1
    FINISH = 2


class TypingStatus(IntEnum):
    TYPING = 1
    CANCEL = 2


class UploadMediaType(IntEnum):
    IMAGE = 1
    VIDEO = 2
    FILE = 3
    VOICE = 4


class BaseInfo(_BaseModel):
    channel_version: str | None = None


class CDNMedia(_BaseModel):
    encrypt_query_param: str | None = None
    aes_key: str | None = None
    encrypt_type: int | None = None
    full_url: str | None = None


class TextItem(_BaseModel):
    text: str | None = None


class ImageItem(_BaseModel):
    media: CDNMedia | None = None
    thumb_media: CDNMedia | None = None
    aeskey: str | None = None
    url: str | None = None
    mid_size: int | None = None
    thumb_size: int | None = None
    thumb_height: int | None = None
    thumb_width: int | None = None
    hd_size: int | None = None


class VoiceItem(_BaseModel):
    media: CDNMedia | None = None
    encode_type: int | None = None
    bits_per_sample: int | None = None
    sample_rate: int | None = None
    playtime: int | None = None
    text: str | None = None


class FileItem(_BaseModel):
    media: CDNMedia | None = None
    file_name: str | None = None
    md5: str | None = None
    len: str | None = None


class VideoItem(_BaseModel):
    media: CDNMedia | None = None
    video_size: int | None = None
    play_length: int | None = None
    video_md5: str | None = None
    thumb_media: CDNMedia | None = None
    thumb_size: int | None = None
    thumb_height: int | None = None
    thumb_width: int | None = None


class MessageItem(_BaseModel):
    type: int | None = None
    create_time_ms: int | None = None
    update_time_ms: int | None = None
    is_completed: bool | None = None
    msg_id: str | None = None
    ref_msg: Optional["RefMessage"] = None
    text_item: TextItem | None = None
    image_item: ImageItem | None = None
    voice_item: VoiceItem | None = None
    file_item: FileItem | None = None
    video_item: VideoItem | None = None


class RefMessage(_BaseModel):
    message_item: MessageItem | None = None
    title: str | None = None


MessageItem.model_rebuild()


class WeixinMessage(_BaseModel):
    seq: int | None = None
    message_id: int | None = None
    from_user_id: str | None = None
    to_user_id: str | None = None
    client_id: str | None = None
    create_time_ms: int | None = None
    update_time_ms: int | None = None
    delete_time_ms: int | None = None
    session_id: str | None = None
    group_id: str | None = None
    message_type: int | None = None
    message_state: int | None = None
    item_list: list[MessageItem] | None = None
    context_token: str | None = None


class GetUpdatesRequest(_BaseModel):
    get_updates_buf: str = ""
    base_info: BaseInfo | None = None


class GetUpdatesResponse(_BaseModel):
    ret: int | None = None
    errcode: int | None = None
    errmsg: str | None = None
    msgs: list[WeixinMessage] | None = None
    get_updates_buf: str | None = None
    longpolling_timeout_ms: int | None = None


class SendMessageRequest(_BaseModel):
    msg: WeixinMessage | None = None
    base_info: BaseInfo | None = None


class GetUploadUrlRequest(_BaseModel):
    filekey: str | None = None
    media_type: int | None = None
    to_user_id: str | None = None
    rawsize: int | None = None
    rawfilemd5: str | None = None
    filesize: int | None = None
    thumb_rawsize: int | None = None
    thumb_rawfilemd5: str | None = None
    thumb_filesize: int | None = None
    no_need_thumb: bool | None = None
    aeskey: str | None = None
    base_info: BaseInfo | None = None


class GetUploadUrlResponse(_BaseModel):
    upload_param: str | None = None
    thumb_upload_param: str | None = None
    upload_full_url: str | None = None


class GetConfigResponse(_BaseModel):
    ret: int | None = None
    errmsg: str | None = None
    typing_ticket: str | None = None


class SendTypingRequest(_BaseModel):
    ilink_user_id: str | None = None
    typing_ticket: str | None = None
    status: int | None = None
    base_info: BaseInfo | None = None


class QRCodeResponse(_BaseModel):
    qrcode: str = ""
    qrcode_img_content: str = ""


class QRStatusResponse(_BaseModel):
    status: str = "wait"
    bot_token: str | None = None
    ilink_bot_id: str | None = None
    baseurl: str | None = None
    ilink_user_id: str | None = None
    redirect_host: str | None = None
