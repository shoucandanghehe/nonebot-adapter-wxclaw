from nonebot.adapters.wxclaw.event import (
    FileMessageEvent,
    ImageMessageEvent,
    TextMessageEvent,
    VideoMessageEvent,
    VoiceMessageEvent,
    parse_event,
)
from nonebot.adapters.wxclaw.message import Message, MessageSegment
from nonebot.adapters.wxclaw.models import (
    FileItem,
    ImageItem,
    MessageItem,
    MessageItemType,
    MessageType,
    TextItem,
    VideoItem,
    VoiceItem,
    WeixinMessage,
)


class TestEvent:
    def test_text_message_event(self) -> None:
        event = TextMessageEvent(
            message_id=1,
            from_user_id="user1",
            to_user_id="bot1",
            session_id="session1",
            create_time_ms=1000,
            context_token="ctx1",
            message=Message([MessageSegment.text("hello")]),
        )
        assert event.get_type() == "message"
        assert event.get_event_name() == "message.text"
        assert event.get_user_id() == "user1"
        assert event.get_session_id() == "session1"
        assert event.is_tome()
        assert event.get_message() == Message([MessageSegment.text("hello")])
        assert event.get_plaintext() == "hello"

    def test_image_message_event(self) -> None:
        event = ImageMessageEvent(
            from_user_id="user1",
            to_user_id="bot1",
            session_id="session1",
            message=Message([MessageSegment.image()]),
            image_item=ImageItem(url="http://img"),
        )
        assert event.get_event_name() == "message.image"
        assert event.image_item is not None
        assert event.image_item.url == "http://img"

    def test_voice_message_event(self) -> None:
        event = VoiceMessageEvent(
            from_user_id="user1",
            to_user_id="bot1",
            session_id="session1",
            message=Message([MessageSegment("voice", {"text": "hello"})]),
            voice_item=VoiceItem(text="hello"),
        )
        assert event.get_event_name() == "message.voice"

    def test_file_message_event(self) -> None:
        event = FileMessageEvent(
            from_user_id="user1",
            to_user_id="bot1",
            session_id="session1",
            message=Message([MessageSegment.file(file_name="doc.pdf")]),
            file_item=FileItem(file_name="doc.pdf"),
        )
        assert event.get_event_name() == "message.file"

    def test_video_message_event(self) -> None:
        event = VideoMessageEvent(
            from_user_id="user1",
            to_user_id="bot1",
            session_id="session1",
            message=Message([MessageSegment.video()]),
            video_item=VideoItem(video_size=1024),
        )
        assert event.get_event_name() == "message.video"

    def test_event_description(self) -> None:
        event = TextMessageEvent(
            message_id=42,
            from_user_id="user1",
            to_user_id="bot1",
            session_id="session1",
            message=Message([MessageSegment.text("test")]),
        )
        desc = event.get_event_description()
        assert "42" in desc
        assert "user1" in desc


class TestParseEvent:
    def test_parse_text_event(self) -> None:
        msg = WeixinMessage(
            message_id=1,
            from_user_id="user1",
            to_user_id="bot1",
            session_id="session1",
            message_type=MessageType.USER,
            create_time_ms=1000,
            context_token="ctx",
            item_list=[
                MessageItem(
                    type=MessageItemType.TEXT,
                    text_item=TextItem(text="hello"),
                )
            ],
        )
        event = parse_event(msg)
        assert isinstance(event, TextMessageEvent)
        assert event.get_user_id() == "user1"
        assert event.get_plaintext() == "hello"
        assert event.context_token == "ctx"

    def test_parse_image_event(self) -> None:
        msg = WeixinMessage(
            message_id=2,
            from_user_id="user1",
            to_user_id="bot1",
            session_id="session1",
            message_type=MessageType.USER,
            item_list=[
                MessageItem(
                    type=MessageItemType.IMAGE,
                    image_item=ImageItem(url="http://img"),
                )
            ],
        )
        event = parse_event(msg)
        assert isinstance(event, ImageMessageEvent)
        assert event.image_item is not None

    def test_parse_voice_event(self) -> None:
        msg = WeixinMessage(
            message_id=3,
            from_user_id="user1",
            to_user_id="bot1",
            session_id="session1",
            item_list=[
                MessageItem(
                    type=MessageItemType.VOICE,
                    voice_item=VoiceItem(text="voice text"),
                )
            ],
        )
        event = parse_event(msg)
        assert isinstance(event, VoiceMessageEvent)

    def test_parse_file_event(self) -> None:
        msg = WeixinMessage(
            message_id=4,
            from_user_id="user1",
            to_user_id="bot1",
            session_id="session1",
            item_list=[
                MessageItem(
                    type=MessageItemType.FILE,
                    file_item=FileItem(file_name="test.pdf"),
                )
            ],
        )
        event = parse_event(msg)
        assert isinstance(event, FileMessageEvent)

    def test_parse_video_event(self) -> None:
        msg = WeixinMessage(
            message_id=5,
            from_user_id="user1",
            to_user_id="bot1",
            session_id="session1",
            item_list=[
                MessageItem(
                    type=MessageItemType.VIDEO,
                    video_item=VideoItem(video_size=1024),
                )
            ],
        )
        event = parse_event(msg)
        assert isinstance(event, VideoMessageEvent)

    def test_parse_empty_items(self) -> None:
        msg = WeixinMessage(
            message_id=6,
            from_user_id="user1",
            to_user_id="bot1",
            session_id="session1",
            item_list=[],
        )
        event = parse_event(msg)
        assert isinstance(event, TextMessageEvent)

    def test_parse_mixed_prefers_media(self) -> None:
        msg = WeixinMessage(
            message_id=7,
            from_user_id="user1",
            to_user_id="bot1",
            session_id="session1",
            item_list=[
                MessageItem(
                    type=MessageItemType.TEXT,
                    text_item=TextItem(text="caption"),
                ),
                MessageItem(
                    type=MessageItemType.IMAGE,
                    image_item=ImageItem(url="http://img"),
                ),
            ],
        )
        event = parse_event(msg)
        assert isinstance(event, ImageMessageEvent)
        assert len(event.message) == 2
