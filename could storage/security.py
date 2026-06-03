"""Password hashing and password-based file encryption helpers."""

import base64
import hashlib
import hmac
import os
from pathlib import Path
from typing import BinaryIO

from werkzeug.security import check_password_hash, generate_password_hash

PBKDF2_ITERATIONS = 390_000
SALT_SIZE = 16
CHUNK_SIZE = 1024 * 1024
MAC_SIZE = 32


class InvalidToken(Exception):
    """Raised when an encrypted file cannot be authenticated/decrypted."""


def hash_password(password: str) -> str:
    """Return a strong one-way hash for login passwords."""
    return generate_password_hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Verify a plaintext password against a stored hash."""
    if not password_hash:
        return False
    return check_password_hash(password_hash, password)


def make_salt() -> str:
    """Create a base64 salt for per-file password based encryption."""
    return base64.urlsafe_b64encode(os.urandom(SALT_SIZE)).decode("ascii")


def _derive_keys(password: str, salt: str) -> tuple[bytes, bytes]:
    raw_salt = base64.urlsafe_b64decode(salt.encode("ascii"))
    key_material = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        raw_salt,
        PBKDF2_ITERATIONS,
        dklen=64,
    )
    return key_material[:32], key_material[32:]


def _xor_with_keystream(data: bytes, encryption_key: bytes, chunk_index: int) -> bytes:
    output = bytearray(len(data))
    offset = 0
    block_index = 0
    while offset < len(data):
        counter = chunk_index.to_bytes(8, "big") + block_index.to_bytes(8, "big")
        stream_block = hashlib.sha256(encryption_key + counter).digest()
        for value in stream_block:
            if offset >= len(data):
                break
            output[offset] = data[offset] ^ value
            offset += 1
        block_index += 1
    return bytes(output)


def encrypt_file(source: BinaryIO, destination: Path, password: str, salt: str) -> None:
    """Encrypt an uploaded file stream to disk with a password-derived key.

    Each encrypted chunk is authenticated with HMAC-SHA256. The password is
    never stored; losing it means the file cannot be decrypted.
    """
    encryption_key, mac_key = _derive_keys(password, salt)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as encrypted_file:
        chunk_index = 0
        while chunk := source.read(CHUNK_SIZE):
            encrypted_chunk = _xor_with_keystream(chunk, encryption_key, chunk_index)
            mac = hmac.new(
                mac_key,
                chunk_index.to_bytes(8, "big") + encrypted_chunk,
                hashlib.sha256,
            ).digest()
            encrypted_file.write(mac + encrypted_chunk)
            chunk_index += 1


def decrypt_file_to_bytes(path: str | Path, password: str, salt: str) -> bytes:
    """Decrypt an encrypted file and return bytes suitable for Flask send_file."""
    encryption_key, mac_key = _derive_keys(password, salt)
    output = bytearray()
    chunk_index = 0
    with Path(path).open("rb") as encrypted_file:
        while payload := encrypted_file.read(MAC_SIZE + CHUNK_SIZE):
            if len(payload) < MAC_SIZE:
                raise InvalidToken("Invalid encrypted payload")
            mac = payload[:MAC_SIZE]
            encrypted_chunk = payload[MAC_SIZE:]
            expected_mac = hmac.new(
                mac_key,
                chunk_index.to_bytes(8, "big") + encrypted_chunk,
                hashlib.sha256,
            ).digest()
            if not hmac.compare_digest(mac, expected_mac):
                raise InvalidToken("Wrong password or modified file")
            output.extend(_xor_with_keystream(encrypted_chunk, encryption_key, chunk_index))
            chunk_index += 1
    return bytes(output)


__all__ = [
    "InvalidToken",
    "decrypt_file_to_bytes",
    "encrypt_file",
    "hash_password",
    "make_salt",
    "verify_password",
]
