from __future__ import annotations

import json
import time

import pytest

from animetta.orchestration.server.auth_session import (
    SESSION_KEY_PREFIX,
    USER_SESSION_KEY_PREFIX,
    AuthSessionStoreUnavailableError,
    RedisAuthSessionStore,
)


class RecordingRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}
        self.set_calls: list[tuple[str, str, dict[str, object]]] = []
        self.expire_calls: list[tuple[str, int]] = []
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

    async def delete(self, *keys: str) -> int:
        self._check()
        deleted = 0
        for key in keys:
            deleted += int(self.values.pop(key, None) is not None)
            deleted += int(self.sets.pop(key, None) is not None)
        return deleted

    async def sadd(self, key: str, value: str) -> int:
        self._check()
        before = len(self.sets.setdefault(key, set()))
        self.sets[key].add(value)
        return int(len(self.sets[key]) > before)

    async def expire(self, key: str, seconds: int) -> bool:
        self._check()
        self.expire_calls.append((key, seconds))
        return key in self.sets

    async def srem(self, key: str, value: str) -> int:
        self._check()
        members = self.sets.setdefault(key, set())
        before = len(members)
        members.discard(value)
        return int(len(members) < before)

    async def smembers(self, key: str) -> set[str]:
        self._check()
        return set(self.sets.get(key, set()))

    async def scard(self, key: str) -> int:
        self._check()
        return len(self.sets.get(key, set()))

    async def aclose(self) -> None:
        self.closed = True

    def _check(self) -> None:
        if self.unavailable:
            raise ConnectionError("redis unavailable")


@pytest.mark.asyncio
async def test_opaque_session_uses_digest_key_metadata_and_fixed_ttl() -> None:
    redis = RecordingRedis()
    store = RedisAuthSessionStore(None, ttl_seconds=8 * 3600, client=redis)

    token, session = await store.issue(user_id="user-1", credential_version=3, now=1_000)

    assert len(token) >= 40
    assert session.issued_at == 1_000
    assert session.expires_at == 29_800
    assert session.user_id == "user-1"
    assert session.credential_version == 3
    assert len(redis.set_calls) == 1
    key, value, options = redis.set_calls[0]
    assert key.startswith(SESSION_KEY_PREFIX)
    assert token not in key
    assert token not in value
    assert options == {"ex": 28_800, "nx": True}
    assert json.loads(value) == {
        "expires_at": 29_800,
        "credential_version": 3,
        "issued_at": 1_000,
        "user_id": "user-1",
    }
    index_key = f"{USER_SESSION_KEY_PREFIX}user-1"
    assert redis.sets[index_key] == {key.removeprefix(SESSION_KEY_PREFIX)}
    assert redis.expire_calls == [(index_key, 28_800)]
    assert await store.verify(token, now=29_799) == session
    assert redis.expire_calls == [(index_key, 28_800)]
    assert await store.verify(token, now=29_800) is None


@pytest.mark.asyncio
async def test_multiple_sessions_are_independent_and_logout_revokes_one() -> None:
    redis = RecordingRedis()
    store = RedisAuthSessionStore(None, ttl_seconds=8 * 3600, client=redis)
    now = int(time.time())
    first_token, first_session = await store.issue(user_id="user-1", credential_version=1, now=now)
    second_token, second_session = await store.issue(
        user_id="user-1", credential_version=1, now=now + 1
    )

    assert first_token != second_token
    assert first_session.session_id != second_session.session_id
    await store.revoke(first_token)
    assert await store.verify(first_token, now=now + 2) is None
    assert await store.verify(second_token, now=now + 2) == second_session
    assert await store.count_user_sessions({"user-1": 1}) == {"user-1": 1}
    await store.revoke_user("user-1")
    assert await store.verify(second_token, now=now + 2) is None


@pytest.mark.asyncio
async def test_session_count_removes_expired_and_stale_credential_entries() -> None:
    redis = RecordingRedis()
    store = RedisAuthSessionStore(None, ttl_seconds=8 * 3600, client=redis)
    token, _ = await store.issue(user_id="user-1", credential_version=1)

    assert await store.count_user_sessions({"user-1": 2}) == {"user-1": 0}
    assert await store.verify(token) is None
    assert redis.sets[f"{USER_SESSION_KEY_PREFIX}user-1"] == set()


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
        await store.issue(user_id="user-1", credential_version=1)
    assert (await store.check_health()).available is False
    assert store.health.reason == "auth_session_unavailable"
