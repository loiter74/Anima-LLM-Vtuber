from __future__ import annotations

from animetta.observability.context import (
    ObservationContext,
    attach_observation_recorder,
    detach_observation_recorder,
    observation_context,
)
from animetta.observability.domain import PrivacyMode
from animetta.orchestration.graph.node_error import VALID_ERROR_TYPES, log_node_error


class Recorder:
    def __init__(self) -> None:
        self.events = []

    async def record_event(self, event) -> None:
        self.events.append(event)


def _context() -> ObservationContext:
    return ObservationContext(
        "task-1",
        "llm-op",
        None,
        "message-1",
        "conversation-1",
        "socket-1",
        PrivacyMode.REDACTED,
    )


async def test_active_context_records_structured_error_event() -> None:
    recorder = Recorder()
    token = attach_observation_recorder(recorder)
    try:
        with observation_context(_context()):
            await log_node_error(
                "socket-1",
                "llm_node",
                "timeout",
                provider="deepseek",
                duration_ms=30000,
            )
    finally:
        detach_observation_recorder(token)

    event = recorder.events[0]
    assert event.trace_id == "task-1"
    assert event.operation_id == "llm-op"
    assert event.name == "llm_node.error"
    assert event.attributes["error_type"] == "timeout"
    assert event.attributes["provider"] == "deepseek"


async def test_invalid_error_type_maps_to_unknown() -> None:
    recorder = Recorder()
    token = attach_observation_recorder(recorder)
    try:
        with observation_context(_context()):
            await log_node_error("socket-1", "tts_node", "cosmic_ray")
    finally:
        detach_observation_recorder(token)

    assert recorder.events[0].attributes["error_type"] == "unknown"


async def test_no_active_context_only_logs() -> None:
    await log_node_error("socket-1", "asr_node", "network_error")


def test_validation_set_matches_spec() -> None:
    assert {
        "timeout",
        "rate_limit",
        "network_error",
        "invalid_response",
    } == VALID_ERROR_TYPES
