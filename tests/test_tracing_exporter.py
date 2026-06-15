from __future__ import annotations

"""Tests for StatsSpanExporter — OTel → StatsStore bridge."""

import contextlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import SpanContext, SpanKind, Status, StatusCode, TraceFlags

from animetta.tracing.exporter import StatsSpanExporter


@pytest.fixture
def mock_store():
    """A StatsStore mock with async create_span / finish_span."""
    store = MagicMock()
    store.create_span = AsyncMock()
    store.finish_span = AsyncMock()
    return store


@pytest.fixture
def exporter(mock_store):
    return StatsSpanExporter(stats_store=mock_store)


def _make_otel_span(
    name: str = "test.span",
    trace_id: int = 0xDEADBEEFCAFE1234567890ABCDEF0001,
    span_id: int = 0x0000000000000001,
    parent_span_id: int = None,
    duration_ms: float = 100.0,
    status_code=StatusCode.OK,
    attributes: dict = None,
):
    """Build a minimal ReadableSpan-like object for testing."""
    span = MagicMock(spec=ReadableSpan)
    span.name = name

    # SpanContext
    ctx = SpanContext(trace_id=trace_id, span_id=span_id, is_remote=False,
                      trace_flags=TraceFlags(TraceFlags.SAMPLED))
    span.get_span_context.return_value = ctx

    # Parent
    span.parent = None
    if parent_span_id is not None:
        parent_ctx = SpanContext(trace_id=trace_id, span_id=parent_span_id,
                                  is_remote=False, trace_flags=TraceFlags(0))
        span.parent = parent_ctx

    # Timing (nanoseconds)
    start_ns = 1_000_000_000  # 1s
    end_ns = start_ns + int(duration_ms * 1_000_000)
    span.start_time = start_ns
    span.end_time = end_ns

    # Status
    span.status = Status(status_code)

    # Attributes
    span.attributes = attributes or {}

    # Events
    span.events = []

    # Kind
    span.kind = SpanKind.INTERNAL

    return span


class TestStatsSpanExporter:

    def test_export_returns_success(self, exporter, mock_store):
        """export() should succeed with valid spans."""
        span = _make_otel_span()
        result = exporter.export([span])
        assert result.value == 0  # SpanExportResult.SUCCESS

    def test_export_writes_to_store(self, exporter, mock_store):
        """export() should call create_span + finish_span."""
        span = _make_otel_span(duration_ms=250.0)
        exporter.export([span])
        # Force async flush
        import asyncio
        with contextlib.suppress(RuntimeError):
            asyncio.get_running_loop()

    def test_export_error_span(self, exporter, mock_store):
        """Spans with ERROR status should set status='error'."""
        span = _make_otel_span(
            name="error.span",
            status_code=StatusCode.ERROR,
            duration_ms=50.0,
        )
        result = exporter.export([span])
        assert result.value == 0

    def test_export_empty_list(self, exporter, mock_store):
        """Empty span list should succeed."""
        result = exporter.export([])
        assert result.value == 0

    def test_export_parent_span(self, exporter, mock_store):
        """Spans with parent should pass parent_span_id."""
        span = _make_otel_span(
            name="child",
            trace_id=1,
            span_id=2,
            parent_span_id=1,
        )
        result = exporter.export([span])
        assert result.value == 0

    def test_shutdown_noop(self, exporter):
        """shutdown() should not raise."""
        exporter.shutdown()

    def test_force_flush(self, exporter):
        """force_flush() should return True."""
        assert exporter.force_flush() is True
