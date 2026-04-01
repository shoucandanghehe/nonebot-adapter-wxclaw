from io import BytesIO
from pathlib import Path

from nonebot.adapters.wxclaw.message import (
    Message,
    MessageSegment,
    item_list_to_message,
    message_to_item_list,
)
from nonebot.adapters.wxclaw.models import (
    CDNMedia,
    FileItem,
    ImageItem,
    MessageItem,
    MessageItemType,
    TextItem,
    VideoItem,
    VoiceItem,
)


class TestMessageSegment:
    def test_text(self) -> None:
        seg = MessageSegment.text("hello")
        assert seg.type == "text"
        assert seg.data == {"text": "hello"}
        assert str(seg) == "hello"
        assert seg.is_text()

    def test_image(self) -> None:
        media = CDNMedia(aes_key="test_key")
        seg = MessageSegment.image(media=media, url="https://example.com/img.png")
        assert seg.type == "image"
        assert seg.data["media"] == media
        assert seg.data["url"] == "https://example.com/img.png"
        assert str(seg) == "[图片]"
        assert not seg.is_text()

    def test_voice(self) -> None:
        seg = MessageSegment("voice", {"text": "transcribed text"})
        assert seg.type == "voice"
        assert seg.data["text"] == "transcribed text"
        assert str(seg) == "[语音]"

    def test_file(self) -> None:
        seg = MessageSegment.file(file_name="doc.pdf")
        assert seg.type == "file"
        assert seg.data["file_name"] == "doc.pdf"
        assert str(seg) == "[文件:doc.pdf]"

    def test_video(self) -> None:
        seg = MessageSegment.video()
        assert seg.type == "video"
        assert str(seg) == "[视频]"

    def test_ref(self) -> None:
        seg = MessageSegment("ref", {"title": "quoted message"})
        assert seg.type == "ref"
        assert str(seg) == "[引用:quoted message]"

    def test_image_no_args(self) -> None:
        seg = MessageSegment.image()
        assert seg.type == "image"
        assert seg.data == {}

    def test_file_no_name(self) -> None:
        seg = MessageSegment.file()
        assert str(seg) == "[文件]"

    def test_ref_no_title(self) -> None:
        seg = MessageSegment("ref", {})
        assert str(seg) == "[引用]"

    def test_image_content_bytes(self) -> None:
        seg = MessageSegment.image(content=b"raw-image")
        assert seg.data["content"] == b"raw-image"

    def test_image_content_bytesio(self) -> None:
        seg = MessageSegment.image(content=BytesIO(b"bytesio-image"))
        assert seg.data["content"] == b"bytesio-image"

    def test_image_content_path(self, tmp_path: Path) -> None:
        f = tmp_path / "img.png"
        f.write_bytes(b"path-image")
        seg = MessageSegment.image(content=f)
        assert seg.data["content"] == b"path-image"

    def test_file_content_path_auto_name(self, tmp_path: Path) -> None:
        f = tmp_path / "report.pdf"
        f.write_bytes(b"pdf-data")
        seg = MessageSegment.file(content=f)
        assert seg.data["content"] == b"pdf-data"
        assert seg.data["file_name"] == "report.pdf"

    def test_file_content_path_explicit_name(self, tmp_path: Path) -> None:
        f = tmp_path / "report.pdf"
        f.write_bytes(b"pdf-data")
        seg = MessageSegment.file(content=f, file_name="custom.pdf")
        assert seg.data["file_name"] == "custom.pdf"

    def test_video_content_bytesio(self) -> None:
        seg = MessageSegment.video(content=BytesIO(b"video-data"))
        assert seg.data["content"] == b"video-data"


class TestMessage:
    def test_construct_from_string(self) -> None:
        msg = Message("hello world")
        assert len(msg) == 1
        assert msg[0].type == "text"
        assert msg[0].data["text"] == "hello world"

    def test_construct_from_segments(self) -> None:
        msg = Message(
            [MessageSegment.text("hi"), MessageSegment.image(url="http://img.png")]
        )
        assert len(msg) == 2
        assert msg[0].type == "text"
        assert msg[1].type == "image"

    def test_add_segment(self) -> None:
        msg = Message("hello") + MessageSegment.image()
        assert len(msg) == 2

    def test_extract_plain_text(self) -> None:
        msg = Message(
            [
                MessageSegment.text("hello "),
                MessageSegment.image(),
                MessageSegment.text("world"),
            ]
        )
        assert msg.extract_plain_text() == "hello world"

    def test_str(self) -> None:
        msg = Message([MessageSegment.text("hi"), MessageSegment.image()])
        assert str(msg) == "hi[图片]"


class TestItemListConversion:
    def test_text_roundtrip(self) -> None:
        items = [
            MessageItem(
                type=MessageItemType.TEXT,
                text_item=TextItem(text="hello"),
            )
        ]
        msg = item_list_to_message(items)
        assert len(msg) == 1
        assert msg[0].type == "text"
        assert msg[0].data["text"] == "hello"

        back = message_to_item_list(msg)
        assert len(back) == 1
        assert back[0].type == MessageItemType.TEXT
        assert back[0].text_item is not None
        assert back[0].text_item.text == "hello"

    def test_image_roundtrip(self) -> None:
        media = CDNMedia(aes_key="key123", full_url="https://cdn/img")
        items = [
            MessageItem(
                type=MessageItemType.IMAGE,
                image_item=ImageItem(media=media, url="https://cdn/thumb"),
            )
        ]
        msg = item_list_to_message(items)
        assert len(msg) == 1
        assert msg[0].type == "image"
        assert msg[0].data["url"] == "https://cdn/thumb"

        back = message_to_item_list(msg)
        assert len(back) == 1
        assert back[0].type == MessageItemType.IMAGE
        assert back[0].image_item is not None

    def test_voice_receive(self) -> None:
        items = [
            MessageItem(
                type=MessageItemType.VOICE,
                voice_item=VoiceItem(text="voice text"),
            )
        ]
        msg = item_list_to_message(items)
        assert msg[0].type == "voice"
        assert msg[0].data["text"] == "voice text"

    def test_file_roundtrip(self) -> None:
        items = [
            MessageItem(
                type=MessageItemType.FILE,
                file_item=FileItem(file_name="test.pdf"),
            )
        ]
        msg = item_list_to_message(items)
        assert msg[0].type == "file"
        assert msg[0].data["file_name"] == "test.pdf"

    def test_video_roundtrip(self) -> None:
        items = [
            MessageItem(
                type=MessageItemType.VIDEO,
                video_item=VideoItem(video_size=1024),
            )
        ]
        msg = item_list_to_message(items)
        assert msg[0].type == "video"

    def test_message_to_item_list_from_string(self) -> None:
        items = message_to_item_list("hello world")
        assert len(items) == 1
        assert items[0].type == MessageItemType.TEXT
        assert items[0].text_item is not None
        assert items[0].text_item.text == "hello world"

    def test_mixed_items(self) -> None:
        items = [
            MessageItem(
                type=MessageItemType.TEXT,
                text_item=TextItem(text="check this: "),
            ),
            MessageItem(
                type=MessageItemType.IMAGE,
                image_item=ImageItem(url="http://img"),
            ),
        ]
        msg = item_list_to_message(items)
        assert len(msg) == 2
        assert msg[0].type == "text"
        assert msg[1].type == "image"

    def test_empty_items(self) -> None:
        msg = item_list_to_message([])
        assert len(msg) == 0

    def test_ref_in_items(self) -> None:
        from nonebot.adapters.wxclaw.models import RefMessage

        items = [
            MessageItem(
                type=MessageItemType.TEXT,
                text_item=TextItem(text="reply"),
                ref_msg=RefMessage(title="original"),
            ),
        ]
        msg = item_list_to_message(items)
        # text + ref
        assert len(msg) == 2
        assert msg[0].type == "text"
        assert msg[1].type == "ref"
        assert msg[1].data["title"] == "original"
