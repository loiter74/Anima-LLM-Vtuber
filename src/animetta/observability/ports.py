"""Dependency inversion ports for recording and consuming observations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from .domain import (
    CommittedObservation,
    ContentFacts,
    ObservationEvent,
    ObservationHealth,
    OperationFinished,
    OperationStarted,
    TraceOutcome,
    TraceStarted,
)


@runtime_checkable
class ObservationRecorder(Protocol):
    async def start_trace(self, record: TraceStarted) -> None: ...
    async def finish_trace(
        self,
        trace_id: str,
        outcome: TraceOutcome,
        *,
        finished_at: float,
        error_type: str | None = None,
        error_summary: str | None = None,
        assistant_content: ContentFacts | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> None: ...
    async def start_operation(self, record: OperationStarted) -> None: ...
    async def finish_operation(self, record: OperationFinished) -> None: ...
    async def record_event(self, record: ObservationEvent) -> None: ...
    async def flush(self) -> None: ...
    async def health(self) -> ObservationHealth: ...


@runtime_checkable
class ObservationQuery(Protocol):
    async def overview(self) -> Mapping[str, Any]: ...
    async def operation_aggregates(self) -> Sequence[Mapping[str, Any]]: ...
    async def recent_traces(
        self, limit: int = 50, offset: int = 0
    ) -> Sequence[Mapping[str, Any]]: ...
    async def trace_detail(self, trace_id: str) -> Mapping[str, Any] | None: ...
    async def trace_events(self, trace_id: str) -> Sequence[Mapping[str, Any]]: ...
    async def inspection_reports(
        self, limit: int = 50, offset: int = 0
    ) -> Sequence[Mapping[str, Any]]: ...
    async def observation_health(self) -> ObservationHealth: ...


@runtime_checkable
class ObservationReportStore(Protocol):
    async def store_inspection_report(self, report: Mapping[str, Any]) -> None: ...
    async def latest_inspection_report(self) -> Mapping[str, Any] | None: ...


@runtime_checkable
class ObservationMirror(Protocol):
    async def publish(self, record: CommittedObservation) -> None: ...
    async def health(self) -> ObservationHealth: ...


class NoOpObservationRecorder:
    async def start_trace(self, record: TraceStarted) -> None:
        del record

    async def finish_trace(
        self,
        trace_id: str,
        outcome: TraceOutcome,
        *,
        finished_at: float,
        error_type: str | None = None,
        error_summary: str | None = None,
        assistant_content: ContentFacts | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> None:
        del (
            trace_id,
            outcome,
            finished_at,
            error_type,
            error_summary,
            assistant_content,
            attributes,
        )

    async def start_operation(self, record: OperationStarted) -> None:
        del record

    async def finish_operation(self, record: OperationFinished) -> None:
        del record

    async def record_event(self, record: ObservationEvent) -> None:
        del record

    async def flush(self) -> None:
        return None

    async def health(self) -> ObservationHealth:
        return ObservationHealth(enabled=False, ready=False, degraded=True)


class NoOpObservationQuery:
    async def overview(self) -> Mapping[str, Any]:
        return {"schema_version": 2, "total_requests": 0}

    async def operation_aggregates(self) -> Sequence[Mapping[str, Any]]:
        return []

    async def recent_traces(self, limit: int = 50, offset: int = 0) -> Sequence[Mapping[str, Any]]:
        del limit, offset
        return []

    async def trace_detail(self, trace_id: str) -> Mapping[str, Any] | None:
        del trace_id
        return None

    async def trace_events(self, trace_id: str) -> Sequence[Mapping[str, Any]]:
        del trace_id
        return []

    async def inspection_reports(
        self, limit: int = 50, offset: int = 0
    ) -> Sequence[Mapping[str, Any]]:
        del limit, offset
        return []

    async def observation_health(self) -> ObservationHealth:
        return ObservationHealth(enabled=False, ready=False, degraded=True)


class NoOpObservationReportStore:
    async def store_inspection_report(self, report: Mapping[str, Any]) -> None:
        del report

    async def latest_inspection_report(self) -> Mapping[str, Any] | None:
        return None


class NoOpObservationMirror:
    async def publish(self, record: CommittedObservation) -> None:
        del record

    async def health(self) -> ObservationHealth:
        return ObservationHealth(enabled=False, ready=False, degraded=False)
