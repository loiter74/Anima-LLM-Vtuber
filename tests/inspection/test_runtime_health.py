from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from animetta.inspection.checks.health import check_all_components
from animetta.inspection.models import CheckResult, InspectionReport
from animetta.inspection.reporter import store_report
from animetta.inspection.runtime import InspectionRuntime
from animetta.observability.domain import ObservationHealth


def _runtime() -> InspectionRuntime:
    metric_probe_count = 0

    async def observation_write_probe() -> None:
        nonlocal metric_probe_count
        metric_probe_count += 1

    query = MagicMock()
    query.observation_health = AsyncMock(
        return_value=ObservationHealth(True, True, False, queue_depth=0)
    )
    query.overview = AsyncMock(return_value={"schema_version": 2})
    memory = MagicMock()
    memory.health = AsyncMock(
        return_value={
            "ready": True,
            "ingestion_queue_depth": 0,
            "index_backlog": 0,
            "ingestion_failed": 0,
            "last_error": None,
        }
    )
    readiness = MagicMock()
    readiness.to_dict.return_value = {
        "ready": True,
        "profile": "golden",
        "components": {
            "llm": {
                "ready": True,
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
            },
            "tts": {"ready": True, "provider": "qwen3"},
        },
    }
    return InspectionRuntime(
        observation_query=query,
        report_store=MagicMock(),
        memory_runtime=memory,
        readiness_snapshot=lambda: readiness,
        metrics_snapshot=lambda: (
            "anima_active_sessions 0\n"
            'anima_trace_outcomes_total{outcome="success"} 1\n'
            f"anima_readiness_probe_total {metric_probe_count}\n"
        ),
        observation_write_probe=observation_write_probe,
    )


async def test_component_health_uses_injected_runtime_ports() -> None:
    runtime = _runtime()
    results = await check_all_components(runtime)

    assert set(results) == {
        "observation_ledger",
        "service_pool",
        "memory_runtime",
        "metrics_projection",
    }
    assert all(result.ok for result in results.values())
    assert results["service_pool"].detail["llm_provider"] == "deepseek"
    runtime.observation_query.overview.assert_awaited_once()
    runtime.memory_runtime.health.assert_awaited_once()


async def test_component_health_fails_closed_for_uninitialized_runtime() -> None:
    results = await check_all_components(None)
    assert results["inspection_runtime"].ok is False
    assert "not configured" in (results["inspection_runtime"].error or "")


async def test_memory_backlog_and_errors_are_reported_as_degraded() -> None:
    runtime = _runtime()
    runtime.memory_runtime.health.return_value = {
        "ready": True,
        "ingestion_queue_depth": 3,
        "index_backlog": 2,
        "ingestion_failed": 1,
        "last_error": "IndexError",
    }
    results = await check_all_components(runtime)
    result = results["memory_runtime"]
    assert result.ok is False
    assert result.detail["index_backlog"] == 2
    assert result.detail["ingestion_failed"] == 1


async def test_healthy_memory_backlog_remains_ready_while_work_is_in_flight() -> None:
    runtime = _runtime()
    runtime.memory_runtime.health.return_value = {
        "ready": True,
        "degraded": False,
        "ingestion_queue_depth": 3,
        "index_backlog": 2,
        "ingestion_failed": 0,
        "last_error": None,
    }

    result = (await check_all_components(runtime))["memory_runtime"]

    assert result.ok is True
    assert result.detail["ingestion_queue_depth"] == 3
    assert result.detail["index_backlog"] == 2


async def test_observation_read_only_probe_fails_component_health() -> None:
    runtime = _runtime()
    read_only_runtime = InspectionRuntime(
        observation_query=runtime.observation_query,
        report_store=runtime.report_store,
        memory_runtime=runtime.memory_runtime,
        readiness_snapshot=runtime.readiness_snapshot,
        metrics_snapshot=runtime.metrics_snapshot,
        observation_write_probe=AsyncMock(side_effect=PermissionError("read only")),
    )

    result = (await check_all_components(read_only_runtime))["observation_ledger"]

    assert result.ok is False


async def test_unchanged_metrics_fail_component_health() -> None:
    runtime = _runtime()
    unchanged_runtime = InspectionRuntime(
        observation_query=runtime.observation_query,
        report_store=runtime.report_store,
        memory_runtime=runtime.memory_runtime,
        readiness_snapshot=runtime.readiness_snapshot,
        metrics_snapshot=lambda: "anima_readiness_probe_total 1\n",
        observation_write_probe=AsyncMock(),
    )

    result = (await check_all_components(unchanged_runtime))["metrics_projection"]

    assert result.ok is False
    assert result.detail["anima_readiness_probe_total_delta"] == 0


async def test_inspection_report_persists_through_report_port() -> None:
    report_store = MagicMock()
    report_store.store_inspection_report = AsyncMock()
    report = InspectionReport(
        started_at=10.0,
        finished_at=11.0,
        checks={"ledger": CheckResult.passed("ledger")},
    )
    await store_report(report, report_store)

    payload = report_store.store_inspection_report.await_args.args[0]
    assert payload["run_id"] == report.run_id
    assert payload["overall_ok"] is True
    assert payload["checks"]["ledger"]["ok"] is True
