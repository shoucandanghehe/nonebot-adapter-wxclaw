import os
from unittest.mock import AsyncMock

from nonebot.adapters.wxclaw.bot import Bot
from nonebot.adapters.wxclaw.cdn import (
    aes_ecb_decrypt,
    aes_ecb_encrypt,
    calculate_ciphertext_size,
    parse_aes_key,
)
from nonebot.adapters.wxclaw.config import Config, WxClawAccountInfo
from nonebot.adapters.wxclaw.exception import NetworkError

from nonebot.drivers import Response
import pytest


class TestAesEcb:
    def test_encrypt_decrypt_roundtrip(self) -> None:
        key = os.urandom(16)
        plaintext = b"hello world 1234"  # 16 bytes
        ciphertext = aes_ecb_encrypt(plaintext, key)
        assert ciphertext != plaintext
        decrypted = aes_ecb_decrypt(ciphertext, key)
        assert decrypted == plaintext

    def test_encrypt_decrypt_short(self) -> None:
        key = os.urandom(16)
        plaintext = b"hi"
        ciphertext = aes_ecb_encrypt(plaintext, key)
        decrypted = aes_ecb_decrypt(ciphertext, key)
        assert decrypted == plaintext

    def test_encrypt_decrypt_large(self) -> None:
        key = os.urandom(16)
        plaintext = os.urandom(1024)
        ciphertext = aes_ecb_encrypt(plaintext, key)
        decrypted = aes_ecb_decrypt(ciphertext, key)
        assert decrypted == plaintext

    def test_ciphertext_size_multiple_of_16(self) -> None:
        key = os.urandom(16)
        for size in [1, 15, 16, 17, 31, 32, 33, 100, 1000]:
            plaintext = os.urandom(size)
            ciphertext = aes_ecb_encrypt(plaintext, key)
            assert len(ciphertext) % 16 == 0


class TestCalculateCiphertextSize:
    def test_sizes(self) -> None:
        assert calculate_ciphertext_size(0) == 16
        assert calculate_ciphertext_size(1) == 16
        assert calculate_ciphertext_size(15) == 16
        assert calculate_ciphertext_size(16) == 32
        assert calculate_ciphertext_size(17) == 32
        assert calculate_ciphertext_size(31) == 32
        assert calculate_ciphertext_size(32) == 48

    def test_matches_actual_ciphertext(self) -> None:
        key = os.urandom(16)
        for size in [0, 1, 15, 16, 17, 31, 32, 100]:
            plaintext = os.urandom(size)
            actual = len(aes_ecb_encrypt(plaintext, key))
            expected = calculate_ciphertext_size(size)
            assert actual == expected, (
                f"size={size}: actual={actual}, expected={expected}"
            )


class TestParseAesKey:
    def test_raw_16_bytes(self) -> None:
        import base64

        raw_key = os.urandom(16)
        b64 = base64.b64encode(raw_key).decode()
        parsed = parse_aes_key(b64)
        assert parsed == raw_key

    def test_hex_encoded_key(self) -> None:
        import base64

        raw_key = os.urandom(16)
        hex_str = raw_key.hex()
        b64 = base64.b64encode(hex_str.encode()).decode()
        parsed = parse_aes_key(b64)
        assert parsed == raw_key

    def test_invalid_key_length(self) -> None:
        import base64

        invalid = base64.b64encode(b"short").decode()
        with pytest.raises(ValueError, match="aes_key must decode"):
            parse_aes_key(invalid)


@pytest.fixture
def bot() -> Bot:
    adapter = AsyncMock()
    adapter.adapter_config = Config()
    return Bot(adapter, "test", WxClawAccountInfo(account_id="test", token="tok"))


class TestUploadToCdn:
    @pytest.mark.asyncio
    async def test_success(self, bot: Bot) -> None:
        bot.adapter.request = AsyncMock(
            return_value=Response(200, headers={"x-encrypted-param": "enc_123"}),
        )
        result = await bot.upload_to_cdn(
            upload_url="https://cdn.example.com/upload",
            encrypted_data=b"encrypted",
        )
        assert result == "enc_123"

    @pytest.mark.asyncio
    async def test_client_error_no_retry(self, bot: Bot) -> None:
        bot.adapter.request = AsyncMock(return_value=Response(400))
        with pytest.raises(NetworkError, match="client error"):
            await bot.upload_to_cdn(
                upload_url="https://cdn.example.com/upload",
                encrypted_data=b"data",
                max_retries=1,
            )

    @pytest.mark.asyncio
    async def test_missing_param_header(self, bot: Bot) -> None:
        bot.adapter.request = AsyncMock(return_value=Response(200, headers={}))
        with pytest.raises(NetworkError, match="missing x-encrypted-param"):
            await bot.upload_to_cdn(
                upload_url="https://cdn.example.com/upload",
                encrypted_data=b"data",
                max_retries=1,
            )

    @pytest.mark.asyncio
    async def test_retry_on_server_error(self, bot: Bot) -> None:
        bot.adapter.request = AsyncMock(
            side_effect=[
                Response(500),
                Response(200, headers={"x-encrypted-param": "ok"}),
            ],
        )
        result = await bot.upload_to_cdn(
            upload_url="https://cdn.example.com/upload",
            encrypted_data=b"data",
            max_retries=2,
        )
        assert result == "ok"
        assert bot.adapter.request.call_count == 2


class TestDownloadFromCdn:
    @pytest.mark.asyncio
    async def test_download_and_decrypt(self, bot: Bot) -> None:
        import base64

        key = os.urandom(16)
        plaintext = b"hello world data"
        encrypted = aes_ecb_encrypt(plaintext, key)

        bot.adapter.request = AsyncMock(
            return_value=Response(200, content=encrypted),
        )
        result = await bot.download_from_cdn(
            url="https://cdn.example.com/file",
            aes_key_base64=base64.b64encode(key).decode(),
        )
        assert result == plaintext

    @pytest.mark.asyncio
    async def test_network_error(self, bot: Bot) -> None:
        bot.adapter.request = AsyncMock(side_effect=ConnectionError("timeout"))
        with pytest.raises(NetworkError, match="timeout"):
            await bot.download_from_cdn(
                url="https://cdn.example.com/file",
                aes_key_base64="dGVzdGtleXRlc3RrZXkx",
            )

    @pytest.mark.asyncio
    async def test_http_error(self, bot: Bot) -> None:
        bot.adapter.request = AsyncMock(return_value=Response(404))
        with pytest.raises(NetworkError, match="404"):
            await bot.download_from_cdn(
                url="https://cdn.example.com/file",
                aes_key_base64="dGVzdGtleXRlc3RrZXkx",
            )


class TestPrepareAndUploadFile:
    @pytest.mark.asyncio
    async def test_full_flow(self, bot: Bot) -> None:
        from nonebot.adapters.wxclaw.models import GetUploadUrlResponse, UploadMediaType

        bot.get_upload_url = AsyncMock(
            return_value=GetUploadUrlResponse(
                upload_param="param123",
                upload_full_url="https://cdn.example.com/upload?key=abc",
            ),
        )
        bot.upload_to_cdn = AsyncMock(return_value="download_param_xyz")

        result = await bot.prepare_and_upload_file(
            file_data=b"test file content",
            media_type=UploadMediaType.IMAGE,
            to_user_id="user1",
        )

        assert result.filekey
        assert result.download_encrypted_query_param == "download_param_xyz"
        assert result.aeskey
        assert result.file_size == len(b"test file content")
        assert result.file_md5
        bot.get_upload_url.assert_called_once()
        bot.upload_to_cdn.assert_called_once()
