from __future__ import annotations

import json

import pytest

from animetta.orchestration.server.auth_session import (
    SESSION_KEY_PREFIX,
    AuthSessionStoreUnavailableError,
    RedisAuthSessionStore,
)


class RecordingRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, dict[str, object]]] = []
        self.unavailable = False
        self.closed = False

    async def ping(self) -> bool:
        self._check()
        return True

    async def set(self, key: str, value: str, **kwargs) -> bool:
        self._check()
        self.set_calls.append((key, value, kwargs))
        if kwargs.get("nx") and key in self.values:
            return False
        self.values[key] = value
        return True

    async def get(self, key: str) -> str | None:
        self._check()
        return self.values.get(key)

    async def delete(self, key: str) -> int:
        self._check()
        return int(self.values.pop(key, None) is not None)

    async def aclose(self) -> None:
        self.closed = True

    def _check(self) -> None:
        if self.unavailable:
            raise ConnectionError("redis unavailable")


@pytest.mark.asyncio
async def test_opaque_session_uses_digest_key_metadata_and_fixed_ttl() -> None:
    redis = RecordingRedis()
    store = RedisAuthSessionStore(None, ttl_seconds=8 * 3600, client=redis)

    token, session = await store.issue(now=1_000)

    assert len(token) >= 40
    assert session.issued_at == 1_000
    assert session.expires_at == 29_800
    assert len(redis.set_calls) == 1
    key, value, options = redis.set_calls[0]
    assert key.startswith(SESSION_KEY_PREFIX)
    assert token not in key
    assert token not in value
    assert options == {"ex": 28_800, "nx": True}
    assert json.loads(value) == {
        "expires_at": 29_800,
        "issued_at": 1_000,
        "version": 1,
    }
    assert await store.verify(token, now=29_799) == session
    assert await store.verify(token, now=29_800) is None


@pytest.mark.asyncio
async def test_multiple_sessions_are_independent_and_logout_revokes_one() -> None:
    redis = RecordingRedis()
    store = RedisAuthSessionStore(None, ttl_seconds=8 * 3600, client=redis)
    first_token, first_session = await store.issue(now=1_000)
    second_token, second_session = await store.issue(now=1_001)

    assert first_token != second_token
    assert first_session.session_id != second_session.session_id
    await store.revoke(first_token)
    assert await store.verify(first_token, now=1_002) is None
    assert await store.verify(second_token, now=1_002) == second_session


@pytest.mark.asyncio
async def test_legacy_cookie_is_rejected_without_redis_lookup() -> None:
    redis = RecordingRedis()
    redis.unavailable = True
    store = RedisAuthSessionStore(None, ttl_seconds=8 * 3600, client=redis)

    assert await store.verify("legacy.payload.signature") is None


@pytest.mark.asyncio
async def test_redis_failures_are_reported_as_session_store_unavailable() -> None:
    redis = RecordingRedis()
    store = RedisAuthSessionStore(None, ttl_seconds=8 * 3600, client=redis)
    assert (await store.start()).available is True
    redis.unavailable = True

    with pytest.raises(AuthSessionStoreUnavailableError):
        await store.issue()
    assert (await store.check_health()).available is False
    assert store.health.reason == "auth_session_unavailable"
