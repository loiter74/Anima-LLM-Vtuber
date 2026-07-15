"""Explicit runtime dependencies for inspection checks and persistence."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from animetta.observability.ports import (
    ObservationQuery,
    ObservationReportStore,
)


@dataclass(frozen=True, slots=True)
class InspectionRuntime:
    observation_query: ObservationQuery
    report_store: ObservationReportStore
    memory_runtime: Any
    readiness_snapshot: Callable[[], Any]
    metrics_snapshot: Callable[[], str]
    observation_write_probe: Callable[[], Awaitable[None]] | None = None
    remote_tts_probe: Callable[[], Awaitable[dict[str, Any]]] | None = None
