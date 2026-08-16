"""Redis-backed browser sessions kept separate from LangGraph checkpoints."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Protocol

from loguru import logger

SESSION_KEY_PREFIX = "animetta:auth:session:v2:"
USER_SESSION_KEY_PREFIX = "animetta:auth:user_sessions:v1:"
SESSION_TOKEN_BYTES = 32


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
    user_id: str
    credential_version: int
    issued_at: int
    expires_at: int


class AuthSessionStore(Protocol):
    """Async session operations consumed by the security boundary."""

    @property
    def health(self) -> AuthSessionHealth: ...

    async def start(self) -> AuthSessionHealth: ...

    async def check_health(self) -> AuthSessionHealth: ...

    async def issue(
        self,
        *,
        user_id: str,
        credential_version: int,
        now: int | None = None,
    ) -> tuple[str, StoredSession]: ...

    async def verify(self, token: str, *, now: int | None = None) -> StoredSession | None: ...

    async def revoke(self, token: str) -> None: ...

    async def revoke_user(self, user_id: str) -> None: ...

    async def count_user_sessions(
        self,
        user_versions: dict[str, int],
    ) -> dict[str, int]: ...

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

    async def issue(
        self,
        *,
        user_id: str,
        credential_version: int,
        now: int | None = None,
    ) -> tuple[str, StoredSession]:
        client = self._require_client()
        issued_at = int(time.time()) if now is None else now
        expires_at = issued_at + self.ttl_seconds
        value = json.dumps(
            {
                "credential_version": credential_version,
                "expires_at": expires_at,
                "issued_at": issued_at,
                "user_id": user_id,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        for _ in range(3):
            token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
            digest, session_id, key = _session_identity(token)
            index_key = _user_session_key(user_id)
            try:
                stored = await client.set(key, value, ex=self.ttl_seconds, nx=True)
                if not stored:
                    continue
                await client.sadd(index_key, digest)
                await client.expire(index_key, self.ttl_seconds)
            except Exception as exc:
                with suppress(Exception):
                    await client.delete(key)
                with suppress(Exception):
                    await client.srem(index_key, digest)
                self._raise_unavailable(exc, "issue")
            self._health = AuthSessionHealth(True, None)
            return token, StoredSession(
                session_id,
                user_id,
                credential_version,
                issued_at,
                expires_at,
            )
        raise AuthSessionStoreUnavailableError("session token allocation failed")

    async def verify(self, token: str, *, now: int | None = None) -> StoredSession | None:
        if not _is_valid_token(token):
            return None
        client = self._require_client()
        _, session_id, key = _session_identity(token)
        try:
            encoded = await client.get(key)
        except Exception as exc:
            self._raise_unavailable(exc, "verify")
        if encoded is None:
            self._health = AuthSessionHealth(True, None)
            return None
        current = int(time.time()) if now is None else now
        session = _decode_session(encoded, session_id=session_id, now=current)
        if session is None:
            return None
        self._health = AuthSessionHealth(True, None)
        return session

    async def revoke(self, token: str) -> None:
        if not _is_valid_token(token):
            return
        client = self._require_client()
        digest, _, key = _session_identity(token)
        try:
            encoded = await client.get(key)
            await client.delete(key)
            user_id = _stored_user_id(encoded)
            if user_id:
                await client.srem(_user_session_key(user_id), digest)
            self._health = AuthSessionHealth(True, None)
        except Exception as exc:
            self._raise_unavailable(exc, "revoke")

    async def revoke_user(self, user_id: str) -> None:
        client = self._require_client()
        index_key = _user_session_key(user_id)
        try:
            digests = await client.smembers(index_key)
            keys = [f"{SESSION_KEY_PREFIX}{_decode_digest(value)}" for value in digests]
            if keys:
                await client.delete(*keys)
            await client.delete(index_key)
            self._health = AuthSessionHealth(True, None)
        except Exception as exc:
            self._raise_unavailable(exc, "revoke_user")

    async def count_user_sessions(self, user_versions: dict[str, int]) -> dict[str, int]:
        client = self._require_client()
        try:
            counts: dict[str, int] = {}
            now = int(time.time())
            for user_id, credential_version in user_versions.items():
                index_key = _user_session_key(user_id)
                digests = await client.smembers(index_key)
                active = 0
                for value in digests:
                    digest = _decode_digest(value)
                    key = f"{SESSION_KEY_PREFIX}{digest}"
                    encoded = await client.get(key)
                    session = _decode_session(encoded, session_id=digest[:24], now=now)
                    if (
                        session is not None
                        and session.user_id == user_id
                        and session.credential_version == credential_version
                    ):
                        active += 1
                        continue
                    await client.delete(key)
                    await client.srem(index_key, digest)
                counts[user_id] = active
            self._health = AuthSessionHealth(True, None)
        except Exception as exc:
            self._raise_unavailable(exc, "count_user_sessions")
        return counts

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


def _session_identity(token: str) -> tuple[str, str, str]:
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    return digest, digest[:24], f"{SESSION_KEY_PREFIX}{digest}"


def _user_session_key(user_id: str) -> str:
    return f"{USER_SESSION_KEY_PREFIX}{user_id}"


def _stored_user_id(encoded: object) -> str | None:
    if not isinstance(encoded, (str, bytes, bytearray)):
        return None
    try:
        value = json.loads(encoded)
        user_id = str(value["user_id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return user_id or None


def _decode_session(encoded: object, *, session_id: str, now: int) -> StoredSession | None:
    if not isinstance(encoded, (str, bytes, bytearray)):
        return None
    try:
        data = json.loads(encoded)
        user_id = str(data["user_id"])
        credential_version = int(data["credential_version"])
        issued_at = int(data["issued_at"])
        expires_at = int(data["expires_at"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not user_id or credential_version < 1 or now >= expires_at or expires_at <= issued_at:
        return None
    return StoredSession(
        session_id,
        user_id,
        credential_version,
        issued_at,
        expires_at,
    )


def _decode_digest(value: object) -> str:
    return value.decode("ascii") if isinstance(value, bytes) else str(value)


def _is_valid_token(token: str) -> bool:
    return 40 <= len(token) <= 128 and all(
        character.isascii() and (character.isalnum() or character in "_-") for character in token
    )
