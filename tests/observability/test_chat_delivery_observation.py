from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from animetta.observability.context import ObservationContext, observation_context
from animetta.observability.domain import EventDirection, PrivacyMode
from animetta.orchestration.chat_contracts import ChatIdentity, ChatTransportMode
from animetta.orchestration.chat_delivery import ChatDelivery


class Recorder:
    def __init__(self) -> None:
        self.events = []

    async def record_event(self, event) -> None:
        self.events.append(event)


def _identity() -> ChatIdentity:
    task_id = str(uuid4())
    return ChatIdentity(
        message_id=str(uuid4()),
        conversation_id=str(uuid4()),
        task_id=task_id,
        turn_id=task_id,
    )


def _context(identity: ChatIdentity) -> ObservationContext:
    return ObservationContext(
        identity.task_id,
        "output-op",
        None,
        identity.message_id,
        identity.conversation_id,
        "socket-1",
        PrivacyMode.REDACTED,
    )


async def test_emit_records_delivered_egress_without_payload_content() -> None:
    identity = _identity()
    recorder = Recorder()
    sio = AsyncMock()
    delivery = ChatDelivery(
        sio, identity, ChatTransportMode.CANONICAL, recorder=recorder
    )

    with observation_context(_context(identity)):
        await delivery.emit(
            "chat",
            "sentence",
            {"text": "private assistant output", "seq": 0, "lang": "zh"},
            to="socket-1",
        )

    event = recorder.events[0]
    assert event.direction is EventDirection.EGRESS
    assert event.name == "chat:sentence"
    assert event.phase == "delivered"
    assert event.operation_id == "output-op"
    assert event.payload_size > 0
    assert event.identity_valid is True
    assert "private assistant output" not in repr(event)


async def test_emit_failure_records_failed_phase_and_reraises() -> None:
    identity = _identity()
    recorder = Recorder()
    sio = AsyncMock()
    sio.emit.side_effect = ConnectionError("network down")
    delivery = ChatDelivery(
        sio, identity, ChatTransportMode.CANONICAL, recorder=recorder
    )

    with observation_context(_context(identity)), pytest.raises(ConnectionError):
        await delivery.emit(
            "chat",
            "audio_with_expression",
            {"audio_data": "private-audio", "format": "wav", "volumes": []},
        )

    assert recorder.events[0].phase == "failed"
    assert recorder.events[0].payload_size >= len(b"private-audio")
    assert "private-audio" not in repr(recorder.events[0])
