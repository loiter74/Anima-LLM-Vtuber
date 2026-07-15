from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

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
