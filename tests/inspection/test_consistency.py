from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from loguru import logger

from animetta.inspection.checks.consistency import (
    check_data_consistency,
    chroma_responds,
    has_trace_in_last,
    observation_ledger_responds,
)
from animetta.inspection.runtime import InspectionRuntime
from animetta.observability.domain import ObservationHealth


def _runtime() -> InspectionRuntime:
    query = MagicMock()
    query.observation_health = AsyncMock(return_value=ObservationHealth(True, True, False))
    query.overview = AsyncMock(return_value={"schema_version": 2})
    query.recent_traces = AsyncMock(return_value=[{"trace_id": "task-1"}])
    memory = MagicMock()
    memory.health = AsyncMock(return_value={"ready": True, "last_error": None})
    return InspectionRuntime(
        observation_query=query,
        report_store=MagicMock(),
        memory_runtime=memory,
        readiness_snapshot=MagicMock(),
        metrics_snapshot=MagicMock(),
    )


async def test_canonical_ledger_and_memory_runtime_respond() -> None:
    runtime = _runtime()
    assert await observation_ledger_responds(runtime) is True
    assert await has_trace_in_last(60, runtime) is True
    assert await chroma_responds(runtime) is True


async def test_missing_injection_fails_closed() -> None:
    assert await observation_ledger_responds() is False
    assert await has_trace_in_last(60) is False
    assert await chroma_responds() is False
    assert (await check_data_consistency()).ok is False


async def test_no_recent_trace_is_diagnostic_only() -> None:
    runtime = _runtime()
    runtime.observation_query.recent_traces.return_value = []
    result = await check_data_consistency(runtime)
    assert result.ok is True
    assert result.detail["has_recent_trace"] is False


async def test_runtime_error_is_reported_without_private_database_probe() -> None:
    runtime = _runtime()
    runtime.memory_runtime.health.return_value = {
        "ready": False,
        "last_error": "index_failed",
    }
    result = await check_data_consistency(runtime)
    assert result.ok is False
    assert result.detail["memory_runtime_ok"] is False


# ── Probe-failure diagnostics (P1-3) ─────────────────────────────────────────


@pytest.mark.parametrize(
    "probe_fn, setup",
    [
        (
            # observation_ledger_responds(runtime)
            lambda r: observation_ledger_responds(r),
            lambda r: setattr(
                r.observation_query,
                "observation_health",
                AsyncMock(side_effect=RuntimeError("boom")),
            ),
        ),
        (
            # has_trace_in_last(minutes, runtime) — note the leading minutes arg
            lambda r: has_trace_in_last(60, r),
            lambda r: setattr(
                r.observation_query, "recent_traces", AsyncMock(side_effect=RuntimeError("boom"))
            ),
        ),
        (
            # chroma_responds(runtime)
            lambda r: chroma_responds(r),
            lambda r: setattr(
                r.memory_runtime, "health", AsyncMock(side_effect=RuntimeError("boom"))
            ),
        ),
    ],
)
async def test_probe_exception_logs_warning_and_returns_false(probe_fn, setup) -> None:
    """When a probe dependency raises, the check must log the root cause.

    Regression: previously these three probes swallowed every exception
    silently and returned False, making inspection failures invisible.
    The check still returns False (degraded), but the failure is now visible
    in logs instead of disappearing.
    """
    runtime = _runtime()
    setup(runtime)

    # Capture loguru output via a temporary in-memory sink. Loguru does not
    # route through stdlib ``logging`` by default, so pytest's ``caplog``
    # fixture cannot see it.
    captured: list[str] = []

    def _sink(message) -> None:
        captured.append(str(message))

    handler_id = logger.add(_sink, level="WARNING")
    try:
        result = await probe_fn(runtime)
    finally:
        logger.remove(handler_id)

    assert result is False
    assert any("probe failed" in line and "boom" in line for line in captured)
