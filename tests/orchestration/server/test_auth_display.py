from __future__ import annotations

import json
import re

import pytest

from animetta.orchestration.server.auth_display import (
    CREDENTIAL_INDEX_KEY,
    CREDENTIAL_KEY_PREFIX,
    PAIRING_CODE_KEY_PREFIX,
    PAIRING_KEY_PREFIX,
    AuthDisplayStoreUnavailableError,
    DisplayCredentialLimitError,
    DisplayPairingExpiredError,
    RedisAuthDisplayStore,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}
        self.ttls: dict[str, int] = {}
        self.unavailable = False

    async def ping(self) -> bool:
        self._check()
        return True

    async def set(self, key: str, value: str, *, ex: int, nx: bool = False) -> bool:
        self._check()
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.ttls[key] = ex
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
            self.ttls.pop(key, None)
        return deleted

    async def sadd(self, key: str, value: str) -> int:
        self._check()
        before = len(self.sets.setdefault(key, set()))
        self.sets[key].add(value)
        return int(len(self.sets[key]) > before)

    async def srem(self, key: str, value: str) -> int:
        self._check()
        before = len(self.sets.setdefault(key, set()))
        self.sets[key].discard(value)
        return int(len(self.sets[key]) < before)

    async def smembers(self, key: str) -> set[str]:
        self._check()
        return set(self.sets.get(key, set()))

    def _check(self) -> None:
        if self.unavailable:
            raise ConnectionError("redis unavailable")


def _store(redis: FakeRedis, *, maximum: int = 5) -> RedisAuthDisplayStore:
    return RedisAuthDisplayStore(
        None,
        pairing_ttl_seconds=300,
        credential_ttl_seconds=30 * 86400,
        poll_interval_seconds=3,
        max_active_credentials=maximum,
        client=redis,
        code_hmac_key=b"display-test-key" * 2,
    )


@pytest.mark.asyncio
async def test_pairing_uses_safe_short_code_digests_and_five_minute_ttl() -> None:
    redis = FakeRedis()
    store = _store(redis)

    first = await store.create_pairing(origin="http://127.0.0.1", now=1_000)
    second = await store.create_pairing(origin="http://127.0.0.1", now=1_000)

    assert re.fullmatch(r"[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}", first.code)
    assert first.code != second.code
    assert first.expires_at == 1_300
    assert first.poll_interval_seconds == 3
    assert all(redis.ttls[key] == 300 for key in redis.values)
    serialized = json.dumps(redis.values, sort_keys=True)
    assert first.token not in serialized
    assert first.code.replace("-", "") not in serialized
    assert all(
        re.fullmatch(r"[0-9a-f]{64}", key.rsplit(":", 1)[-1])
        for key in redis.values
        if key.startswith((PAIRING_KEY_PREFIX, PAIRING_CODE_KEY_PREFIX))
    )


@pytest.mark.asyncio
async def test_approved_pairing_exchanges_once_for_fixed_non_sliding_credential() -> None:
    redis = FakeRedis()
    store = _store(redis)
    pairing = await store.create_pairing(origin="http://127.0.0.1", now=1_000)
    await store.approve_pairing(
        pairing.code,
        name="B站直播场景",
        approved_by_user_id="admin-id",
        now=1_010,
    )

    exchanged = await store.exchange_pairing(
        pairing.token,
        origin="http://127.0.0.1",
        now=1_020,
    )

    assert exchanged is not None
    token, credential = exchanged
    assert credential.name == "B站直播场景"
    assert credential.expires_at == 1_020 + 30 * 86400
    digest = next(iter(redis.sets[CREDENTIAL_INDEX_KEY]))
    key = f"{CREDENTIAL_KEY_PREFIX}{digest}"
    assert redis.ttls[key] == 30 * 86400
    assert token not in json.dumps(redis.values, ensure_ascii=False)
    assert re.fullmatch(r"[0-9a-f]{64}", digest)

    verified = await store.verify_credential(
        token,
        origin="http://127.0.0.1",
        now=1_120,
        touch=True,
    )
    assert verified is not None
    assert verified.last_seen_at == 1_120
    assert verified.expires_at == credential.expires_at
    assert redis.ttls[key] == credential.expires_at - 1_120
    assert await store.verify_credential(token, origin="http://localhost", now=1_120) is None
    with pytest.raises(DisplayPairingExpiredError):
        await store.exchange_pairing(
            pairing.token,
            origin="http://127.0.0.1",
            now=1_021,
        )


@pytest.mark.asyncio
async def test_credential_limit_requires_explicit_revoke() -> None:
    redis = FakeRedis()
    store = _store(redis, maximum=1)

    first = await store.create_pairing(origin="http://127.0.0.1", now=1_000)
    await store.approve_pairing(
        first.code,
        name="first",
        approved_by_user_id="admin-id",
        now=1_001,
    )
    exchanged = await store.exchange_pairing(
        first.token,
        origin="http://127.0.0.1",
        now=1_002,
    )
    assert exchanged is not None

    second = await store.create_pairing(origin="http://127.0.0.1", now=1_003)
    with pytest.raises(DisplayCredentialLimitError):
        await store.approve_pairing(
            second.code,
            name="second",
            approved_by_user_id="admin-id",
            now=1_004,
        )

    assert await store.revoke_credential(exchanged[1].id) is True
    await store.approve_pairing(
        second.code,
        name="second",
        approved_by_user_id="admin-id",
        now=1_005,
    )


@pytest.mark.asyncio
async def test_redis_failure_closes_display_authorization() -> None:
    redis = FakeRedis()
    store = _store(redis)
    assert (await store.start()).available is True
    redis.unavailable = True

    with pytest.raises(AuthDisplayStoreUnavailableError):
        await store.create_pairing(origin="http://127.0.0.1")

    assert store.health.available is False
    assert store.health.reason == "auth_display_unavailable"
