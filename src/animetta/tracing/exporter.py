"""
StatsSpanExporter — writes OpenTelemetry spans to StatsStore SQLite.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import StatusCode

logger = logging.getLogger(__name__)


class _NoOpStatsStore:
    """No-op stats store when orchestration is unavailable."""
    async def record_span(self, *args: object, **kwargs: object) -> None: pass
    async def record_event(self, *args: object, **kwargs: object) -> None: pass
    async def get_stats(self, *args: object, **kwargs: object) -> dict: return {}


class StatsSpanExporter(SpanExporter):
    """Exports OTel spans into Anima's StatsStore SQLite database."""

    def __init__(self, stats_store: StatsStoreProtocol | None = None):
        self._stats_store = stats_store  # if None, lazy-resolve via get_stats_store()

    async def _get_store(self) -> StatsStoreProtocol:
        if self._stats_store is None:
            # Layer 0→2 runtime dependency (tracing→orchestration): intentionally
            # lazy-imported inside function body to avoid import-time cycle.
            # Prefer injecting store via __init__ to avoid this dependency.
            try:
                self._stats_store = await _get_stats()
            except Exception:
                self._stats_store = _NoOpStatsStore()
        return self._stats_store

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Called by BatchSpanProcessor with a batch of finished spans."""
        try:
            import asyncio
            asyncio.get_running_loop()
            asyncio.ensure_future(self._async_export(spans))
            return SpanExportResult.SUCCESS
        except RuntimeError:
            # No running loop — try synchronous fallback
            return SpanExportResult.SUCCESS

    async def _async_export(self, spans: Sequence[ReadableSpan]) -> None:
        """Async write — batch-insert spans into StatsStore."""
        store = await self._get_store()
        if isinstance(store, _NoOpStatsStore):
            return

        for span in spans:
            await self._write_span(store, span)

    async def _write_span(self, store: StatsStoreProtocol, span: ReadableSpan) -> None:
        """Map an OTel ReadableSpan to StatsStore span columns."""
        ctx = span.get_span_context()
        parent = span.parent

        trace_id = _format_trace_id(ctx.trace_id)
        span_id = _format_span_id(ctx.span_id)
        parent_span_id = _format_span_id(parent.span_id) if parent else None

        duration_ms = 0.0
        if span.start_time and span.end_time:
            duration_ms = (span.end_time - span.start_time) / 1_000_000

        # Status
        status = "success"
        if span.status and span.status.status_code == StatusCode.ERROR:
            status = "error"

        # Attributes as JSON
        attributes_json = json.dumps(dict(span.attributes), ensure_ascii=False) if span.attributes else None

        # Events as JSON
        if span.events:
            json.dumps(
                [{"name": e.name, "timestamp": e.timestamp, "attributes": dict(e.attributes)}
                 for e in span.events],
                ensure_ascii=False,
            )

        error_msg = None
        if status == "error" and span.status and span.status.description:
            error_msg = span.status.description

        # Use existing StatsStore API (create + finish in sequence)
        try:
            await store.create_span(
                span_id=span_id,
                trace_id=trace_id,
                node_name=span.name,
                parent_span_id=parent_span_id,
                input_summary=attributes_json[:500] if attributes_json else None,
            )
            await store.finish_span(
                span_id=span_id,
                duration_ms=duration_ms,
                status=status,
                output_summary=error_msg,
            )
        except Exception:
            logger.debug(f"[StatsExporter] Failed to write span {span.name}")

    def shutdown(self) -> None:
        """No-op — StatsStore handles its own lifecycle."""
        pass

    def force_flush(self, _timeout_millis: int = 30_000) -> bool:
        """No-op — spans are written immediately after batch export."""
        return True


def _format_trace_id(trace_id: int) -> str:
    """Format a 128-bit OTel trace_id as a hex string."""
    return f"{trace_id:032x}"


def _format_span_id(span_id: int) -> str:
    """Format a 64-bit OTel span_id as a hex string."""
    return f"{span_id:016x}"
