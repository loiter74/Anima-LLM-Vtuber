"""OpenTelemetry projection of records already committed to the local ledger."""

from __future__ import annotations

import asyncio
import threading
from collections import deque
from collections.abc import Sequence
from typing import Any

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import Span, Status, StatusCode, Tracer

from ..domain import (
    CommittedObservation,
    ObservationEvent,
    ObservationHealth,
    OperationFinished,
    OperationStarted,
    OperationStatus,
    TraceFinished,
    TraceOutcome,
    TraceStarted,
)

_SAFE_ATTRIBUTE_KEYS = frozenset(
    {
        "attempt",
        "cache_hit",
        "chunk_count",
        "delivery_required",
        "identity_valid",
        "payload_size",
        "queue_depth",
        "result_count",
        "retry_count",
    }
)


class OTelMirror:
    """Maintain one OTel hierarchy from canonical committed records."""

    def __init__(
        self,
        *,
        tracer: Tracer,
        provider: Any | None = None,
        health_state: _MirrorHealthState | None = None,
        batched: bool = False,
        dedup_capacity: int = 16_384,
    ) -> None:
        self._tracer = tracer
        self._provider = provider
        self._health_state = health_state or _MirrorHealthState()
        self.batched = batched
        self._dedup_capacity = max(128, int(dedup_capacity))
        self._seen: set[str] = set()
        self._seen_order: deque[str] = deque()
        self._trace_spans: dict[str, Span] = {}
        self._operation_spans: dict[str, Span] = {}
        self._operation_trace_ids: dict[str, str] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def from_endpoint(
        cls,
        endpoint: str,
        *,
        service_name: str = "animetta",
        max_export_batch_size: int = 512,
        schedule_delay_millis: int = 5000,
    ) -> OTelMirror:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        health_state = _MirrorHealthState()
        exporter = _HealthTrackingExporter(
            OTLPSpanExporter(endpoint=endpoint, timeout=10), health_state
        )
        provider = TracerProvider(
            resource=Resource.create({"service.name": service_name})
        )
        provider.add_span_processor(
            BatchSpanProcessor(
                exporter,
                max_export_batch_size=max_export_batch_size,
                schedule_delay_millis=schedule_delay_millis,
            )
        )
        return cls(
            tracer=provider.get_tracer(service_name),
            provider=provider,
            health_state=health_state,
            batched=True,
        )

    @classmethod
    def from_exporter(
        cls,
        exporter: SpanExporter,
        *,
        service_name: str = "animetta-test",
    ) -> OTelMirror:
        """Build a synchronous mirror for deterministic exporter health tests."""
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor

        health_state = _MirrorHealthState()
        provider = TracerProvider()
        provider.add_span_processor(
            SimpleSpanProcessor(_HealthTrackingExporter(exporter, health_state))
        )
        return cls(
            tracer=provider.get_tracer(service_name),
            provider=provider,
            health_state=health_state,
        )

    @classmethod
    def unavailable(cls, error: BaseException) -> OTelMirror:
        """Represent an enabled mirror whose optional exporter could not start."""
        health_state = _MirrorHealthState()
        health_state.fail(error)
        provider = trace.NoOpTracerProvider()
        return cls(
            tracer=provider.get_tracer("animetta-unavailable-otlp"),
            health_state=health_state,
        )

    async def publish(self, record: CommittedObservation) -> None:
        async with self._lock:
            key = _record_key(record)
            if key in self._seen:
                return
            try:
                self._apply(record)
            except Exception as exc:  # exporter setup/runtime is non-critical
                self._health_state.fail(exc)
                return
            self._remember(key)

    async def health(self) -> ObservationHealth:
        errors, last_error = self._health_state.snapshot()
        return ObservationHealth(
            enabled=True,
            ready=errors == 0,
            degraded=errors > 0,
            writer_errors=errors,
            last_error=last_error,
        )

    async def close(self) -> None:
        provider = self._provider
        if provider is not None:
            await asyncio.to_thread(provider.shutdown)

    def _apply(self, record: CommittedObservation) -> None:
        if isinstance(record, TraceStarted):
            self._trace_spans[record.trace_id] = self._tracer.start_span(
                "conversation",
                start_time=_ns(record.started_at),
                attributes={
                    "animetta.task_id": record.trace_id,
                    "animetta.runtime_profile": record.runtime_profile,
                    "animetta.input_type": record.input_type,
                    "animetta.privacy_mode": record.privacy_mode.value,
                },
            )
            return
        if isinstance(record, TraceFinished):
            span = self._trace_spans.pop(record.trace_id, None)
            if span is not None:
                span.set_attribute("animetta.outcome", record.outcome.value)
                span.set_status(_trace_status(record.outcome, record.error_summary))
                span.end(end_time=_ns(record.finished_at))
            return
        if isinstance(record, OperationStarted):
            parent = (
                self._operation_spans.get(record.parent_operation_id)
                if record.parent_operation_id
                else self._trace_spans.get(record.trace_id)
            )
            context: Context | None = (
                trace.set_span_in_context(parent) if parent is not None else None
            )
            attributes: dict[str, Any] = {
                "animetta.operation_id": record.operation_id,
                "animetta.task_id": record.trace_id,
                "animetta.layer": record.layer.value,
                "animetta.critical_path": record.critical_path,
            }
            if record.provider:
                attributes["animetta.provider"] = record.provider
            if record.model:
                attributes["animetta.model"] = record.model
            attributes.update(_safe_attributes(record.attributes))
            self._operation_spans[record.operation_id] = self._tracer.start_span(
                record.name,
                context=context,
                start_time=_ns(record.started_at),
                attributes=attributes,
            )
            self._operation_trace_ids[record.operation_id] = record.trace_id
            return
        if isinstance(record, OperationFinished):
            span = self._operation_spans.pop(record.operation_id, None)
            self._operation_trace_ids.pop(record.operation_id, None)
            if span is not None:
                span.set_attribute("animetta.status", record.status.value)
                for key, value in _safe_attributes(record.attributes).items():
                    span.set_attribute(key, value)
                span.set_status(_operation_status(record.status, record.error_summary))
                span.end(end_time=_ns(record.finished_at))
            return
        if isinstance(record, ObservationEvent):
            span = (
                self._operation_spans.get(record.operation_id)
                if record.operation_id
                else self._trace_spans.get(record.trace_id)
            )
            if span is not None:
                span.add_event(
                    record.name,
                    {
                        "animetta.direction": record.direction.value,
                        "animetta.phase": record.phase,
                        "animetta.payload_size": record.payload_size,
                        "animetta.identity_valid": record.identity_valid,
                        **_safe_attributes(record.attributes),
                    },
                    timestamp=_ns(record.occurred_at),
                )

    def _remember(self, key: str) -> None:
        self._seen.add(key)
        self._seen_order.append(key)
        while len(self._seen_order) > self._dedup_capacity:
            self._seen.discard(self._seen_order.popleft())


def _safe_attributes(attributes: Any) -> dict[str, str | int | float | bool]:
    result: dict[str, str | int | float | bool] = {}
    for key, value in dict(attributes).items():
        if key not in _SAFE_ATTRIBUTE_KEYS:
            continue
        if isinstance(value, (str, int, float, bool)):
            result[f"animetta.{key}"] = value
    return result


def _trace_status(outcome: TraceOutcome, description: str | None) -> Status:
    if outcome in {TraceOutcome.FAILED, TraceOutcome.ABORTED}:
        return Status(StatusCode.ERROR, description)
    return Status(StatusCode.OK)


def _operation_status(status: OperationStatus, description: str | None) -> Status:
    if status is OperationStatus.ERROR:
        return Status(StatusCode.ERROR, description)
    return Status(StatusCode.OK)


def _record_key(record: CommittedObservation) -> str:
    if isinstance(record, TraceStarted):
        return f"trace:start:{record.trace_id}"
    if isinstance(record, TraceFinished):
        return f"trace:finish:{record.trace_id}"
    if isinstance(record, OperationStarted):
        return f"operation:start:{record.operation_id}"
    if isinstance(record, OperationFinished):
        return f"operation:finish:{record.operation_id}"
    return f"event:{record.event_id}"


def _ns(timestamp: float) -> int:
    return int(timestamp * 1_000_000_000)


class _MirrorHealthState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._errors = 0
        self._last_error: str | None = None

    def fail(self, error: BaseException) -> None:
        with self._lock:
            self._errors += 1
            self._last_error = f"{type(error).__name__}: {error}"[:200]

    def snapshot(self) -> tuple[int, str | None]:
        with self._lock:
            return self._errors, self._last_error


class _HealthTrackingExporter(SpanExporter):
    def __init__(
        self, delegate: SpanExporter, health_state: _MirrorHealthState
    ) -> None:
        self._delegate = delegate
        self._health_state = health_state

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            result = self._delegate.export(spans)
        except Exception as exc:
            self._health_state.fail(exc)
            return SpanExportResult.FAILURE
        if result is not SpanExportResult.SUCCESS:
            self._health_state.fail(RuntimeError("OTLP exporter returned failure"))
        return result

    def shutdown(self) -> None:
        self._delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return self._delegate.force_flush(timeout_millis)
