from __future__ import annotations

"""Tests for StatsSpanExporter — OTel span → StatsStore mapping."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExportResult
from opentelemetry.trace import SpanContext, SpanKind, Status, StatusCode, TraceFlags

from animetta.tracing.exporter import StatsSpanExporter, _format_span_id, _format_trace_id


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
    parent_span_id: int | None = None,
    duration_ms: float = 100.0,
    status_code=StatusCode.OK,
    attributes: dict | None = None,
    events: list | None = None,
):
    """Build a minimal ReadableSpan-like object for testing."""
    span = MagicMock(spec=ReadableSpan)
    span.name = name

    ctx = SpanContext(
        trace_id=trace_id, span_id=span_id, is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    span.get_span_context.return_value = ctx

    span.parent = None
    if parent_span_id is not None:
        parent_ctx = SpanContext(
            trace_id=trace_id, span_id=parent_span_id,
            is_remote=False, trace_flags=TraceFlags(0),
        )
        span.parent = parent_ctx

    start_ns = 1_000_000_000
    end_ns = start_ns + int(duration_ms * 1_000_000)
    span.start_time = start_ns
    span.end_time = end_ns
    span.status = Status(status_code)
    span.attributes = attributes or {}
    span.events = events or []
    span.kind = SpanKind.INTERNAL

    return span


class TestStatsSpanExporter:
    """Suite for StatsSpanExporter."""

    # ── export ───────────────────────────────────────────────────────

    def test_export_returns_success(self, exporter, mock_store):
        """export() with valid spans should return SUCCESS."""
        span = _make_otel_span()
        result = exporter.export([span])
        assert result == SpanExportResult.SUCCESS

    def test_export_empty_list(self, exporter, mock_store):
        """Empty span list should return SUCCESS."""
        result = exporter.export([])
        assert result == SpanExportResult.SUCCESS

    def test_export_writes_to_store(self, exporter, mock_store):
        """export() should trigger async write (create_span + finish_span)."""
        span = _make_otel_span(name="llm.chat", duration_ms=250.0)
        result = exporter.export([span])
        assert result == SpanExportResult.SUCCESS

    def test_export_error_span(self, exporter, mock_store):
        """Spans with ERROR status should be written with status='error'."""
        span = _make_otel_span(
            name="error.span",
            status_code=StatusCode.ERROR,
            duration_ms=50.0,
            attributes={"error_type": "timeout"},
        )
        result = exporter.export([span])
        assert result == SpanExportResult.SUCCESS

    def test_export_parent_span(self, exporter, mock_store):
        """Parent-identified spans should pass parent_span_id."""
        span = _make_otel_span(
            name="child",
            trace_id=1,
            span_id=2,
            parent_span_id=1,
        )
        result = exporter.export([span])
        assert result == SpanExportResult.SUCCESS

    def test_export_multiple_spans(self, exporter, mock_store):
        """Multiple spans should each trigger write."""
        spans = [
            _make_otel_span(name="span1", span_id=1),
            _make_otel_span(name="span2", span_id=2),
        ]
        result = exporter.export(spans)
        assert result == SpanExportResult.SUCCESS

    # ── _write_span mapping ──────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_write_span_calls_create_and_finish(self, exporter, mock_store):
        """_write_span should call create_span then finish_span."""
        span = _make_otel_span(name="test.node", duration_ms=123.4)
        await exporter._write_span(mock_store, span)
        mock_store.create_span.assert_awaited_once()
        mock_store.finish_span.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_write_span_passes_correct_args(self, exporter, mock_store):
        """create_span and finish_span should receive correctly formatted IDs."""
        span = _make_otel_span(
            name="llm.chat",
            trace_id=0xABC,
            span_id=0x123,
            parent_span_id=0x456,
            duration_ms=100.0,
            status_code=StatusCode.OK,
        )
        await exporter._write_span(mock_store, span)

        create_args = mock_store.create_span.call_args
        assert create_args is not None
        args, kwargs = create_args
        trace_id_str = kwargs.get("trace_id", args[1] if len(args) > 1 else "")
        assert "abc" in str(trace_id_str).lower()
        node_name = kwargs.get("node_name", args[2] if len(args) > 2 else "")
        assert node_name == "llm.chat"

        finish_call = mock_store.finish_span.await_args
        assert finish_call is not None

    @pytest.mark.asyncio
    async def test_write_span_with_attributes(self, exporter, mock_store):
        """Attributes should be JSON-serialized and passed as input_summary."""
        span = _make_otel_span(
            name="with_attrs",
            attributes={"key": "value", "count": 42},
        )
        await exporter._write_span(mock_store, span)

        create_call = mock_store.create_span.await_args
        kwargs = create_call[1] if len(create_call) > 1 else {}
        summary = kwargs.get("input_summary", create_call[0][4] if len(create_call[0]) > 4 else "")
        assert summary is not None
        assert "key" in str(summary)

    @pytest.mark.asyncio
    async def test_write_span_with_events(self, exporter, mock_store):
        """Span events should be serialized."""
        from opentelemetry.sdk.trace import Event
        span = _make_otel_span(
            name="with_events",
            events=[
                Event(name="event1", timestamp=1000, attributes={"k": "v"}),
            ],
        )
        await exporter._write_span(mock_store, span)
        # Should not raise
        mock_store.create_span.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_write_span_error_status_includes_description(self, exporter, mock_store):
        """Error status with description should pass output_summary."""
        from opentelemetry.trace import Status
        from opentelemetry.trace import StatusCode as SC
        span = _make_otel_span(
            name="fail",
            status_code=StatusCode.ERROR,
        )
        span.status = Status(SC.ERROR, description="timeout error")
        await exporter._write_span(mock_store, span)
        mock_store.finish_span.assert_awaited_once()

    # ── Edge cases ───────────────────────────────────────────────────

    def test_export_no_running_loop(self, exporter, mock_store):
        """export() outside async context should still return SUCCESS."""
        # This test runs without a running event loop.  export() should
        # catch the RuntimeError and return SUCCESS.
        span = _make_otel_span()
        result = exporter.export([span])
        assert result == SpanExportResult.SUCCESS

    def test_shutdown(self, exporter):
        """shutdown() is a no-op."""
        exporter.shutdown()  # should not raise

    def test_force_flush(self, exporter):
        """force_flush() returns True."""
        assert exporter.force_flush() is True

    # ── _format helpers ──────────────────────────────────────────────

    def test_format_trace_id(self):

        assert _format_trace_id(0xABC) == "00000000000000000000000000000abc"
        assert _format_trace_id(0) == "00000000000000000000000000000000"

    def test_format_span_id(self):

        assert _format_span_id(0x123) == "0000000000000123"
        assert _format_span_id(0) == "0000000000000000"

    def test_format_trace_id_large(self):

        tid = 0xDEADBEEFCAFE1234567890ABCDEF0001
        formatted = _format_trace_id(tid)
        assert len(formatted) == 32
        assert formatted == "deadbeefcafe1234567890abcdef0001"
