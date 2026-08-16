"""Password hashing and validation shared by browser authentication flows."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

PASSWORD_HASH_SCHEME = "scrypt-v1"
PASSWORD_SALT_BYTES = 16
PASSWORD_DIGEST_BYTES = 32
PASSWORD_MIN_BYTES = 8
PASSWORD_MAX_BYTES = 1024
PASSWORD_SCRYPT_N = 2**14
PASSWORD_SCRYPT_R = 8
PASSWORD_SCRYPT_P = 1


def validate_password(password: str) -> None:
    """Reject passwords outside the documented byte-length policy."""
    password_bytes = password.encode("utf-8")
    if not PASSWORD_MIN_BYTES <= len(password_bytes) <= PASSWORD_MAX_BYTES:
        raise ValueError(
            f"password must contain between {PASSWORD_MIN_BYTES} and {PASSWORD_MAX_BYTES} bytes"
        )


def hash_password(password: str) -> str:
    """Return a randomly salted, environment-safe password hash."""
    validate_password(password)
    password_bytes = password.encode("utf-8")
    salt = secrets.token_bytes(PASSWORD_SALT_BYTES)
    digest = _derive_password(password_bytes, salt)
    return f"{PASSWORD_HASH_SCHEME}:{_b64url(salt)}:{_b64url(digest)}"


def verify_password(password: str, password_hash: str) -> bool:
    """Compare a supplied password with a stored scrypt hash in constant time."""
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > PASSWORD_MAX_BYTES:
        return False
    try:
        salt, expected = parse_password_hash(password_hash)
    except ValueError:
        return False
    supplied = _derive_password(password_bytes, salt)
    return hmac.compare_digest(supplied, expected)


def parse_password_hash(value: str) -> tuple[bytes, bytes]:
    """Validate and decode the supported password-hash representation."""
    try:
        scheme, salt_value, digest_value = value.split(":", maxsplit=2)
        salt = _b64url_decode(salt_value)
        digest = _b64url_decode(digest_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid password hash") from exc
    if (
        scheme != PASSWORD_HASH_SCHEME
        or len(salt) != PASSWORD_SALT_BYTES
        or len(digest) != PASSWORD_DIGEST_BYTES
    ):
        raise ValueError("invalid password hash")
    return salt, digest


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _derive_password(password: bytes, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password,
        salt=salt,
        n=PASSWORD_SCRYPT_N,
        r=PASSWORD_SCRYPT_R,
        p=PASSWORD_SCRYPT_P,
        dklen=PASSWORD_DIGEST_BYTES,
    )
