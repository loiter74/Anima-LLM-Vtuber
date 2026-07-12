from dataclasses import FrozenInstanceError

import pytest

from animetta.observability.context import ObservationCarrier, ObservationContext
from animetta.observability.domain import (
    EventDirection,
    ObservationEvent,
    ObservationLayer,
    OperationStarted,
    OperationStatus,
    PrivacyMode,
    TraceIdentity,
    TraceOutcome,
    TraceStarted,
)


def test_trace_identity_uses_task_id_verbatim() -> None:
    identity = TraceIdentity(
        message_id="message-1",
        conversation_id="conversation-1",
        task_id="task-with-hyphens",
        session_id="socket-1",
    )

    assert identity.trace_id == "task-with-hyphens"


@pytest.mark.parametrize(
    ("enum_type", "expected"),
    [
        (TraceOutcome, {"success", "degraded", "failed", "cancelled", "aborted"}),
        (OperationStatus, {"success", "skipped", "degraded", "error", "cancelled"}),
        (ObservationLayer, {"transport", "workflow", "service", "memory", "delivery"}),
        (EventDirection, {"ingress", "egress", "internal"}),
    ],
)
def test_status_enums_have_stable_wire_values(enum_type: type, expected: set[str]) -> None:
    assert {item.value for item in enum_type} == expected


def test_observation_records_are_deeply_immutable() -> None:
    started = TraceStarted(
        identity=TraceIdentity("m", "c", "t", "s"),
        runtime_profile="golden",
        input_type="text",
        privacy_mode=PrivacyMode.REDACTED,
        started_at=10.0,
        attributes={"source": "text"},
    )

    with pytest.raises(FrozenInstanceError):
        started.input_type = "audio"  # type: ignore[misc]
    with pytest.raises(TypeError):
        started.attributes["source"] = "voice"  # type: ignore[index]


def test_operation_and_event_keep_canonical_trace_identity() -> None:
    operation = OperationStarted(
        operation_id="op-1",
        trace_id="task-1",
        parent_operation_id=None,
        layer=ObservationLayer.WORKFLOW,
        name="reasoner",
        critical_path=True,
        started_at=11.0,
    )
    event = ObservationEvent(
        event_id="event-1",
        trace_id="task-1",
        operation_id="op-1",
        direction=EventDirection.EGRESS,
        name="chat:sentence",
        phase="text",
        occurred_at=12.0,
        payload_size=42,
        identity_valid=True,
    )

    assert operation.trace_id == event.trace_id == "task-1"


def test_observation_carrier_round_trips_across_queue_boundary() -> None:
    context = ObservationContext(
        trace_id="task-1",
        operation_id="memory-enqueue",
        parent_operation_id="output",
        message_id="message-1",
        conversation_id="conversation-1",
        session_id="socket-1",
        privacy_mode=PrivacyMode.REDACTED,
    )

    carrier = ObservationCarrier.from_context(context)
    restored = ObservationCarrier.from_dict(carrier.to_dict())

    assert restored == carrier
    assert restored.trace_id == "task-1"
    assert restored.parent_operation_id == "memory-enqueue"
