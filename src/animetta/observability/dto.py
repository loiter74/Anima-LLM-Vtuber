"""Versioned public DTOs for ledger-backed local observability APIs."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from .domain import ObservationHealth


class ObservationDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")
    api_version: ClassVar[str] = "2"

    def public_dict(self) -> dict[str, Any]:
        return {"api_version": self.api_version, **self.model_dump()}


class OverviewDTO(ObservationDTO):
    schema_version: int = 2
    total_requests: int = 0
    success_count: int = 0
    degraded_count: int = 0
    failed_count: int = 0
    success_rate: float = 0.0
    avg_duration_ms: float = 0.0


class OperationAggregateDTO(ObservationDTO):
    layer: str
    name: str
    provider: str | None = None
    model: str | None = None
    operation_count: int = 0
    success_count: int = 0
    degraded_count: int = 0
    failure_count: int = 0
    avg_duration_ms: float | None = None


class TraceSummaryDTO(ObservationDTO):
    trace_id: str
    message_id: str
    conversation_id: str
    session_id: str
    runtime_profile: str
    input_type: str
    privacy_mode: str
    started_at: float
    finished_at: float | None = None
    duration_ms: float | None = None
    outcome: str | None = None
    error_type: str | None = None


class ContentDTO(BaseModel):
    text: str | None = None
    character_count: int | None = None
    byte_count: int | None = None
    digest: str | None = None


class OperationDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")
    operation_id: str
    trace_id: str
    parent_operation_id: str | None = None
    layer: str
    name: str
    critical_path: bool
    started_at: float
    finished_at: float | None = None
    duration_ms: float | None = None
    status: str | None = None
    provider: str | None = None
    model: str | None = None
    error_type: str | None = None
    error_summary: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    children: list[OperationDTO] = Field(default_factory=list)


class EventDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")
    event_id: str
    trace_id: str
    operation_id: str | None = None
    direction: str
    name: str
    phase: str
    occurred_at: float
    payload_size: int
    identity_valid: bool
    attributes: dict[str, Any] = Field(default_factory=dict)


class PostTurnDTO(BaseModel):
    pending: int = 0
    completed: int = 0
    failed: int = 0
    operations: list[OperationDTO] = Field(default_factory=list)


class TraceDetailDTO(TraceSummaryDTO):
    error_summary: str | None = None
    content: dict[str, ContentDTO]
    attributes: dict[str, Any] = Field(default_factory=dict)
    operations: list[OperationDTO] = Field(default_factory=list)
    operation_tree: list[OperationDTO] = Field(default_factory=list)
    events: list[EventDTO] = Field(default_factory=list)
    post_turn: PostTurnDTO = Field(default_factory=PostTurnDTO)
    schema_version: int = 2

    @classmethod
    def from_ledger(cls, value: dict[str, Any]) -> TraceDetailDTO:
        content = {
            "user": ContentDTO(
                text=value.get("user_text"),
                character_count=value.get("user_character_count"),
                byte_count=value.get("user_byte_count"),
                digest=value.get("user_digest"),
            ),
            "assistant": ContentDTO(
                text=value.get("assistant_text"),
                character_count=value.get("assistant_character_count"),
                byte_count=value.get("assistant_byte_count"),
                digest=value.get("assistant_digest"),
            ),
        }
        return cls.model_validate({**value, "content": content})


class HealthDTO(ObservationDTO):
    enabled: bool
    ready: bool
    degraded: bool
    queue_depth: int = 0
    dropped_records: int = 0
    writer_errors: int = 0
    stale_traces_recovered: int = 0
    last_error: str | None = None

    @classmethod
    def from_health(cls, health: ObservationHealth) -> HealthDTO:
        return cls(**{
            field: getattr(health, field)
            for field in cls.model_fields
        })


def versioned_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "api_version": "2",
        "events": [EventDTO.model_validate(event).model_dump() for event in events],
    }
