import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from animetta.core.shared_memory_runtime import ConversationTurn, SharedMemoryRuntime
from animetta.memory.v2.context import MemoryContext
from animetta.observability.context import (
    ObservationCarrier,
    ObservationContext,
    observation_context,
)
from animetta.observability.domain import PrivacyMode
from animetta.orchestration.graph.memory_middleware import MemoryMiddleware


class Recorder:
    def __init__(self) -> None:
        self.started = []
        self.finished = []
        self.events = []

    async def start_operation(self, record) -> None:
        self.started.append(record)

    async def finish_operation(self, record) -> None:
        self.finished.append(record)

    async def record_event(self, record) -> None:
        self.events.append(record)


def _context() -> ObservationContext:
    return ObservationContext(
        "task-1",
        "output-op",
        None,
        "message-1",
        "conversation-1",
        "socket-1",
        PrivacyMode.REDACTED,
    )


class MemorySystem:
    def __init__(self) -> None:
        self.store = SimpleNamespace(
            process_index_outbox=AsyncMock(
                return_value={"processed": 1, "succeeded": 1, "failed": 0}
            ),
            get_revision=AsyncMock(return_value=1),
            get_index_backlog=AsyncMock(return_value=0),
            get_index_health=lambda: {"degraded": False, "last_error": ""},
        )
        self.encode = AsyncMock(return_value=SimpleNamespace(id="atom-1"))

    async def initialize(self):
        return None

    async def start_metabolism(self):
        return None

    async def shutdown(self):
        return None


async def test_background_turn_preserves_carrier_and_noncritical_stages() -> None:
    recorder = Recorder()
    system = MemorySystem()
    runtime = SharedMemoryRuntime(
        system_factory=lambda: system,
        worker_interval=0.01,
        observation_recorder=recorder,
    )
    await runtime.initialize()
    turn = ConversationTurn(
        user_input="hello",
        agent_response="hi",
        context=MemoryContext(actor_id="local:owner", channel="local"),
        observation_carrier=ObservationCarrier.from_context(_context()),
    )

    assert runtime.submit_turn(turn) is True
    await runtime.drain()
    for _ in range(20):
        if any(item.name == "memory.chroma_index" for item in recorder.started):
            break
        await asyncio.sleep(0.01)

    names = [item.name for item in recorder.started]
    assert names[:3] == [
        "memory.ingest",
        "memory.sqlite_commit",
        "memory.outbox_enqueue",
    ]
    assert "memory.chroma_index" in names
    assert {item.trace_id for item in recorder.started} == {"task-1"}
    assert all(item.critical_path is False for item in recorder.started)
    assert recorder.events[0].phase == "accepted"
    await runtime.shutdown()


async def test_memory_recall_is_child_of_active_workflow_operation() -> None:
    recorder = Recorder()
    memory = SimpleNamespace(
        recall=AsyncMock(return_value=SimpleNamespace(atoms=[], profile={}, memes=[], metadata={}))
    )
    middleware = MemoryMiddleware(memory, observation_recorder=recorder)

    with observation_context(_context()):
        await middleware.recall_structured("socket-1", "private query")

    operation = recorder.started[0]
    assert operation.name == "memory.recall"
    assert operation.parent_operation_id == "output-op"
    assert operation.critical_path is True
    assert "private query" not in repr(operation)


async def test_rejected_memory_turn_records_queue_phase() -> None:
    recorder = Recorder()
    runtime = SharedMemoryRuntime(
        system_factory=MemorySystem,
        worker_interval=0.01,
        observation_recorder=recorder,
    )
    await runtime.initialize()
    rejected = ConversationTurn(
        user_input="probe",
        agent_response="pong",
        context=MemoryContext(actor_id="local:owner", channel="local"),
        is_probe=True,
        observation_carrier=ObservationCarrier.from_context(_context()),
    )

    assert runtime.submit_turn(rejected) is False
    await asyncio.sleep(0)

    assert recorder.events[0].name == "memory.turn_queue"
    assert recorder.events[0].phase == "rejected"
    await runtime.shutdown()
