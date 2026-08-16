"""Redis-backed local display pairing and fixed-lifetime credentials."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
import time
import unicodedata
import uuid
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, NoReturn, Protocol

from loguru import logger

PAIRING_KEY_PREFIX = "animetta:auth:display_pairing:v1:"
PAIRING_CODE_KEY_PREFIX = "animetta:auth:display_pairing_code:v1:"
CREDENTIAL_KEY_PREFIX = "animetta:auth:display_session:v1:"
CREDENTIAL_INDEX_KEY = "animetta:auth:display_sessions:v1"
ALLOCATION_LOCK_KEY = "animetta:auth:display_allocation_lock:v1"
PAIRING_TOKEN_BYTES = 32
CREDENTIAL_TOKEN_BYTES = 32
PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
PAIRING_CODE_LENGTH = 8


class AuthDisplayStoreUnavailableError(RuntimeError):
    """Raised when display authorization cannot fail closed through Redis."""


class DisplayPairingInvalidError(RuntimeError):
    """Raised when a pairing token or short code does not identify a request."""


class DisplayPairingExpiredError(RuntimeError):
    """Raised when a pairing request has expired."""


class DisplayCredentialLimitError(RuntimeError):
    """Raised when all configured display slots are occupied."""


@dataclass(frozen=True, slots=True)
class AuthDisplayHealth:
    available: bool
    reason: str | None

    def public_dict(self) -> dict[str, object | None]:
        return {
            "state": "ready" if self.available else "failed",
            "ready": self.available,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class PendingPairing:
    token: str
    code: str
    expires_at: int
    poll_interval_seconds: int


@dataclass(frozen=True, slots=True)
class DisplayCredential:
    id: str
    name: str
    approved_by_user_id: str
    bound_origin: str
    issued_at: int
    expires_at: int
    last_seen_at: int | None
    session_id: str

    def public_dict(self) -> dict[str, str | int | None]:
        return {
            "id": self.id,
            "name": self.name,
            "approved_by_user_id": self.approved_by_user_id,
            "bound_origin": self.bound_origin,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "last_seen_at": self.last_seen_at,
        }


class AuthDisplayStore(Protocol):
    @property
    def health(self) -> AuthDisplayHealth: ...

    async def start(self) -> AuthDisplayHealth: ...

    async def check_health(self) -> AuthDisplayHealth: ...

    async def create_pairing(self, *, origin: str, now: int | None = None) -> PendingPairing: ...

    async def approve_pairing(
        self,
        code: str,
        *,
        name: str,
        approved_by_user_id: str,
        now: int | None = None,
    ) -> dict[str, Any]: ...

    async def exchange_pairing(
        self,
        token: str,
        *,
        origin: str,
        now: int | None = None,
    ) -> tuple[str, DisplayCredential] | None: ...

    async def verify_credential(
        self,
        token: str,
        *,
        origin: str,
        now: int | None = None,
        touch: bool = False,
    ) -> DisplayCredential | None: ...

    async def list_credentials(self, *, now: int | None = None) -> list[DisplayCredential]: ...

    async def revoke_credential(self, device_id: str) -> bool: ...

    async def close(self) -> None: ...


class RedisAuthDisplayStore:
    """Own a Redis client used only for local browser-source authorization."""

    def __init__(
        self,
        redis_url: str | None,
        *,
        pairing_ttl_seconds: int,
        credential_ttl_seconds: int,
        poll_interval_seconds: int,
        max_active_credentials: int,
        client: Any | None = None,
        code_hmac_key: bytes | None = None,
    ) -> None:
        self.redis_url = redis_url
        self.pairing_ttl_seconds = pairing_ttl_seconds
        self.credential_ttl_seconds = credential_ttl_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.max_active_credentials = max_active_credentials
        self._client = client
        self._owns_client = client is None
        self._code_hmac_key = code_hmac_key or secrets.token_bytes(32)
        self._health = AuthDisplayHealth(False, "not_started")

    @property
    def health(self) -> AuthDisplayHealth:
        return self._health

    async def start(self) -> AuthDisplayHealth:
        if self._client is None:
            if not self.redis_url:
                self._health = AuthDisplayHealth(False, "redis_url_missing")
                return self._health
            try:
                from redis.asyncio import Redis

                self._client = Redis.from_url(self.redis_url, decode_responses=False)
            except Exception as exc:
                self._mark_unavailable(exc, "create")
                return self._health
        return await self.check_health()

    async def check_health(self) -> AuthDisplayHealth:
        if self._client is None:
            return await self.start()
        try:
            await self._client.ping()
            self._health = AuthDisplayHealth(True, None)
        except Exception as exc:
            self._mark_unavailable(exc, "health")
        return self._health

    async def create_pairing(self, *, origin: str, now: int | None = None) -> PendingPairing:
        client = self._require_client()
        issued_at = int(time.time()) if now is None else now
        expires_at = issued_at + self.pairing_ttl_seconds
        for _ in range(6):
            token = secrets.token_urlsafe(PAIRING_TOKEN_BYTES)
            code = "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(PAIRING_CODE_LENGTH))
            pairing_digest = _token_digest(token)
            code_digest = self._code_digest(code)
            value = _json(
                {
                    "approved_by_user_id": None,
                    "code_digest": code_digest,
                    "device_id": None,
                    "expires_at": expires_at,
                    "issued_at": issued_at,
                    "name": None,
                    "origin": origin,
                    "state": "pending",
                }
            )
            try:
                stored = await client.set(
                    f"{PAIRING_KEY_PREFIX}{pairing_digest}",
                    value,
                    ex=self.pairing_ttl_seconds,
                    nx=True,
                )
                if not stored:
                    continue
                code_stored = await client.set(
                    f"{PAIRING_CODE_KEY_PREFIX}{code_digest}",
                    pairing_digest,
                    ex=self.pairing_ttl_seconds,
                    nx=True,
                )
                if not code_stored:
                    await client.delete(f"{PAIRING_KEY_PREFIX}{pairing_digest}")
                    continue
                self._health = AuthDisplayHealth(True, None)
                return PendingPairing(
                    token, _display_code(code), expires_at, self.poll_interval_seconds
                )
            except Exception as exc:
                self._raise_unavailable(exc, "create_pairing")
        raise AuthDisplayStoreUnavailableError("pairing allocation failed")

    async def approve_pairing(
        self,
        code: str,
        *,
        name: str,
        approved_by_user_id: str,
        now: int | None = None,
    ) -> dict[str, Any]:
        client = self._require_client()
        normalized_code = _normalize_code(code)
        normalized_name = _normalize_name(name)
        current = int(time.time()) if now is None else now
        try:
            pairing_digest = await client.get(
                f"{PAIRING_CODE_KEY_PREFIX}{self._code_digest(normalized_code)}"
            )
            if pairing_digest is None:
                raise DisplayPairingInvalidError("DISPLAY_PAIRING_INVALID")
            pairing_digest = _decode(pairing_digest)
            key = f"{PAIRING_KEY_PREFIX}{pairing_digest}"
            data = _decode_json(await client.get(key))
            if data is None:
                raise DisplayPairingExpiredError("DISPLAY_PAIRING_EXPIRED")
            if int(data.get("expires_at") or 0) <= current:
                await client.delete(key)
                raise DisplayPairingExpiredError("DISPLAY_PAIRING_EXPIRED")
            if data.get("state") != "pending":
                raise DisplayPairingInvalidError("DISPLAY_PAIRING_INVALID")
            active = await self.list_credentials(now=current)
            if len(active) >= self.max_active_credentials:
                raise DisplayCredentialLimitError("DISPLAY_CREDENTIAL_LIMIT")
            ttl = max(1, int(data["expires_at"]) - current)
            data.update(
                {
                    "approved_by_user_id": approved_by_user_id,
                    "device_id": str(uuid.uuid4()),
                    "name": normalized_name,
                    "state": "approved",
                }
            )
            await client.set(key, _json(data), ex=ttl)
            self._health = AuthDisplayHealth(True, None)
            return data
        except (
            DisplayCredentialLimitError,
            DisplayPairingExpiredError,
            DisplayPairingInvalidError,
        ):
            raise
        except Exception as exc:
            self._raise_unavailable(exc, "approve_pairing")

    async def exchange_pairing(
        self,
        token: str,
        *,
        origin: str,
        now: int | None = None,
    ) -> tuple[str, DisplayCredential] | None:
        if not _valid_token(token):
            raise DisplayPairingInvalidError("DISPLAY_PAIRING_INVALID")
        client = self._require_client()
        current = int(time.time()) if now is None else now
        pairing_digest = _token_digest(token)
        pairing_key = f"{PAIRING_KEY_PREFIX}{pairing_digest}"
        allocation_locked = False
        try:
            data = _decode_json(await client.get(pairing_key))
            if data is None:
                raise DisplayPairingExpiredError("DISPLAY_PAIRING_EXPIRED")
            if int(data.get("expires_at") or 0) <= current:
                await client.delete(pairing_key)
                raise DisplayPairingExpiredError("DISPLAY_PAIRING_EXPIRED")
            if data.get("origin") != origin:
                raise DisplayPairingInvalidError("DISPLAY_PAIRING_INVALID")
            if data.get("state") == "pending":
                return None
            if data.get("state") != "approved":
                raise DisplayPairingInvalidError("DISPLAY_PAIRING_INVALID")
            for _ in range(3):
                allocation_locked = bool(await client.set(ALLOCATION_LOCK_KEY, "1", ex=5, nx=True))
                if allocation_locked:
                    break
                await asyncio.sleep(0.05)
            if not allocation_locked:
                raise AuthDisplayStoreUnavailableError("display allocation is busy")
            data = _decode_json(await client.get(pairing_key))
            if data is None or data.get("state") != "approved":
                raise DisplayPairingInvalidError("DISPLAY_PAIRING_INVALID")
            if len(await self.list_credentials(now=current)) >= self.max_active_credentials:
                raise DisplayCredentialLimitError("DISPLAY_CREDENTIAL_LIMIT")
            credential_token = secrets.token_urlsafe(CREDENTIAL_TOKEN_BYTES)
            credential_digest = _token_digest(credential_token)
            issued_at = current
            expires_at = issued_at + self.credential_ttl_seconds
            credential_data = {
                "approved_by_user_id": str(data["approved_by_user_id"]),
                "bound_origin": origin,
                "expires_at": expires_at,
                "id": str(data["device_id"]),
                "issued_at": issued_at,
                "last_seen_at": None,
                "name": str(data["name"]),
            }
            credential_key = f"{CREDENTIAL_KEY_PREFIX}{credential_digest}"
            stored = await client.set(
                credential_key,
                _json(credential_data),
                ex=self.credential_ttl_seconds,
                nx=True,
            )
            if not stored:
                raise AuthDisplayStoreUnavailableError("credential allocation failed")
            await client.sadd(CREDENTIAL_INDEX_KEY, credential_digest)
            await client.delete(pairing_key)
            await client.delete(f"{PAIRING_CODE_KEY_PREFIX}{data['code_digest']}")
            self._health = AuthDisplayHealth(True, None)
            return credential_token, _credential_from_data(
                credential_data,
                session_id=credential_digest[:24],
            )
        except (
            DisplayCredentialLimitError,
            DisplayPairingExpiredError,
            DisplayPairingInvalidError,
        ):
            raise
        except AuthDisplayStoreUnavailableError:
            raise
        except Exception as exc:
            self._raise_unavailable(exc, "exchange_pairing")
        finally:
            if allocation_locked:
                with suppress(Exception):
                    await client.delete(ALLOCATION_LOCK_KEY)

    async def verify_credential(
        self,
        token: str,
        *,
        origin: str,
        now: int | None = None,
        touch: bool = False,
    ) -> DisplayCredential | None:
        if not _valid_token(token):
            return None
        client = self._require_client()
        current = int(time.time()) if now is None else now
        digest = _token_digest(token)
        key = f"{CREDENTIAL_KEY_PREFIX}{digest}"
        try:
            data = _decode_json(await client.get(key))
            if data is None:
                return None
            if data.get("bound_origin") != origin or int(data.get("expires_at") or 0) <= current:
                return None
            if touch:
                data["last_seen_at"] = current
                ttl = max(1, int(data["expires_at"]) - current)
                await client.set(key, _json(data), ex=ttl)
            self._health = AuthDisplayHealth(True, None)
            return _credential_from_data(data, session_id=digest[:24])
        except Exception as exc:
            self._raise_unavailable(exc, "verify_credential")

    async def list_credentials(self, *, now: int | None = None) -> list[DisplayCredential]:
        client = self._require_client()
        current = int(time.time()) if now is None else now
        credentials: list[DisplayCredential] = []
        try:
            for raw_digest in await client.smembers(CREDENTIAL_INDEX_KEY):
                digest = _decode(raw_digest)
                data = _decode_json(await client.get(f"{CREDENTIAL_KEY_PREFIX}{digest}"))
                if data is None or int(data.get("expires_at") or 0) <= current:
                    await client.srem(CREDENTIAL_INDEX_KEY, digest)
                    continue
                credentials.append(_credential_from_data(data, session_id=digest[:24]))
            self._health = AuthDisplayHealth(True, None)
            return sorted(credentials, key=lambda item: item.issued_at, reverse=True)
        except Exception as exc:
            self._raise_unavailable(exc, "list_credentials")

    async def revoke_credential(self, device_id: str) -> bool:
        client = self._require_client()
        try:
            for raw_digest in await client.smembers(CREDENTIAL_INDEX_KEY):
                digest = _decode(raw_digest)
                key = f"{CREDENTIAL_KEY_PREFIX}{digest}"
                data = _decode_json(await client.get(key))
                if data is not None and data.get("id") == device_id:
                    await client.delete(key)
                    await client.srem(CREDENTIAL_INDEX_KEY, digest)
                    self._health = AuthDisplayHealth(True, None)
                    return True
            self._health = AuthDisplayHealth(True, None)
            return False
        except Exception as exc:
            self._raise_unavailable(exc, "revoke_credential")

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None and self._owns_client:
            with suppress(Exception):
                await client.aclose()
        self._health = AuthDisplayHealth(False, "closed")

    def _code_digest(self, code: str) -> str:
        normalized = _normalize_code(code)
        return hmac.new(self._code_hmac_key, normalized.encode("ascii"), hashlib.sha256).hexdigest()

    def _require_client(self) -> Any:
        if self._client is None:
            raise AuthDisplayStoreUnavailableError("display store is unavailable")
        return self._client

    def _raise_unavailable(self, exc: Exception, operation: str) -> NoReturn:
        self._mark_unavailable(exc, operation)
        raise AuthDisplayStoreUnavailableError("display store is unavailable") from exc

    def _mark_unavailable(self, exc: Exception, operation: str) -> None:
        self._health = AuthDisplayHealth(False, "auth_display_unavailable")
        logger.warning(
            "[AuthDisplay] Redis {} failed: error_type={}", operation, type(exc).__name__
        )


def _credential_from_data(data: dict[str, Any], *, session_id: str) -> DisplayCredential:
    return DisplayCredential(
        id=str(data["id"]),
        name=str(data["name"]),
        approved_by_user_id=str(data["approved_by_user_id"]),
        bound_origin=str(data["bound_origin"]),
        issued_at=int(data["issued_at"]),
        expires_at=int(data["expires_at"]),
        last_seen_at=int(data["last_seen_at"]) if data.get("last_seen_at") is not None else None,
        session_id=session_id,
    )


def _normalize_code(code: str) -> str:
    normalized = "".join(character for character in code.upper() if character not in " -")
    if len(normalized) != PAIRING_CODE_LENGTH or any(
        character not in PAIRING_ALPHABET for character in normalized
    ):
        raise DisplayPairingInvalidError("DISPLAY_PAIRING_INVALID")
    return normalized


def _normalize_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", name).strip()
    if not 1 <= len(normalized) <= 64 or any(
        unicodedata.category(char) == "Cc" for char in normalized
    ):
        raise ValueError("invalid display name")
    return normalized


def _display_code(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _valid_token(token: str) -> bool:
    return 40 <= len(token) <= 128 and all(
        character.isascii() and (character.isalnum() or character in "_-") for character in token
    )


def _decode(value: object) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _decode_json(value: object) -> dict[str, Any] | None:
    if not isinstance(value, (str, bytes, bytearray)):
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
