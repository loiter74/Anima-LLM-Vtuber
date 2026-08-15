from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from animetta.core.redis_checkpoint import RedisCheckpointRuntime


class _SaverContext:
    def __init__(self, saver, *, error: Exception | None = None) -> None:
        self.saver = saver
        self.error = error
        self.closed = False

    async def __aenter__(self):
        if self.error is not None:
            raise self.error
        await self.saver.asetup()
        return self.saver

    async def __aexit__(self, *_args) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_runtime_owns_official_saver_setup_ttl_and_close() -> None:
    saver = MagicMock()
    saver.asetup = AsyncMock()
    saver._redis.ping = AsyncMock(return_value=True)
    context = _SaverContext(saver)
    saver_type = MagicMock()
    saver_type.from_conn_string.return_value = context
    module = ModuleType("langgraph.checkpoint.redis.aio")
    module.AsyncRedisSaver = saver_type

    with patch.dict(sys.modules, {"langgraph.checkpoint.redis.aio": module}):
        runtime = RedisCheckpointRuntime("redis://redis:6379/0")
        health = await runtime.start()
        refreshed = await runtime.check_health()
        await runtime.close()

    assert health.available is True
    assert refreshed.available is True
    saver.asetup.assert_awaited_once()
    saver._redis.ping.assert_awaited_once()
    saver_type.from_conn_string.assert_called_once_with(
        "redis://redis:6379/0",
        ttl={"default_ttl": 1440, "refresh_on_read": True},
    )
    assert context.closed is True


@pytest.mark.asyncio
async def test_unavailable_redis_degrades_without_memory_fallback() -> None:
    saver_type = MagicMock()
    saver_type.from_conn_string.return_value = _SaverContext(
        MagicMock(), error=ConnectionError("offline")
    )
    module = ModuleType("langgraph.checkpoint.redis.aio")
    module.AsyncRedisSaver = saver_type

    with patch.dict(sys.modules, {"langgraph.checkpoint.redis.aio": module}):
        runtime = RedisCheckpointRuntime("redis://offline:6379/0")
        health = await runtime.start()

    assert health.available is False
    assert health.reason == "checkpoint_unavailable"
    assert runtime.saver is None


@pytest.mark.asyncio
async def test_health_check_marks_live_saver_degraded_and_recovers() -> None:
    saver = MagicMock()
    saver.asetup = AsyncMock()
    saver._redis.ping = AsyncMock(side_effect=[ConnectionError("offline"), True])
    context = _SaverContext(saver)
    saver_type = MagicMock()
    saver_type.from_conn_string.return_value = context
    module = ModuleType("langgraph.checkpoint.redis.aio")
    module.AsyncRedisSaver = saver_type

    with patch.dict(sys.modules, {"langgraph.checkpoint.redis.aio": module}):
        runtime = RedisCheckpointRuntime("redis://redis:6379/0")
        await runtime.start()
        degraded = await runtime.check_health()
        recovered = await runtime.check_health()
        await runtime.close()

    assert degraded.available is False
    assert degraded.reason == "checkpoint_unavailable"
    assert recovered.available is True


@pytest.mark.asyncio
async def test_has_thread_uses_official_saver_lookup() -> None:
    runtime = RedisCheckpointRuntime("redis://example")
    runtime.saver = MagicMock()
    runtime.saver.aget_tuple = AsyncMock(return_value=MagicMock())

    assert await runtime.has_thread("turn:task-1") is True
    runtime.saver.aget_tuple.assert_awaited_once_with(
        {"configurable": {"thread_id": "turn:task-1"}}
    )


@pytest.mark.asyncio
async def test_missing_url_keeps_volatile_runtime_available() -> None:
    runtime = RedisCheckpointRuntime(None)

    health = await runtime.start()

    assert health.available is False
    assert health.reason == "redis_url_missing"
    assert runtime.saver is None
