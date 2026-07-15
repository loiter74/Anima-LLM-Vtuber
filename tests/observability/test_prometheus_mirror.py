from __future__ import annotations

import asyncio

import pytest
from prometheus_client import CollectorRegistry, generate_latest

from animetta.observability.domain import (
    ObservationHealth,
    ObservationLayer,
    OperationFinished,
    OperationStarted,
    OperationStatus,
    PrivacyMode,
    TraceFinished,
    TraceIdentity,
    TraceOutcome,
    TraceStarted,
)
from animetta.observability.ledger import SQLiteObservationLedger
from animetta.observability.mirrors.prometheus import PrometheusMirror


def _trace_started(trace_id: str = "task-1") -> TraceStarted:
    return TraceStarted(
        identity=TraceIdentity("message-1", "conversation-1", trace_id, "session-1"),
        runtime_profile="development",
        input_type="text",
        privacy_mode=PrivacyMode.FULL,
        started_at=10.0,
    )


def _operation(
    operation_id: str,
    *,
    layer: ObservationLayer,
    name: str,
    provider: str | None = None,
    model: str | None = None,
    started_at: float = 11.0,
) -> OperationStarted:
    return OperationStarted(
        operation_id=operation_id,
        trace_id="task-1",
        parent_operation_id=None,
        layer=layer,
        name=name,
        critical_path=True,
        started_at=started_at,
        provider=provider,
        model=model,
    )


async def test_prometheus_mirror_counts_each_committed_record_once() -> None:
    registry = CollectorRegistry()
    mirror = PrometheusMirror(registry=registry)
    started = _trace_started()
    workflow = _operation("workflow-1", layer=ObservationLayer.WORKFLOW, name="llm_node")
    finished = OperationFinished("workflow-1", OperationStatus.SUCCESS, finished_at=12.5)

    for record in (started, started, workflow, workflow, finished, finished):
        await mirror.publish(record)
    trace_finished = TraceFinished("task-1", TraceOutcome.DEGRADED, finished_at=13.0)
    await mirror.publish(trace_finished)
    await mirror.publish(trace_finished)

    metrics = generate_latest(registry).decode()
    assert "anima_active_sessions 0.0" in metrics
    assert 'anima_trace_outcomes_total{outcome="degraded"} 1.0' in metrics
    assert 'anima_node_duration_seconds_count{node_name="llm_node",status="success"} 1.0' in metrics


async def test_prometheus_mirror_records_service_and_rag_durations() -> None:
    registry = CollectorRegistry()
    mirror = PrometheusMirror(registry=registry)
    await mirror.publish(_trace_started())

    records = [
        _operation(
            "service-1",
            layer=ObservationLayer.SERVICE,
            name="llm.chat",
            provider="openai",
            model="gpt-test",
        ),
        OperationFinished("service-1", OperationStatus.ERROR, finished_at=12.0),
        _operation(
            "rag-1",
            layer=ObservationLayer.MEMORY,
            name="memory.recall",
            started_at=12.0,
        ),
        OperationFinished("rag-1", OperationStatus.SUCCESS, finished_at=12.25),
    ]
    for record in records:
        await mirror.publish(record)

    metrics = generate_latest(registry).decode()
    assert (
        'anima_service_duration_seconds_count{model="gpt-test",operation="llm.chat",provider="openai",service="llm",status="error"} 1.0'
        in metrics
    )
    assert (
        'anima_rag_retrieval_duration_seconds_count{name="memory.recall",status="success"} 1.0'
        in metrics
    )


async def test_prometheus_mirror_bounds_dynamic_label_cardinality() -> None:
    mirror = PrometheusMirror(
        registry=CollectorRegistry(),
        dynamic_label_limit=2,
    )
    await mirror.publish(_trace_started())
    for index in range(5):
        operation_id = f"service-{index}"
        await mirror.publish(
            _operation(
                operation_id,
                layer=ObservationLayer.SERVICE,
                name=f"provider-{index}.chat",
                provider=f"provider-{index}",
                model=f"model-{index}",
            )
        )
        await mirror.publish(OperationFinished(operation_id, OperationStatus.SUCCESS, 12.0 + index))

    # Four dynamic service dimensions, each capped independently at two values.
    assert mirror.dynamic_label_cardinality <= 8
    assert "__other__" in generate_latest(mirror.registry).decode()


@pytest.mark.parametrize("outcome", list(TraceOutcome))
async def test_prometheus_mirror_exposes_all_typed_outcomes(
    outcome: TraceOutcome,
) -> None:
    registry = CollectorRegistry()
    mirror = PrometheusMirror(registry=registry)
    started = _trace_started(trace_id=f"task-{outcome.value}")
    await mirror.publish(started)
    await mirror.publish(TraceFinished(started.trace_id, outcome, finished_at=11.0))
    assert (
        f'anima_trace_outcomes_total{{outcome="{outcome.value}"}} 1.0'
        in generate_latest(registry).decode()
    )


async def test_controlled_delta_happens_only_after_ledger_commit(tmp_path) -> None:
    registry = CollectorRegistry()
    mirror = PrometheusMirror(registry=registry)
    ledger = SQLiteObservationLedger(tmp_path / "observations.db", mirrors=(mirror,))
    await ledger.start()
    before = generate_latest(registry)

    await ledger.start_trace(_trace_started())
    await ledger.flush()
    for _ in range(10):
        if generate_latest(registry) != before:
            break
        await asyncio.sleep(0)

    after = generate_latest(registry)
    assert after != before
    assert b"anima_active_sessions 1.0" in after
    await ledger.close()


async def test_mirror_failure_degrades_health_without_blocking_or_recursing(
    tmp_path,
) -> None:
    class FailingMirror:
        async def publish(self, _record) -> None:
            raise ConnectionError("mirror unavailable")

        async def health(self) -> ObservationHealth:
            return ObservationHealth(enabled=True, ready=True, degraded=False)

    ledger = SQLiteObservationLedger(tmp_path / "observations.db", mirrors=(FailingMirror(),))
    await ledger.start()
    await asyncio.wait_for(ledger.start_trace(_trace_started()), timeout=0.5)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    health = await ledger.health()
    detail = await ledger.trace_detail("task-1")
    assert health.degraded is True
    assert health.writer_errors == 1
    assert "ConnectionError" in (health.last_error or "")
    assert detail is not None
    assert detail["events"] == []
    await ledger.close()
