from collections.abc import Iterable
from io import BytesIO
from pathlib import Path
from typing import Any
from typing_extensions import override

from nonebot.adapters import (
    Message as BaseMessage,
    MessageSegment as BaseMessageSegment,
)

from .models import (
    CDNMedia,
    FileItem,
    ImageItem,
    MessageItem,
    MessageItemType,
    TextItem,
    VideoItem,
)


def _normalize_content(content: bytes | BytesIO | Path) -> bytes:
    if isinstance(content, bytes):
        return content
    if isinstance(content, BytesIO):
        return content.getvalue()
    return content.read_bytes()


class MessageSegment(BaseMessageSegment["Message"]):
    @classmethod
    @override
    def get_message_class(cls) -> type["Message"]:
        return Message

    @override
    def __str__(self) -> str:
        if self.type == "text":
            return self.data.get("text", "")
        if self.type == "image":
            return "[图片]"
        if self.type == "voice":
            return "[语音]"
        if self.type == "file":
            name = self.data.get("file_name", "")
            return f"[文件:{name}]" if name else "[文件]"
        if self.type == "video":
            return "[视频]"
        if self.type == "ref":
            title = self.data.get("title", "")
            return f"[引用:{title}]" if title else "[引用]"
        return f"[{self.type}]"

    @override
    def is_text(self) -> bool:
        return self.type == "text"

    @staticmethod
    def text(text: str) -> "MessageSegment":
        return MessageSegment("text", {"text": text})

    @staticmethod
    def image(
        *,
        media: CDNMedia | None = None,
        url: str = "",
        image_item: ImageItem | None = None,
        content: bytes | BytesIO | Path | None = None,
    ) -> "MessageSegment":
        data: dict[str, Any] = {}
        if media:
            data["media"] = media
        if url:
            data["url"] = url
        if image_item:
            data["image_item"] = image_item
        if content is not None:
            data["content"] = _normalize_content(content)
        return MessageSegment("image", data)

    @staticmethod
    def file(
        *,
        media: CDNMedia | None = None,
        file_name: str = "",
        file_item: FileItem | None = None,
        content: bytes | BytesIO | Path | None = None,
    ) -> "MessageSegment":
        data: dict[str, Any] = {}
        if media:
            data["media"] = media
        if not file_name and isinstance(content, Path):
            file_name = content.name
        if file_name:
            data["file_name"] = file_name
        if file_item:
            data["file_item"] = file_item
        if content is not None:
            data["content"] = _normalize_content(content)
        return MessageSegment("file", data)

    @staticmethod
    def video(
        *,
        media: CDNMedia | None = None,
        video_item: VideoItem | None = None,
        content: bytes | BytesIO | Path | None = None,
    ) -> "MessageSegment":
        data: dict[str, Any] = {}
        if media:
            data["media"] = media
        if video_item:
            data["video_item"] = video_item
        if content is not None:
            data["content"] = _normalize_content(content)
        return MessageSegment("video", data)


class Message(BaseMessage[MessageSegment]):
    @classmethod
    @override
    def get_segment_class(cls) -> type[MessageSegment]:
        return MessageSegment

    @staticmethod
    @override
    def _construct(msg: str) -> Iterable[MessageSegment]:
        yield MessageSegment.text(msg)


def _item_to_seg(item: MessageItem) -> MessageSegment | None:
    item_type = item.type
    if item_type == MessageItemType.TEXT and item.text_item:
        return MessageSegment.text(item.text_item.text or "")
    if item_type == MessageItemType.IMAGE and item.image_item:
        return MessageSegment.image(
            media=item.image_item.media,
            url=item.image_item.url or "",
            image_item=item.image_item,
        )
    if item_type == MessageItemType.VOICE and item.voice_item:
        data: dict[str, Any] = {"voice_item": item.voice_item}
        if item.voice_item.media:
            data["media"] = item.voice_item.media
        if item.voice_item.text:
            data["text"] = item.voice_item.text
        return MessageSegment("voice", data)
    if item_type == MessageItemType.FILE and item.file_item:
        return MessageSegment.file(
            media=item.file_item.media,
            file_name=item.file_item.file_name or "",
            file_item=item.file_item,
        )
    if item_type == MessageItemType.VIDEO and item.video_item:
        return MessageSegment.video(
            media=item.video_item.media,
            video_item=item.video_item,
        )
    return None


def item_list_to_message(items: list[MessageItem]) -> Message:
    msg = Message()
    for item in items:
        seg = _item_to_seg(item)
        if seg is not None:
            msg.append(seg)

        if item.ref_msg:
            ref_data: dict[str, Any] = {}
            if item.ref_msg.title:
                ref_data["title"] = item.ref_msg.title
            if item.ref_msg.message_item:
                ref_data["message_item"] = item.ref_msg.message_item
            msg.append(MessageSegment("ref", ref_data))

    return msg


def _seg_to_item(seg: MessageSegment) -> MessageItem | None:
    if seg.type == "text":
        return MessageItem(
            type=MessageItemType.TEXT,
            text_item=TextItem(text=seg.data.get("text", "")),
        )
    if seg.type == "image":
        image_item: ImageItem | None = seg.data.get("image_item")
        if not image_item:
            image_item = ImageItem(media=seg.data.get("media"))
        return MessageItem(type=MessageItemType.IMAGE, image_item=image_item)
    if seg.type == "file":
        file_item: FileItem | None = seg.data.get("file_item")
        if not file_item:
            file_item = FileItem(
                media=seg.data.get("media"),
                file_name=seg.data.get("file_name", ""),
            )
        return MessageItem(type=MessageItemType.FILE, file_item=file_item)
    if seg.type == "video":
        video_item: VideoItem | None = seg.data.get("video_item")
        if not video_item:
            video_item = VideoItem(media=seg.data.get("media"))
        return MessageItem(type=MessageItemType.VIDEO, video_item=video_item)
    return None


def message_to_item_list(message: Message | str) -> list[MessageItem]:
    if isinstance(message, str):
        message = Message(message)

    items: list[MessageItem] = []
    for seg in message:
        if seg.type in ("ref", "voice"):
            continue
        item = _seg_to_item(seg)
        if item is not None:
            items.append(item)
    return items
