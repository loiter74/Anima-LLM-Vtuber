from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import CollectorRegistry, generate_latest

from animetta.core.component_readiness import ComponentReadinessCache
from animetta.inspection.runtime import InspectionRuntime
from animetta.observability.domain import ObservationHealth
from animetta.observability.ledger import SQLiteObservationLedger
from animetta.observability.mirrors import PrometheusMirror


def runtime() -> InspectionRuntime:
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
            "degraded": False,
            "index_backlog": 0,
            "ingestion_queue": 0,
            "ingestion_failed": 0,
            "last_error": None,
        }
    )
    readiness = MagicMock()
    readiness.to_dict.return_value = {
        "ready": True,
        "profile": "production",
        "components": {},
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


def test_cache_fails_closed_before_first_refresh() -> None:
    snapshot = ComponentReadinessCache(runtime()).snapshot()

    assert snapshot["ready"] is False
    assert all(
        component["reason"] == "cache_unavailable"
        for component in snapshot["components"].values()
    )


async def test_cache_publishes_only_sanitized_required_component_results() -> None:
    cache = ComponentReadinessCache(runtime())

    await cache.refresh()
    snapshot = cache.snapshot()

    assert snapshot["ready"] is True
    assert set(snapshot["components"]) == {
        "observation_ledger",
        "memory_runtime",
        "metrics_projection",
    }
    assert all(component["ready"] for component in snapshot["components"].values())


@pytest.mark.parametrize(
    "component",
    ["observation_ledger", "memory_runtime", "metrics_projection"],
)
async def test_each_local_component_degradation_fails_cached_readiness(
    component: str,
) -> None:
    injected = runtime()
    if component == "observation_ledger":
        injected.observation_query.observation_health.return_value = ObservationHealth(
            True,
            False,
            True,
            queue_depth=7,
            last_error="C:/private/secret",
        )
    elif component == "memory_runtime":
        injected.memory_runtime.health.return_value = {
            "ready": True,
            "degraded": True,
            "index_backlog": 3,
            "ingestion_failed": 0,
            "last_error": "C:/private/secret",
        }
    else:
        injected = InspectionRuntime(
            observation_query=injected.observation_query,
            report_store=injected.report_store,
            memory_runtime=injected.memory_runtime,
            readiness_snapshot=injected.readiness_snapshot,
            metrics_snapshot=lambda: "missing required metrics",
            observation_write_probe=injected.observation_write_probe,
        )
    cache = ComponentReadinessCache(injected)

    await cache.refresh()
    snapshot = cache.snapshot()

    assert snapshot["ready"] is False
    assert snapshot["components"][component]["ready"] is False
    assert "private" not in str(snapshot)
    assert "secret" not in str(snapshot)


async def test_stale_cache_fails_closed_without_running_probes_in_snapshot() -> None:
    now = [100.0]
    cache = ComponentReadinessCache(runtime(), max_age_seconds=5.0, clock=lambda: now[0])
    await cache.refresh()
    now[0] = 106.0

    snapshot = cache.snapshot()

    assert snapshot["ready"] is False
    assert all(
        component["reason"] == "stale_status"
        for component in snapshot["components"].values()
    )


async def test_real_ledger_commit_and_prometheus_delta_feed_cached_readiness(
    tmp_path,
) -> None:
    registry = CollectorRegistry()
    mirror = PrometheusMirror(registry=registry)
    ledger = SQLiteObservationLedger(tmp_path / "observations.db", mirrors=[mirror])
    await ledger.start()
    memory = MagicMock()
    memory.health = AsyncMock(
        return_value={
            "ready": True,
            "degraded": False,
            "ingestion_queue_depth": 0,
            "index_backlog": 0,
            "ingestion_failed": 0,
            "last_error": None,
        }
    )

    async def probe() -> None:
        await ledger.probe_write()
        await mirror.probe()

    injected = InspectionRuntime(
        observation_query=ledger,
        report_store=ledger,
        memory_runtime=memory,
        readiness_snapshot=lambda: {"ready": True, "components": {}},
        metrics_snapshot=lambda: generate_latest(registry).decode(),
        observation_write_probe=probe,
    )
    cache = ComponentReadinessCache(injected)
    try:
        await cache.refresh()
        snapshot = cache.snapshot()
    finally:
        await ledger.close()

    assert snapshot["ready"] is True
    assert snapshot["components"]["observation_ledger"]["write_probe"] is True
    assert (
        snapshot["components"]["metrics_projection"]
        ["anima_readiness_probe_total_delta"]
        > 0
    )


async def test_required_remote_tts_outage_and_recovery_refresh_cached_readiness() -> None:
    injected = runtime()
    probe = AsyncMock(
        side_effect=[
            ConnectionError("C:/private/worker unavailable"),
            {
                "ready": True,
                "service": "qwen-tts",
                "api_version": "v1",
            },
        ]
    )
    cache = ComponentReadinessCache(replace(injected, remote_tts_probe=probe))

    await cache.refresh()
    outage = cache.snapshot()
    await cache.refresh()
    recovered = cache.snapshot()

    assert outage["ready"] is False
    assert outage["components"]["remote_tts"] == {
        "state": "failed",
        "ready": False,
        "reason": "component_degraded",
    }
    assert "private" not in str(outage)
    assert recovered["ready"] is True
    assert recovered["components"]["remote_tts"]["ready"] is True
