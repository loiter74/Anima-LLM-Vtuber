from __future__ import annotations

"""Tests for context.py — attach/detach_trace_context with OTel."""

from opentelemetry import trace as otel_trace

from animetta.tracing.context import (
    _make_otel_span_context,
    _uuid_to_otel_trace_id,
    attach_trace_context,
    detach_trace_context,
)


class TestTraceContext:
    """Suite for attach/detach_trace_context."""

    # ── attach_trace_context ─────────────────────────────────────────

    def test_attach_with_valid_uuid(self):
        """A valid UUID string should produce a token."""

        token = attach_trace_context("123e4567-e89b-12d3-a456-426614174000")
        assert token is not None
        # Clean up
        detach_trace_context(token)

    def test_attach_with_empty_string(self):
        """Empty string should return None."""

        assert attach_trace_context("") is None
        assert attach_trace_context(None) is None

    def test_attach_invalid_uuid(self):
        """Invalid UUID should return None gracefully."""

        result = attach_trace_context("not-a-uuid")
        # Depending on implementation, this may return None if parsing fails
        assert result is None

    def test_attach_sets_otel_context(self):
        """After attach, the current OTel span context should contain our trace_id."""

        token = attach_trace_context("00000000-0000-0000-0000-000000000001")
        assert token is not None
        # The current span should reflect our context
        span = otel_trace.get_current_span()
        ctx = span.get_span_context()
        assert ctx.trace_id == 1
        detach_trace_context(token)

    # ── detach_trace_context ─────────────────────────────────────────

    def test_detach_with_none(self):
        """detach with None should not raise."""

        detach_trace_context(None)  # no-op, should not raise

    def test_detach_restores_previous_context(self):
        """After detach, the previous empty context should be restored."""

        token = attach_trace_context("123e4567-e89b-12d3-a456-426614174000")
        assert token is not None
        # Detach restores previous context
        detach_trace_context(token)
        # After detach, get_current_span should return a non-recording span
        span = otel_trace.get_current_span()
        # The default should be an invalid context
        ctx = span.get_span_context()
        assert ctx.trace_id != 0x123e4567e89b12d3a456426614174000

    # ── _uuid_to_otel_trace_id ───────────────────────────────────────

    def test_uuid_to_otel_trace_id(self):
        """UUID string converts correctly to a 128-bit int."""

        # UUID "00000000-0000-0000-0000-000000000001" → int 1
        assert _uuid_to_otel_trace_id("00000000-0000-0000-0000-000000000001") == 1

        # Known test vector
        uuid_str = "123e4567-e89b-12d3-a456-426614174000"
        result = _uuid_to_otel_trace_id(uuid_str)
        assert isinstance(result, int)
        assert result > 0

    # ── _make_otel_span_context ──────────────────────────────────────

    def test_make_otel_span_context(self):
        """Should produce a SpanContext with trace_id, non-recording."""

        sc = _make_otel_span_context(42)
        assert sc.trace_id == 42
        assert sc.span_id == 0  # non-recording
        assert sc.is_remote is False

    # ── Round-trip integration ───────────────────────────────────────

    def test_attach_detach_round_trip(self):
        """Full attach → verify → detach cycle should work cleanly."""

        uuid_str = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        expected_tid = int(uuid_str.replace("-", ""), 16)

        token = attach_trace_context(uuid_str)
        assert token is not None

        span = otel_trace.get_current_span()
        ctx = span.get_span_context()
        assert ctx.trace_id == expected_tid

        detach_trace_context(token)

        # After detach, should be back to default
        span2 = otel_trace.get_current_span()
        ctx2 = span2.get_span_context()
        assert ctx2.trace_id != expected_tid
