"""Redis-backed browser sessions kept separate from LangGraph checkpoints."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Protocol

from loguru import logger

SESSION_KEY_PREFIX = "animetta:auth:session:v1:"
SESSION_TOKEN_BYTES = 32
SESSION_VERSION = 1


class AuthSessionStoreUnavailableError(RuntimeError):
    """Raised when browser session state cannot be read or changed safely."""


@dataclass(frozen=True, slots=True)
class AuthSessionHealth:
    """Content-free readiness for the dedicated session client."""

    available: bool
    reason: str | None

    def public_dict(self) -> dict[str, object | None]:
        return {
            "state": "ready" if self.available else "failed",
            "ready": self.available,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class StoredSession:
    """Validated browser-session metadata."""

    session_id: str
    issued_at: int
    expires_at: int


class AuthSessionStore(Protocol):
    """Async session operations consumed by the security boundary."""

    @property
    def health(self) -> AuthSessionHealth: ...

    async def start(self) -> AuthSessionHealth: ...

    async def check_health(self) -> AuthSessionHealth: ...

    async def issue(self, *, now: int | None = None) -> tuple[str, StoredSession]: ...

    async def verify(self, token: str, *, now: int | None = None) -> StoredSession | None: ...

    async def revoke(self, token: str) -> None: ...

    async def close(self) -> None: ...


class RedisAuthSessionStore:
    """Own a Redis client used only for opaque, fixed-lifetime browser sessions."""

    def __init__(
        self,
        redis_url: str | None,
        *,
        ttl_seconds: int,
        client: Any | None = None,
    ) -> None:
        self.redis_url = redis_url
        self.ttl_seconds = ttl_seconds
        self._client = client
        self._owns_client = client is None
        self._health = AuthSessionHealth(False, "not_started")

    @property
    def health(self) -> AuthSessionHealth:
        return self._health

    async def start(self) -> AuthSessionHealth:
        if self._client is None:
            if not self.redis_url:
                self._health = AuthSessionHealth(False, "redis_url_missing")
                return self._health
            try:
                from redis.asyncio import Redis

                self._client = Redis.from_url(self.redis_url, decode_responses=False)
            except Exception as exc:
                self._mark_unavailable(exc, "create")
                return self._health
        return await self.check_health()

    async def check_health(self) -> AuthSessionHealth:
        if self._client is None:
            return await self.start()
        try:
            await self._client.ping()
            self._health = AuthSessionHealth(True, None)
        except Exception as exc:
            self._mark_unavailable(exc, "health")
        return self._health

    async def issue(self, *, now: int | None = None) -> tuple[str, StoredSession]:
        client = self._require_client()
        issued_at = int(time.time()) if now is None else now
        expires_at = issued_at + self.ttl_seconds
        value = json.dumps(
            {
                "version": SESSION_VERSION,
                "issued_at": issued_at,
                "expires_at": expires_at,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        for _ in range(3):
            token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
            session_id, key = _session_identity(token)
            try:
                stored = await client.set(key, value, ex=self.ttl_seconds, nx=True)
            except Exception as exc:
                self._raise_unavailable(exc, "issue")
            if stored:
                self._health = AuthSessionHealth(True, None)
                return token, StoredSession(session_id, issued_at, expires_at)
        raise AuthSessionStoreUnavailableError("session token allocation failed")

    async def verify(self, token: str, *, now: int | None = None) -> StoredSession | None:
        if not _is_valid_token(token):
            return None
        client = self._require_client()
        session_id, key = _session_identity(token)
        try:
            encoded = await client.get(key)
        except Exception as exc:
            self._raise_unavailable(exc, "verify")
        if encoded is None:
            self._health = AuthSessionHealth(True, None)
            return None
        try:
            data = json.loads(encoded)
            issued_at = int(data["issued_at"])
            expires_at = int(data["expires_at"])
            version = int(data["version"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        current = int(time.time()) if now is None else now
        if version != SESSION_VERSION or current >= expires_at or expires_at <= issued_at:
            return None
        self._health = AuthSessionHealth(True, None)
        return StoredSession(session_id, issued_at, expires_at)

    async def revoke(self, token: str) -> None:
        if not _is_valid_token(token):
            return
        client = self._require_client()
        _, key = _session_identity(token)
        try:
            await client.delete(key)
            self._health = AuthSessionHealth(True, None)
        except Exception as exc:
            self._raise_unavailable(exc, "revoke")

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None and self._owns_client:
            try:
                await client.aclose()
            except Exception as exc:
                self._mark_unavailable(exc, "close")
        self._health = AuthSessionHealth(False, "closed")

    def _require_client(self) -> Any:
        if self._client is None:
            raise AuthSessionStoreUnavailableError("session store is unavailable")
        return self._client

    def _raise_unavailable(self, exc: Exception, operation: str) -> None:
        self._mark_unavailable(exc, operation)
        raise AuthSessionStoreUnavailableError("session store is unavailable") from exc

    def _mark_unavailable(self, exc: Exception, operation: str) -> None:
        self._health = AuthSessionHealth(False, "auth_session_unavailable")
        logger.warning(
            "[AuthSession] Redis {} failed: error_type={}",
            operation,
            type(exc).__name__,
        )


def _session_identity(token: str) -> tuple[str, str]:
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    return digest[:24], f"{SESSION_KEY_PREFIX}{digest}"


def _is_valid_token(token: str) -> bool:
    return 40 <= len(token) <= 128 and all(
        character.isascii() and (character.isalnum() or character in "_-") for character in token
    )
