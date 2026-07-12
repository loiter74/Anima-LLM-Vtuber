"""Identity-safe Socket.IO delivery for golden chat events."""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

from animetta.observability.context import (
    get_observation_context,
    mark_delivery_evidence,
)
from animetta.observability.domain import EventDirection, ObservationEvent
from animetta.observability.errors import classify_error
from animetta.observability.ports import NoOpObservationRecorder, ObservationRecorder
from animetta.orchestration.chat_contracts import (
    ChatIdentity,
    ChatTransportMode,
)
from animetta.orchestration.socket_events import (
    EVENTS,
    IDENTITY_FIELDS,
    event_aliases,
    event_name,
    validate_event_field_value,
)

_CORRELATED_FIELDS = (*IDENTITY_FIELDS, "turn_id")


@dataclass(frozen=True, slots=True)
class ChatDelivery:
    """Attach immutable turn identity and emit exactly one wire generation."""

    sio: Any
    identity: ChatIdentity
    transport_mode: ChatTransportMode
    recorder: ObservationRecorder = dataclass_field(
        default_factory=NoOpObservationRecorder
    )

    def _wire_event(self, module: str, action: str) -> str:
        canonical = event_name(module, action)
        if self.transport_mode is ChatTransportMode.CANONICAL:
            return canonical
        aliases = event_aliases(module, action)
        if not aliases:
            raise ValueError(f"legacy event alias is not declared: {module}.{action}")
        return aliases[0]

    def build_payload(
        self,
        module: str,
        action: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate one catalog payload and return a detached correlated copy."""
        try:
            definition = EVENTS[module][action]
            schema = definition["payload"]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"unknown event contract: {module}.{action}") from exc
        if definition.get("golden_path") is not True or definition.get("identity") != "correlated":
            raise ValueError(f"event is not a correlated golden event: {module}.{action}")
        if not isinstance(payload, dict) or not isinstance(schema, dict):
            raise TypeError("delivery payload must be a dict")
        overridden = set(payload) & set(_CORRELATED_FIELDS)
        if overridden:
            raise ValueError(f"payload cannot override identity fields: {sorted(overridden)}")

        result = {
            **payload,
            "message_id": self.identity.message_id,
            "conversation_id": self.identity.conversation_id,
            "task_id": self.identity.task_id,
            "turn_id": self.identity.task_id,
        }
        normalized_schema = {
            field.removesuffix("?"): (field, descriptor)
            for field, descriptor in schema.items()
        }
        unknown = set(result) - set(normalized_schema)
        if unknown:
            raise ValueError(f"unknown payload fields: {sorted(unknown)}")
        required = {
            field.removesuffix("?")
            for field, descriptor in schema.items()
            if isinstance(descriptor, dict) and descriptor.get("required") is True
        }
        missing = required - set(result)
        if missing:
            raise ValueError(f"missing required payload fields: {sorted(missing)}")
        for field, value in result.items():
            validate_event_field_value(module, action, field, value)
        return result

    async def emit(
        self,
        module: str,
        action: str,
        payload: dict[str, Any],
        *,
        to: str | None = None,
    ) -> None:
        """Emit one validated event and never mirror it to the other generation."""
        event = self._wire_event(module, action)
        correlated = self.build_payload(module, action, payload)
        try:
            if to is None:
                await self.sio.emit(event, correlated)
            else:
                await self.sio.emit(event, correlated, to=to)
        except Exception as exc:
            self._mark_evidence(action, payload, delivered=False)
            await self._record_event(
                event,
                "failed",
                correlated,
                error_type=classify_error(exc).value,
            )
            raise
        self._mark_evidence(action, payload, delivered=True)
        await self._record_event(event, "delivered", correlated)

    @staticmethod
    def _mark_evidence(
        action: str,
        payload: Mapping[str, Any],
        *,
        delivered: bool,
    ) -> None:
        if action == "sentence" and bool(payload.get("text")):
            mark_delivery_evidence(text_delivered=delivered)
        elif action == "control" and payload.get("signal") == "conversation-end":
            mark_delivery_evidence(terminal_control_delivered=delivered)
        elif action == "audio_with_expression":
            mark_delivery_evidence(audio_delivered=delivered)

    async def _record_event(
        self,
        event_name: str,
        phase: str,
        payload: Mapping[str, Any],
        *,
        error_type: str | None = None,
    ) -> None:
        context = get_observation_context()
        if context is None:
            return
        identity_valid = (
            context.trace_id == self.identity.task_id
            and context.message_id == self.identity.message_id
            and context.conversation_id == self.identity.conversation_id
        )
        await self.recorder.record_event(
            ObservationEvent(
                event_id=uuid.uuid4().hex,
                trace_id=context.trace_id,
                operation_id=context.operation_id,
                direction=EventDirection.EGRESS,
                name=event_name,
                phase=phase,
                occurred_at=time.time(),
                payload_size=_payload_size(payload),
                identity_valid=identity_valid,
                attributes={
                    "event_name": event_name,
                    "phase": phase,
                    "error_type": error_type,
                },
            )
        )


def _payload_size(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bytes):
        return len(value)
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    if isinstance(value, (bool, int, float)):
        return len(str(value))
    if isinstance(value, Mapping):
        return sum(_payload_size(key) + _payload_size(item) for key, item in value.items())
    if isinstance(value, Sequence):
        return sum(_payload_size(item) for item in value)
    return 0
