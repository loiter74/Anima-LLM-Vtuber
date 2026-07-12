"""Dependency-light immutable records for local-first observability."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import TypeAlias

AttributeValue: TypeAlias = str | int | float | bool | None  # noqa: UP040 - Python 3.11 support
Attributes: TypeAlias = Mapping[str, AttributeValue]  # noqa: UP040 - Python 3.11 support


def freeze_attributes(values: Mapping[str, AttributeValue] | None = None) -> Attributes:
    """Return a shallow immutable copy suitable for persistence commands."""

    return MappingProxyType(dict(values or {}))


class TraceOutcome(StrEnum):
    SUCCESS = "success"
    DEGRADED = "degraded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ABORTED = "aborted"


class OperationStatus(StrEnum):
    SUCCESS = "success"
    SKIPPED = "skipped"
    DEGRADED = "degraded"
    ERROR = "error"
    CANCELLED = "cancelled"


class ObservationLayer(StrEnum):
    TRANSPORT = "transport"
    WORKFLOW = "workflow"
    SERVICE = "service"
    MEMORY = "memory"
    DELIVERY = "delivery"


class EventDirection(StrEnum):
    INGRESS = "ingress"
    EGRESS = "egress"
    INTERNAL = "internal"


class PrivacyMode(StrEnum):
    FULL = "full"
    REDACTED = "redacted"


@dataclass(frozen=True, slots=True)
class TraceIdentity:
    message_id: str
    conversation_id: str
    task_id: str
    session_id: str

    def __post_init__(self) -> None:
        for name in ("message_id", "conversation_id", "task_id", "session_id"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must not be empty")

    @property
    def trace_id(self) -> str:
        return self.task_id


@dataclass(frozen=True, slots=True)
class ContentFacts:
    text: str | None
    character_count: int
    byte_count: int
    digest: str


@dataclass(frozen=True, slots=True)
class ErrorFacts:
    error_type: str
    summary: str


@dataclass(frozen=True, slots=True)
class TraceStarted:
    identity: TraceIdentity
    runtime_profile: str
    input_type: str
    privacy_mode: PrivacyMode
    started_at: float
    user_content: ContentFacts | None = None
    attributes: Attributes = field(default_factory=freeze_attributes)

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", freeze_attributes(self.attributes))

    @property
    def trace_id(self) -> str:
        return self.identity.trace_id


@dataclass(frozen=True, slots=True)
class TraceFinished:
    trace_id: str
    outcome: TraceOutcome
    finished_at: float
    error_type: str | None = None
    error_summary: str | None = None
    assistant_content: ContentFacts | None = None
    attributes: Attributes = field(default_factory=freeze_attributes)

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", freeze_attributes(self.attributes))


@dataclass(frozen=True, slots=True)
class OperationStarted:
    operation_id: str
    trace_id: str
    parent_operation_id: str | None
    layer: ObservationLayer
    name: str
    critical_path: bool
    started_at: float
    provider: str | None = None
    model: str | None = None
    attributes: Attributes = field(default_factory=freeze_attributes)

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", freeze_attributes(self.attributes))


@dataclass(frozen=True, slots=True)
class OperationFinished:
    operation_id: str
    status: OperationStatus
    finished_at: float
    error_type: str | None = None
    error_summary: str | None = None
    attributes: Attributes = field(default_factory=freeze_attributes)

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", freeze_attributes(self.attributes))


@dataclass(frozen=True, slots=True)
class ObservationEvent:
    event_id: str
    trace_id: str
    operation_id: str | None
    direction: EventDirection
    name: str
    phase: str
    occurred_at: float
    payload_size: int
    identity_valid: bool
    attributes: Attributes = field(default_factory=freeze_attributes)

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", freeze_attributes(self.attributes))


@dataclass(frozen=True, slots=True)
class ObservationHealth:
    enabled: bool
    ready: bool
    degraded: bool
    queue_depth: int = 0
    dropped_records: int = 0
    writer_errors: int = 0
    stale_traces_recovered: int = 0
    last_error: str | None = None


CommittedObservation: TypeAlias = (  # noqa: UP040 - Python 3.11 support
    TraceStarted | TraceFinished | OperationStarted | OperationFinished | ObservationEvent
)
