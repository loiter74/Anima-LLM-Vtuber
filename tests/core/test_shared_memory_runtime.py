from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from animetta.core.service_context import ServiceContext
from animetta.core.service_pool import ServicePool
from animetta.core.shared_memory_runtime import ConversationTurn, SharedMemoryRuntime
from animetta.memory.v2.atom import MemoryScope, MemoryVisibility
from animetta.memory.v2.context import MemoryContext
from animetta.orchestration.server.session import SessionManager


class FakeMemorySystem:
    def __init__(self) -> None:
        self.store = SimpleNamespace(
            process_index_outbox=AsyncMock(
                return_value={"processed": 0, "succeeded": 0, "failed": 0}
            ),
            get_index_backlog=AsyncMock(return_value=0),
            get_index_health=lambda: {"degraded": False, "last_error": ""},
            get_revision=AsyncMock(return_value=0),
        )
        self.initialize_calls = 0
        self.start_calls = 0
        self.shutdown_calls = 0
        self.encode = AsyncMock(return_value=SimpleNamespace(id="raw-1"))

    async def initialize(self) -> None:
        self.initialize_calls += 1

    async def start_metabolism(self) -> None:
        self.start_calls += 1

    async def shutdown(self) -> None:
        self.shutdown_calls += 1


@pytest.mark.asyncio
async def test_shared_runtime_initializes_and_closes_exactly_once() -> None:
    system = FakeMemorySystem()
    runtime = SharedMemoryRuntime(system_factory=lambda: system, worker_interval=0.01)

    await runtime.initialize()
    await runtime.initialize()

    assert runtime.system is system
    assert system.initialize_calls == 1
    assert system.start_calls == 1

    await runtime.shutdown()
    await runtime.shutdown()

    assert system.shutdown_calls == 1


@pytest.mark.asyncio
async def test_ingestion_filters_deduplicates_and_protects_character_scope() -> None:
    system = FakeMemorySystem()
    runtime = SharedMemoryRuntime(system_factory=lambda: system, worker_interval=0.01)
    await runtime.initialize()
    context = MemoryContext(actor_id="bilibili:42", channel="bilibili")

    assert runtime.submit_turn(ConversationTurn(
        user_input="probe",
        agent_response="pong",
        context=context,
        is_probe=True,
    )) is False
    assert runtime.submit_turn(ConversationTurn(
        user_input="hello",
        agent_response="fallback",
        context=context,
        is_fallback=True,
    )) is False
    turn = ConversationTurn(
        user_input="我喜欢拿铁",
        agent_response="我记住了。",
        context=context,
        requested_scope=MemoryScope.CHARACTER,
        retention_policy="durable",
    )
    assert runtime.submit_turn(turn) is True
    assert runtime.submit_turn(turn) is False

    await runtime.drain()

    system.encode.assert_awaited_once()
    kwargs = system.encode.await_args.kwargs
    assert kwargs["scope"] is MemoryScope.VIEWER
    assert kwargs["visibility"] is MemoryVisibility.PRIVATE
    assert kwargs["retention_policy"] == "durable"
    health = await runtime.health()
    assert health["ingestion_rejected"] == 3
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_ingestion_queue_pressure_is_non_blocking() -> None:
    system = FakeMemorySystem()
    release = asyncio.Event()
    started = asyncio.Event()

    async def blocked_encode(**_: object) -> SimpleNamespace:
        started.set()
        await release.wait()
        return SimpleNamespace(id="raw-blocked")

    system.encode = AsyncMock(side_effect=blocked_encode)
    runtime = SharedMemoryRuntime(
        system_factory=lambda: system,
        worker_interval=0.01,
        ingestion_queue_size=1,
    )
    await runtime.initialize()

    def turn(index: int) -> ConversationTurn:
        return ConversationTurn(
            user_input=f"question {index}",
            agent_response=f"answer {index}",
            context=MemoryContext(actor_id="local:owner", channel="local"),
        )

    assert runtime.submit_turn(turn(1)) is True
    await asyncio.wait_for(started.wait(), timeout=1)
    assert runtime.submit_turn(turn(2)) is True
    assert runtime.submit_turn(turn(3)) is False
    release.set()
    await runtime.drain()

    health = await runtime.health()
    assert health["ingestion_dropped"] == 1
    assert system.encode.await_count == 2
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_revision_subscribers_receive_successful_ingestion() -> None:
    system = FakeMemorySystem()
    system.store.get_revision = AsyncMock(return_value=9)
    runtime = SharedMemoryRuntime(system_factory=lambda: system, worker_interval=0.01)
    notifications: list[dict[str, object]] = []
    runtime.subscribe_revision(notifications.append)
    await runtime.initialize()

    assert runtime.submit_turn(ConversationTurn(
        user_input="hello",
        agent_response="hi",
        context=MemoryContext(actor_id="local:owner", channel="local"),
    )) is True
    await runtime.drain()

    assert notifications == [{
        "revision": 9,
        "reason": "ingested",
        "atom_id": "raw-1",
    }]
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_service_context_does_not_close_borrowed_memory() -> None:
    system = FakeMemorySystem()
    ctx = ServiceContext()
    ctx.attach_memory_system(system, owned=False)

    await ctx.close()

    assert system.shutdown_calls == 0


@pytest.mark.asyncio
async def test_session_contexts_share_runtime_across_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system = FakeMemorySystem()
    runtime = SharedMemoryRuntime(system_factory=lambda: system, worker_interval=0.01)
    await runtime.initialize()

    monkeypatch.setattr(
        ServicePool,
        "get_context",
        classmethod(lambda cls: {"llm_engine": object(), "tts_engine": None, "asr_engine": None}),
    )
    monkeypatch.setattr(ServiceContext, "init_vad", AsyncMock())
    monkeypatch.setattr(ServiceContext, "init_emotion_analyzer", AsyncMock())

    manager = SessionManager(memory_runtime=runtime)
    config = SimpleNamespace(vad=object())
    send = AsyncMock()

    first = await manager.get_or_create_context("socket-a", config, send)
    second = await manager.get_or_create_context("socket-b", config, send)

    assert first.memory_system is system
    assert second.memory_system is system
    assert first.memory_system is second.memory_system

    await manager.cleanup_session("socket-a")

    assert system.shutdown_calls == 0
    assert manager.get_context("socket-b").memory_system is system

    await manager.cleanup_all()
    assert system.shutdown_calls == 0

    await runtime.shutdown()
    assert system.shutdown_calls == 1
