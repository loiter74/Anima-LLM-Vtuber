"""Identity-safe Socket.IO delivery for golden chat events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
        if to is None:
            await self.sio.emit(event, correlated)
        else:
            await self.sio.emit(event, correlated, to=to)
