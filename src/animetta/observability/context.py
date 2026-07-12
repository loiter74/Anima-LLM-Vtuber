"""Context propagation for request and background observation work."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, replace

from .domain import PrivacyMode


@dataclass(frozen=True, slots=True)
class ObservationContext:
    trace_id: str
    operation_id: str | None
    parent_operation_id: str | None
    message_id: str
    conversation_id: str
    session_id: str
    privacy_mode: PrivacyMode
    critical_path: bool = True


@dataclass(frozen=True, slots=True)
class ObservationCarrier:
    trace_id: str
    parent_operation_id: str | None
    message_id: str
    conversation_id: str
    session_id: str
    privacy_mode: PrivacyMode

    @classmethod
    def from_context(cls, context: ObservationContext) -> ObservationCarrier:
        return cls(
            trace_id=context.trace_id,
            parent_operation_id=context.operation_id or context.parent_operation_id,
            message_id=context.message_id,
            conversation_id=context.conversation_id,
            session_id=context.session_id,
            privacy_mode=context.privacy_mode,
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ObservationCarrier:
        return cls(
            trace_id=str(data["trace_id"]),
            parent_operation_id=(
                str(data["parent_operation_id"])
                if data.get("parent_operation_id") is not None
                else None
            ),
            message_id=str(data["message_id"]),
            conversation_id=str(data["conversation_id"]),
            session_id=str(data["session_id"]),
            privacy_mode=PrivacyMode(str(data["privacy_mode"])),
        )

    def to_dict(self) -> dict[str, str | None]:
        return {
            "trace_id": self.trace_id,
            "parent_operation_id": self.parent_operation_id,
            "message_id": self.message_id,
            "conversation_id": self.conversation_id,
            "session_id": self.session_id,
            "privacy_mode": self.privacy_mode.value,
        }

    def to_context(self, *, operation_id: str | None = None) -> ObservationContext:
        return ObservationContext(
            trace_id=self.trace_id,
            operation_id=operation_id,
            parent_operation_id=self.parent_operation_id,
            message_id=self.message_id,
            conversation_id=self.conversation_id,
            session_id=self.session_id,
            privacy_mode=self.privacy_mode,
        )


_CURRENT_CONTEXT: ContextVar[ObservationContext | None] = ContextVar(
    "animetta_observation_context", default=None
)
_DELIVERY_EVIDENCE: ContextVar[dict[str, bool] | None] = ContextVar(
    "animetta_delivery_evidence", default=None
)
_CURRENT_RECORDER: ContextVar[object | None] = ContextVar(
    "animetta_observation_recorder", default=None
)


def get_observation_context() -> ObservationContext | None:
    return _CURRENT_CONTEXT.get()


def attach_observation_context(context: ObservationContext) -> Token:
    return _CURRENT_CONTEXT.set(context)


def detach_observation_context(token: Token) -> None:
    _CURRENT_CONTEXT.reset(token)


def attach_observation_recorder(recorder: object) -> Token:
    return _CURRENT_RECORDER.set(recorder)


def get_observation_recorder() -> object | None:
    return _CURRENT_RECORDER.get()


def detach_observation_recorder(token: Token) -> None:
    _CURRENT_RECORDER.reset(token)


def begin_delivery_evidence() -> Token:
    return _DELIVERY_EVIDENCE.set({"attempted": False})


def mark_delivery_evidence(
    *,
    text_delivered: bool | None = None,
    terminal_control_delivered: bool | None = None,
    audio_delivered: bool | None = None,
) -> None:
    evidence = _DELIVERY_EVIDENCE.get()
    if evidence is None:
        return
    evidence["attempted"] = True
    if text_delivered is not None:
        evidence["text_delivered"] = text_delivered
    if terminal_control_delivered is not None:
        evidence["terminal_control_delivered"] = terminal_control_delivered
    if audio_delivered is not None:
        evidence["audio_delivered"] = audio_delivered


def delivery_evidence() -> dict[str, bool]:
    return dict(_DELIVERY_EVIDENCE.get() or {})


def end_delivery_evidence(token: Token) -> None:
    _DELIVERY_EVIDENCE.reset(token)


@contextmanager
def observation_context(context: ObservationContext) -> Iterator[ObservationContext]:
    token = attach_observation_context(context)
    try:
        yield context
    finally:
        detach_observation_context(token)


@contextmanager
def noncritical_observation_context() -> Iterator[ObservationContext | None]:
    """Mark work spawned from the current operation as post-turn/non-critical."""
    current = get_observation_context()
    if current is None:
        yield None
        return
    background = replace(current, critical_path=False)
    with observation_context(background):
        yield background
