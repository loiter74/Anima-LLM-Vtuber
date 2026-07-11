from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from animetta.orchestration.graph.orchestrator import LangGraphOrchestrator
from animetta.orchestration.graph.state import create_initial_state


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

    async def run_graph(state):
        return {**state, "response_text": "reply"}

    orchestrator._run_graph = AsyncMock(side_effect=run_graph)

    result = await orchestrator.process_text(text="hello", **identity)

    state = orchestrator._run_graph.await_args.args[0]
    for field, value in identity.items():
        assert state[field] == value
        assert state["metadata"][field] == value
        assert result[field] == value


@pytest.mark.asyncio
async def test_run_graph_reuses_task_id_for_stats_and_otel(monkeypatch) -> None:
    identity = _identity()
    context = MagicMock()
    context.session_id = "sid"
    orchestrator = LangGraphOrchestrator(service_context=context, socketio=None)
    orchestrator._stats_handler = MagicMock()
    orchestrator._stats_handler.start_trace.return_value = identity["task_id"]
    orchestrator.graph = MagicMock()
    state = create_initial_state(session_id="sid", user_text="hello", **identity)
    orchestrator.graph.ainvoke = AsyncMock(return_value=state)
    orchestrator._persist_conversation_observation = AsyncMock()
    attach = MagicMock(return_value=None)
    monkeypatch.setattr(
        "animetta.orchestration.graph.orchestrator.attach_trace_context", attach
    )

    await orchestrator._run_graph(state)

    orchestrator._stats_handler.start_trace.assert_called_once_with(
        "sid", "text", "hello", trace_id=identity["task_id"]
    )
    attach.assert_called_once_with(identity["task_id"])


@pytest.mark.asyncio
async def test_persisted_metadata_is_allowlisted_and_keeps_identity(monkeypatch) -> None:
    identity = _identity()
    context = MagicMock()
    context.session_id = "sid"
    orchestrator = LangGraphOrchestrator(service_context=context, socketio=None)
    state = create_initial_state(session_id="sid", user_text="hello", **identity)
    state["config_version"] = 3
    state["metadata"] = {
        **identity,
        "config_version": 3,
        "source": "text",
        "api_key": "must-not-persist",
        "prompt": "must-not-persist",
    }
    store = MagicMock()
    store.create_trace = AsyncMock()
    store.store_conversation_turn = AsyncMock()
    monkeypatch.setattr(
        "animetta.orchestration.graph.orchestrator.get_stats_store",
        AsyncMock(return_value=store),
    )
    orchestrator._persist_node_snapshot_spans = AsyncMock()

    await orchestrator._persist_conversation_observation(
        trace_id=identity["task_id"],
        initial_state=state,
        final_state={**state, "metadata": {"secret": "must-not-persist"}},
        status="success",
        error_msg=None,
    )

    metadata = store.store_conversation_turn.await_args.kwargs["metadata"]
    assert metadata == {**identity, "config_version": 3, "source": "text"}
