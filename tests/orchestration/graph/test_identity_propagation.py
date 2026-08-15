from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from animetta.observability.ports import NoOpObservationRecorder
from animetta.orchestration.graph.orchestrator import LangGraphOrchestrator
from animetta.orchestration.graph.state import create_initial_state


class CaptureRecorder(NoOpObservationRecorder):
    def __init__(self) -> None:
        self.started = []
        self.finished = []

    async def start_trace(self, record) -> None:
        self.started.append(record)

    async def finish_trace(self, trace_id, outcome, **kwargs) -> None:
        self.finished.append((trace_id, outcome, kwargs))


def _identity() -> dict[str, str]:
    task_id = str(uuid4())
    return {
        "message_id": str(uuid4()),
        "conversation_id": str(uuid4()),
        "task_id": task_id,
        "turn_id": task_id,
    }


def test_initial_state_has_first_class_chat_identity() -> None:
    identity = _identity()

    state = create_initial_state(session_id="sid", **identity)

    for field, value in identity.items():
        assert state[field] == value


def test_initial_state_generates_correlated_identity_when_internal_caller_omits_it() -> None:
    state = create_initial_state(session_id="sid")

    assert state["message_id"] is not None
    assert state["conversation_id"] is not None
    assert state["task_id"] is not None
    assert state["turn_id"] == state["task_id"]


@pytest.mark.asyncio
async def test_process_text_propagates_identity_to_state_and_result() -> None:
    identity = _identity()
    context = MagicMock()
    context.session_id = "sid"
    context.runtime_config_version = 1
    orchestrator = LangGraphOrchestrator(service_context=context, socketio=None)
    orchestrator._is_running = True
    orchestrator._get_persona_dict = MagicMock(return_value={})
    orchestrator._get_system_prompt = MagicMock(return_value=None)

    async def run_graph(state, *, tool_invocation_observer=None, checkpoint_request=None):
        assert tool_invocation_observer is None
        assert checkpoint_request is None
        return {**state, "response_text": "reply"}

    orchestrator._run_graph = AsyncMock(side_effect=run_graph)

    result = await orchestrator.process_text(text="hello", **identity)

    state = orchestrator._run_graph.await_args.args[0]
    for field, value in identity.items():
        assert state[field] == value
        assert state["metadata"][field] == value
        assert result[field] == value


@pytest.mark.asyncio
async def test_run_graph_reuses_task_id_for_canonical_observation() -> None:
    identity = _identity()
    context = MagicMock()
    context.session_id = "sid"
    recorder = CaptureRecorder()
    orchestrator = LangGraphOrchestrator(
        service_context=context,
        socketio=None,
        observation_recorder=recorder,
    )
    orchestrator.graph = MagicMock()
    state = create_initial_state(session_id="sid", user_text="hello", **identity)
    orchestrator.graph.ainvoke = AsyncMock(return_value={**state, "response_text": "reply"})
    await orchestrator._run_graph(state)

    assert recorder.started[0].trace_id == identity["task_id"]
    assert recorder.finished[0][0] == identity["task_id"]


@pytest.mark.asyncio
async def test_observation_metadata_is_allowlisted_and_keeps_identity() -> None:
    identity = _identity()
    context = MagicMock()
    context.session_id = "sid"
    recorder = CaptureRecorder()
    orchestrator = LangGraphOrchestrator(
        service_context=context,
        socketio=None,
        observation_recorder=recorder,
    )
    state = create_initial_state(session_id="sid", user_text="hello", **identity)
    state["config_version"] = 3
    state["metadata"] = {
        **identity,
        "config_version": 3,
        "source": "text",
        "api_key": "must-not-persist",
        "prompt": "must-not-persist",
    }
    orchestrator.graph = MagicMock()
    orchestrator.graph.ainvoke = AsyncMock(
        return_value={
            **state,
            "response_text": "reply",
            "metadata": {"secret": "must-not-persist"},
        }
    )
    await orchestrator._run_graph(state)

    serialized = repr((recorder.started, recorder.finished))
    assert identity["task_id"] in serialized
    assert "must-not-persist" not in serialized
