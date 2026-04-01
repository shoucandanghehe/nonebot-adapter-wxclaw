from nonebot.adapters.wxclaw.models import (
    CDNMedia,
    FileItem,
    GetUpdatesResponse,
    ImageItem,
    MessageItem,
    MessageItemType,
    MessageState,
    MessageType,
    QRCodeResponse,
    QRStatusResponse,
    RefMessage,
    SendMessageRequest,
    TextItem,
    TypingStatus,
    UploadMediaType,
    VideoItem,
    VoiceItem,
    WeixinMessage,
)

from nonebot.compat import model_dump, type_validate_python


class TestEnums:
    def test_message_item_type(self) -> None:
        assert MessageItemType.TEXT == 1
        assert MessageItemType.VIDEO == 5

    def test_message_type(self) -> None:
        assert MessageType.USER == 1
        assert MessageType.BOT == 2

    def test_message_state(self) -> None:
        assert MessageState.FINISH == 2

    def test_typing_status(self) -> None:
        assert TypingStatus.TYPING == 1
        assert TypingStatus.CANCEL == 2

    def test_upload_media_type(self) -> None:
        assert UploadMediaType.IMAGE == 1
        assert UploadMediaType.FILE == 3


class TestModels:
    def test_cdn_media(self) -> None:
        media = CDNMedia(
            encrypt_query_param="param1",
            aes_key="key1",
            encrypt_type=0,
            full_url="https://cdn/file",
        )
        assert media.aes_key == "key1"
        d = model_dump(media)
        assert d["full_url"] == "https://cdn/file"

    def test_text_item(self) -> None:
        item = TextItem(text="hello")
        assert item.text == "hello"

    def test_image_item(self) -> None:
        media = CDNMedia(aes_key="k")
        item = ImageItem(media=media, url="http://img", hd_size=1024)
        assert item.hd_size == 1024

    def test_voice_item(self) -> None:
        item = VoiceItem(playtime=3000, text="transcribed")
        assert item.playtime == 3000

    def test_file_item(self) -> None:
        item = FileItem(file_name="doc.pdf", md5="abc")
        assert item.file_name == "doc.pdf"

    def test_video_item(self) -> None:
        item = VideoItem(video_size=2048, play_length=60)
        assert item.play_length == 60

    def test_message_item_with_ref(self) -> None:
        ref = RefMessage(
            title="original",
            message_item=MessageItem(
                type=MessageItemType.TEXT,
                text_item=TextItem(text="quoted"),
            ),
        )
        item = MessageItem(
            type=MessageItemType.TEXT,
            text_item=TextItem(text="reply"),
            ref_msg=ref,
        )
        assert item.ref_msg is not None
        assert item.ref_msg.title == "original"

    def test_weixin_message(self) -> None:
        msg = WeixinMessage(
            message_id=42,
            from_user_id="user1",
            to_user_id="bot1",
            session_id="session1",
            message_type=MessageType.USER,
            message_state=MessageState.FINISH,
            context_token="ctx",
            item_list=[
                MessageItem(
                    type=MessageItemType.TEXT,
                    text_item=TextItem(text="hi"),
                )
            ],
        )
        assert msg.message_id == 42
        assert msg.context_token == "ctx"


class TestResponseModels:
    def test_get_updates_response_parse(self) -> None:
        data = {
            "ret": 0,
            "msgs": [
                {
                    "message_id": 1,
                    "from_user_id": "u1",
                    "to_user_id": "b1",
                    "session_id": "s1",
                    "message_type": 1,
                    "item_list": [{"type": 1, "text_item": {"text": "hello"}}],
                    "context_token": "ct",
                }
            ],
            "get_updates_buf": "buf123",
        }
        resp = type_validate_python(GetUpdatesResponse, data)
        assert resp.ret == 0
        assert resp.msgs is not None
        assert len(resp.msgs) == 1
        assert resp.msgs[0].from_user_id == "u1"
        assert resp.get_updates_buf == "buf123"

    def test_get_updates_response_empty(self) -> None:
        resp = type_validate_python(GetUpdatesResponse, {"ret": 0, "msgs": []})
        assert resp.msgs == []

    def test_send_message_request(self) -> None:
        msg = WeixinMessage(
            to_user_id="user1",
            message_type=MessageType.BOT,
            item_list=[
                MessageItem(
                    type=MessageItemType.TEXT,
                    text_item=TextItem(text="response"),
                )
            ],
        )
        req = SendMessageRequest(msg=msg)
        d = model_dump(req)
        assert d["msg"]["to_user_id"] == "user1"

    def test_qr_code_response(self) -> None:
        resp = type_validate_python(
            QRCodeResponse,
            {"qrcode": "qr123", "qrcode_img_content": "https://qr/img"},
        )
        assert resp.qrcode == "qr123"

    def test_qr_status_response_confirmed(self) -> None:
        resp = type_validate_python(
            QRStatusResponse,
            {
                "status": "confirmed",
                "bot_token": "token123",
                "ilink_bot_id": "bot1",
                "baseurl": "https://api.weixin.qq.com",
                "ilink_user_id": "user1",
            },
        )
        assert resp.status == "confirmed"
        assert resp.bot_token == "token123"
        assert resp.ilink_bot_id == "bot1"

    def test_qr_status_response_wait(self) -> None:
        resp = type_validate_python(QRStatusResponse, {"status": "wait"})
        assert resp.status == "wait"
        assert resp.bot_token is None
