"""Prometheus projection of records already committed to the local ledger."""

from __future__ import annotations

import asyncio
from collections import deque

from prometheus_client import REGISTRY, CollectorRegistry, Counter, Gauge, Histogram

from ..domain import (
    CommittedObservation,
    ObservationEvent,
    ObservationHealth,
    ObservationLayer,
    OperationFinished,
    OperationStarted,
    TraceFinished,
    TraceStarted,
)


class _LabelLimiter:
    def __init__(self, limit: int) -> None:
        self._limit = max(1, int(limit))
        self._values: dict[str, set[str]] = {}

    def value(self, dimension: str, value: str | None) -> str:
        normalized = str(value or "unknown").strip().lower() or "unknown"
        values = self._values.setdefault(dimension, set())
        if normalized in values:
            return normalized
        if len(values) >= self._limit:
            return "__other__"
        values.add(normalized)
        return normalized

    @property
    def cardinality(self) -> int:
        return sum(len(values) for values in self._values.values())


class PrometheusMirror:
    """Exactly-once, bounded-cardinality Prometheus projection."""

    def __init__(
        self,
        *,
        registry: CollectorRegistry = REGISTRY,
        dynamic_label_limit: int = 64,
        dedup_capacity: int = 16_384,
    ) -> None:
        self.registry = registry
        self._labels = _LabelLimiter(dynamic_label_limit)
        self._dedup_capacity = max(128, int(dedup_capacity))
        self._seen: set[str] = set()
        self._seen_order: deque[str] = deque()
        self._operations: dict[str, OperationStarted] = {}
        self._active_traces: set[str] = set()
        self._lock = asyncio.Lock()
        self._errors = 0
        self._last_error: str | None = None

        self._trace_outcomes = Counter(
            "anima_trace_outcomes_total",
            "Completed canonical traces by typed outcome",
            ("outcome",),
            registry=registry,
        )
        self._active_sessions = Gauge(
            "anima_active_sessions",
            "Canonical traces currently in progress",
            registry=registry,
        )
        self._node_duration = Histogram(
            "anima_node_duration_seconds",
            "Committed LangGraph workflow operation duration",
            ("node_name", "status"),
            registry=registry,
        )
        self._service_duration = Histogram(
            "anima_service_duration_seconds",
            "Committed service operation duration",
            ("service", "operation", "provider", "model", "status"),
            registry=registry,
        )
        self._rag_duration = Histogram(
            "anima_rag_retrieval_duration_seconds",
            "Committed memory retrieval duration",
            ("name", "status"),
            registry=registry,
        )
        self._events = Counter(
            "anima_observation_events_total",
            "Committed observation events",
            ("direction", "name", "phase"),
            registry=registry,
        )
        self._readiness_probe = Counter(
            "anima_readiness_probe_total",
            "Controlled readiness probes emitted by the local runtime",
            registry=registry,
        )

    @property
    def dynamic_label_cardinality(self) -> int:
        return self._labels.cardinality

    async def publish(self, record: CommittedObservation) -> None:
        async with self._lock:
            key = _record_key(record)
            if key in self._seen:
                return
            try:
                self._apply(record)
            except Exception as exc:  # mirrors must never affect the ledger
                self._errors += 1
                self._last_error = f"{type(exc).__name__}: {exc}"[:200]
                return
            self._remember(key)

    async def health(self) -> ObservationHealth:
        return ObservationHealth(
            enabled=True,
            ready=self._errors == 0,
            degraded=self._errors > 0,
            writer_errors=self._errors,
            last_error=self._last_error,
        )

    async def probe(self) -> None:
        """Increment a controlled sample used to verify live metric projection."""
        async with self._lock:
            self._readiness_probe.inc()

    def _apply(self, record: CommittedObservation) -> None:
        if isinstance(record, TraceStarted):
            if record.trace_id not in self._active_traces:
                self._active_traces.add(record.trace_id)
                self._active_sessions.inc()
            return
        if isinstance(record, TraceFinished):
            self._trace_outcomes.labels(outcome=record.outcome.value).inc()
            if record.trace_id in self._active_traces:
                self._active_traces.remove(record.trace_id)
                self._active_sessions.dec()
            return
        if isinstance(record, OperationStarted):
            self._operations[record.operation_id] = record
            return
        if isinstance(record, OperationFinished):
            started = self._operations.pop(record.operation_id, None)
            if started is not None:
                self._observe_operation(started, record)
            return
        if isinstance(record, ObservationEvent):
            self._events.labels(
                direction=record.direction.value,
                name=self._labels.value("event_name", record.name),
                phase=self._labels.value("event_phase", record.phase),
            ).inc()

    def _observe_operation(
        self, started: OperationStarted, finished: OperationFinished
    ) -> None:
        duration = max(0.0, finished.finished_at - started.started_at)
        status = finished.status.value
        if started.layer is ObservationLayer.WORKFLOW:
            self._node_duration.labels(
                node_name=self._labels.value("node_name", started.name),
                status=status,
            ).observe(duration)
        elif started.layer is ObservationLayer.SERVICE:
            service = started.name.split(".", 1)[0]
            self._service_duration.labels(
                service=self._labels.value("service", service),
                operation=self._labels.value("service_operation", started.name),
                provider=self._labels.value("provider", started.provider),
                model=self._labels.value("model", started.model),
                status=status,
            ).observe(duration)
        elif started.layer is ObservationLayer.MEMORY and "recall" in started.name:
            self._rag_duration.labels(
                name=self._labels.value("rag_name", started.name),
                status=status,
            ).observe(duration)

    def _remember(self, key: str) -> None:
        self._seen.add(key)
        self._seen_order.append(key)
        while len(self._seen_order) > self._dedup_capacity:
            self._seen.discard(self._seen_order.popleft())


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
