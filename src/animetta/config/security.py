"""Validated security settings for public runtime surfaces."""

from __future__ import annotations

from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SecurityConfig(BaseModel):
    """Non-secret security policy; machine and account secrets stay environment-only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed_origins: tuple[str, ...] = Field(min_length=1)
    access_token_env: str = Field(default="ANIMETTA_ACCESS_TOKEN", pattern=r"^[A-Z][A-Z0-9_]+$")
    account_username_env: str = Field(
        default="ANIMETTA_AUTH_USERNAME",
        pattern=r"^[A-Z][A-Z0-9_]+$",
    )
    account_password_hash_env: str = Field(
        default="ANIMETTA_AUTH_PASSWORD_HASH",
        pattern=r"^[A-Z][A-Z0-9_]+$",
    )
    session_hours: int = Field(default=8, ge=1, le=24)

    @field_validator("allowed_origins")
    @classmethod
    def validate_allowed_origins(cls, origins: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for origin in origins:
            if origin == "*":
                raise ValueError("wildcard origins are forbidden")
            parsed = urlsplit(origin)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError(f"invalid origin: {origin}")
            if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
                raise ValueError(f"origin must not contain a path, query, or fragment: {origin}")
            host = parsed.hostname.lower()
            is_loopback = host in {"localhost", "127.0.0.1", "::1"}
            if not is_loopback and parsed.scheme != "https":
                raise ValueError(f"non-loopback origin must use HTTPS: {origin}")
            canonical = origin.rstrip("/")
            if canonical in normalized:
                raise ValueError(f"duplicate origin: {canonical}")
            normalized.append(canonical)
        return tuple(normalized)
