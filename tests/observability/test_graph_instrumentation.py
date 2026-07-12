import asyncio
import inspect
from collections.abc import Mapping

import pytest

from animetta.observability.context import ObservationContext, observation_context
from animetta.observability.domain import (
    ObservationLayer,
    OperationStatus,
    PrivacyMode,
)
from animetta.orchestration.graph.instrumentation import instrument_node


class Recorder:
    def __init__(self) -> None:
        self.started = []
        self.finished = []

    async def start_operation(self, record) -> None:
        self.started.append(record)

    async def finish_operation(self, record) -> None:
        self.finished.append(record)


def _root() -> ObservationContext:
    return ObservationContext(
        trace_id="task-1",
        operation_id=None,
        parent_operation_id=None,
        message_id="message-1",
        conversation_id="conversation-1",
        session_id="socket-1",
        privacy_mode=PrivacyMode.REDACTED,
    )


async def test_instrument_node_preserves_signature_and_parent_context() -> None:
    recorder = Recorder()
    seen = None

    async def reasoner(state: Mapping, config=None):
        nonlocal seen
        from animetta.observability.context import get_observation_context

        seen = get_observation_context()
        return {"response_text": "ok"}

    wrapped = instrument_node("reasoner", reasoner, recorder)
    with observation_context(_root()):
        result = await wrapped({"task_id": "task-1"}, config={})

    assert inspect.signature(wrapped) == inspect.signature(reasoner)
    assert result == {"response_text": "ok"}
    assert recorder.started[0].trace_id == "task-1"
    assert recorder.started[0].layer is ObservationLayer.WORKFLOW
    assert recorder.started[0].name == "reasoner"
    assert seen.operation_id == recorder.started[0].operation_id
    assert seen.parent_operation_id is None
    assert recorder.finished[0].status is OperationStatus.SUCCESS


async def test_instrument_node_classifies_returned_error_without_exception() -> None:
    recorder = Recorder()

    async def guard(state):
        return {"error": "guard rejected"}

    wrapped = instrument_node("response_guard", guard, recorder)
    with observation_context(_root()):
        await wrapped({})

    assert recorder.finished[0].status is OperationStatus.ERROR


async def test_instrument_node_records_cancellation_and_reraises() -> None:
    recorder = Recorder()

    async def cancelled(state):
        raise asyncio.CancelledError

    wrapped = instrument_node("tts", cancelled, recorder)
    with observation_context(_root()), pytest.raises(asyncio.CancelledError):
        await wrapped({})

    assert recorder.finished[0].status is OperationStatus.CANCELLED
