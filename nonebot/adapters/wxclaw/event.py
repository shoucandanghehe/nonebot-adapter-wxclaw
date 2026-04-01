from typing_extensions import override

from nonebot.adapters import Event as BaseEvent

from nonebot.compat import model_dump

from .message import Message, item_list_to_message
from .models import (
    FileItem,
    ImageItem,
    MessageItem,
    MessageItemType,
    VideoItem,
    VoiceItem,
    WeixinMessage,
)


class Event(BaseEvent):
    message_id: int | None = None
    from_user_id: str = ""
    to_user_id: str = ""
    session_id: str = ""
    create_time_ms: int | None = None
    context_token: str = ""

    @override
    def get_type(self) -> str:
        raise NotImplementedError

    @override
    def get_event_name(self) -> str:
        return self.get_type()

    @override
    def get_event_description(self) -> str:
        return str(model_dump(self))

    @override
    def get_message(self) -> Message:
        raise NotImplementedError

    @override
    def get_user_id(self) -> str:
        return self.from_user_id

    @override
    def get_session_id(self) -> str:
        return self.session_id

    @override
    def is_tome(self) -> bool:
        return True

    @override
    def get_plaintext(self) -> str:
        return self.get_message().extract_plain_text()


class MessageEvent(Event):
    message: Message = Message()

    @override
    def get_type(self) -> str:
        return "message"

    @override
    def get_event_name(self) -> str:
        return "message"

    @override
    def get_event_description(self) -> str:
        return (
            f"Message {self.message_id} from {self.from_user_id}: {self.message!s:.50}"
        )

    @override
    def get_message(self) -> Message:
        return self.message


class TextMessageEvent(MessageEvent):
    @override
    def get_event_name(self) -> str:
        return "message.text"


class ImageMessageEvent(MessageEvent):
    image_item: ImageItem | None = None

    @override
    def get_event_name(self) -> str:
        return "message.image"


class VoiceMessageEvent(MessageEvent):
    voice_item: VoiceItem | None = None

    @override
    def get_event_name(self) -> str:
        return "message.voice"


class FileMessageEvent(MessageEvent):
    file_item: FileItem | None = None

    @override
    def get_event_name(self) -> str:
        return "message.file"


class VideoMessageEvent(MessageEvent):
    video_item: VideoItem | None = None

    @override
    def get_event_name(self) -> str:
        return "message.video"


def _find_primary_type(
    items: list[MessageItem],
) -> tuple[
    MessageItemType | None,
    ImageItem | None,
    VoiceItem | None,
    FileItem | None,
    VideoItem | None,
]:
    primary_type: MessageItemType | None = None
    image_item: ImageItem | None = None
    voice_item: VoiceItem | None = None
    file_item: FileItem | None = None
    video_item: VideoItem | None = None

    for item in items:
        t = item.type
        if t == MessageItemType.IMAGE:
            primary_type = MessageItemType.IMAGE
            image_item = item.image_item
        elif t == MessageItemType.VOICE:
            primary_type = MessageItemType.VOICE
            voice_item = item.voice_item
        elif t == MessageItemType.FILE:
            primary_type = MessageItemType.FILE
            file_item = item.file_item
        elif t == MessageItemType.VIDEO:
            primary_type = MessageItemType.VIDEO
            video_item = item.video_item
        elif t == MessageItemType.TEXT and primary_type is None:
            primary_type = MessageItemType.TEXT

    return primary_type, image_item, voice_item, file_item, video_item


def parse_event(msg: WeixinMessage) -> Event:
    items = msg.item_list or []
    message = item_list_to_message(items)

    base_kwargs = {
        "message_id": msg.message_id,
        "from_user_id": msg.from_user_id or "",
        "to_user_id": msg.to_user_id or "",
        "session_id": msg.session_id or "",
        "create_time_ms": msg.create_time_ms,
        "context_token": msg.context_token or "",
        "message": message,
    }

    primary_type, image_item, voice_item, file_item, video_item = _find_primary_type(
        items
    )

    if primary_type == MessageItemType.IMAGE:
        return ImageMessageEvent(**base_kwargs, image_item=image_item)
    if primary_type == MessageItemType.VOICE:
        return VoiceMessageEvent(**base_kwargs, voice_item=voice_item)
    if primary_type == MessageItemType.FILE:
        return FileMessageEvent(**base_kwargs, file_item=file_item)
    if primary_type == MessageItemType.VIDEO:
        return VideoMessageEvent(**base_kwargs, video_item=video_item)

    return TextMessageEvent(**base_kwargs)
