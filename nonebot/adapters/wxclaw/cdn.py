import base64

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7


def aes_ecb_encrypt(plaintext: bytes, key: bytes) -> bytes:
    padder = PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.ECB())  # noqa: S305
    encryptor = cipher.encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def aes_ecb_decrypt(ciphertext: bytes, key: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.ECB())  # noqa: S305
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def calculate_ciphertext_size(plaintext_size: int) -> int:
    return ((plaintext_size // 16) + 1) * 16


def parse_aes_key(aes_key_base64: str) -> bytes:
    decoded = base64.b64decode(aes_key_base64)
    if len(decoded) == 16:
        return decoded
    if len(decoded) == 32:
        try:
            ascii_str = decoded.decode("ascii")
            if all(c in "0123456789abcdefABCDEF" for c in ascii_str):
                return bytes.fromhex(ascii_str)
        except (UnicodeDecodeError, ValueError):
            pass
    msg = (
        f"aes_key must decode to 16 raw bytes or 32-char hex string,"
        f" got {len(decoded)} bytes"
    )
    raise ValueError(msg)
