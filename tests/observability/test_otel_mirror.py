from __future__ import annotations

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from animetta.observability.domain import (
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
from animetta.observability.mirrors.otel import OTelMirror


def _provider() -> tuple[TracerProvider, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


async def test_otel_mirror_exports_one_hierarchical_trace() -> None:
    provider, exporter = _provider()
    mirror = OTelMirror(tracer=provider.get_tracer("test"))
    started = TraceStarted(
        identity=TraceIdentity("message-1", "conversation-1", "task-1", "session-1"),
        runtime_profile="golden",
        input_type="text",
        privacy_mode=PrivacyMode.REDACTED,
        started_at=10.0,
    )
    parent = OperationStarted(
        "parent-1",
        "task-1",
        None,
        ObservationLayer.WORKFLOW,
        "llm_node",
        True,
        11.0,
    )
    child = OperationStarted(
        "child-1",
        "task-1",
        "parent-1",
        ObservationLayer.SERVICE,
        "llm.chat",
        True,
        11.25,
        provider="openai",
        model="gpt-test",
        attributes={"prompt": "must-not-export", "attempt": 1},
    )
    for record in (
        started,
        parent,
        child,
        OperationFinished("child-1", OperationStatus.SUCCESS, 11.75),
        OperationFinished("parent-1", OperationStatus.SUCCESS, 12.0),
        TraceFinished("task-1", TraceOutcome.SUCCESS, 12.0),
    ):
        await mirror.publish(record)

    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert set(spans) == {"conversation", "llm_node", "llm.chat"}
    assert spans["llm.chat"].parent.span_id == spans["llm_node"].context.span_id
    assert spans["llm_node"].parent.span_id == spans["conversation"].context.span_id
    assert len({span.context.trace_id for span in spans.values()}) == 1
    assert spans["llm.chat"].attributes["animetta.provider"] == "openai"
    assert "prompt" not in spans["llm.chat"].attributes


async def test_otel_mirror_failure_is_degraded_and_non_recursive() -> None:
    class FailingTracer:
        def start_span(self, *_args, **_kwargs):
            raise ConnectionError("collector unreachable")

    mirror = OTelMirror(tracer=FailingTracer())
    await mirror.publish(
        TraceStarted(
            TraceIdentity("message-1", "conversation-1", "task-1", "session-1"),
            "development",
            "text",
            PrivacyMode.FULL,
            10.0,
        )
    )

    health = await mirror.health()
    assert health.ready is False
    assert health.degraded is True
    assert health.writer_errors == 1
    assert "ConnectionError" in (health.last_error or "")


async def test_otel_exporter_failure_updates_health_without_raising() -> None:
    class UnreachableExporter(SpanExporter):
        def export(self, _spans):
            return SpanExportResult.FAILURE

        def shutdown(self) -> None:
            return None

    mirror = OTelMirror.from_exporter(UnreachableExporter())
    started = TraceStarted(
        TraceIdentity("message-1", "conversation-1", "task-1", "session-1"),
        "production",
        "text",
        PrivacyMode.REDACTED,
        10.0,
    )
    await mirror.publish(started)
    await mirror.publish(TraceFinished(started.trace_id, TraceOutcome.SUCCESS, finished_at=11.0))

    health = await mirror.health()
    assert health.degraded is True
    assert health.writer_errors == 1
    assert "returned failure" in (health.last_error or "")
    await mirror.close()


async def test_endpoint_mirror_uses_batch_processor() -> None:
    pytest.importorskip("opentelemetry.exporter.otlp.proto.grpc.trace_exporter")
    mirror = OTelMirror.from_endpoint(
        "http://127.0.0.1:9",
        max_export_batch_size=8,
        schedule_delay_millis=100,
    )
    assert mirror.batched is True
    await mirror.close()
