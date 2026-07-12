"""Fail-closed health checks over injected, application-owned runtime ports."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ..models import CheckResult
from ..runtime import InspectionRuntime

_llm_connectivity_cache: dict[str, object] = {"ok": None, "status": "pending"}


@dataclass(frozen=True, slots=True)
class ComponentCheck:
    name: str
    probe: Callable[[], Awaitable[bool]]
    timeout: float
    description: str = ""


async def _run_single_probe(check: ComponentCheck) -> CheckResult:
    started = time.perf_counter()
    try:
        ok = await asyncio.wait_for(check.probe(), timeout=check.timeout)
    except TimeoutError:
        return CheckResult.failed(
            check.name,
            duration_ms=(time.perf_counter() - started) * 1000,
            error=f"timeout after {check.timeout}s",
        )
    except Exception as exc:
        return CheckResult.failed(
            check.name,
            duration_ms=(time.perf_counter() - started) * 1000,
            error=f"{type(exc).__name__}: {exc}",
        )
    duration_ms = (time.perf_counter() - started) * 1000
    if ok:
        return CheckResult.passed(check.name, duration_ms=duration_ms)
    return CheckResult.failed(check.name, duration_ms=duration_ms, error="probe returned False")


async def check_all_components(
    runtime: InspectionRuntime | None = None,
) -> dict[str, CheckResult]:
    """Inspect only canonical runtime owners; missing injection is a failure."""
    if runtime is None:
        return {
            "inspection_runtime": CheckResult.failed(
                "inspection_runtime", error="inspection runtime not configured"
            )
        }
    results = await asyncio.gather(
        _check_observation_ledger(runtime),
        _check_service_pool(runtime),
        _check_memory_runtime(runtime),
        _check_metrics_projection(runtime),
    )
    return {result.name: result for result in results}


async def _check_observation_ledger(runtime: InspectionRuntime) -> CheckResult:
    started = time.perf_counter()
    try:
        health, overview = await asyncio.gather(
            runtime.observation_query.observation_health(),
            runtime.observation_query.overview(),
        )
        detail = {
            "ready": health.ready,
            "degraded": health.degraded,
            "queue_depth": health.queue_depth,
            "dropped_records": health.dropped_records,
            "writer_errors": health.writer_errors,
            "schema_version": overview.get("schema_version"),
        }
        ok = bool(
            health.enabled
            and health.ready
            and not health.degraded
            and overview.get("schema_version") == 2
        )
        return _result("observation_ledger", ok, started, detail)
    except Exception as exc:
        return _exception_result("observation_ledger", started, exc)


async def _check_service_pool(runtime: InspectionRuntime) -> CheckResult:
    started = time.perf_counter()
    try:
        snapshot = runtime.readiness_snapshot()
        payload = snapshot.to_dict() if hasattr(snapshot, "to_dict") else dict(snapshot)
        components = payload.get("components", {})
        llm = components.get("llm", {})
        tts = components.get("tts", {})
        detail = {
            "profile": payload.get("profile"),
            "ready": payload.get("ready") is True,
            "llm_provider": llm.get("provider"),
            "llm_model": llm.get("model"),
            "llm_ready": llm.get("ready"),
            "tts_provider": tts.get("provider"),
            "tts_ready": tts.get("ready"),
        }
        return _result("service_pool", payload.get("ready") is True, started, detail)
    except Exception as exc:
        return _exception_result("service_pool", started, exc)


async def _check_memory_runtime(runtime: InspectionRuntime) -> CheckResult:
    started = time.perf_counter()
    try:
        health = dict(await runtime.memory_runtime.health())
        ok = bool(
            health.get("ready") is True
            and int(health.get("ingestion_failed", 0)) == 0
            and not health.get("last_error")
        )
        return _result("memory_runtime", ok, started, health)
    except Exception as exc:
        return _exception_result("memory_runtime", started, exc)


async def _check_metrics_projection(runtime: InspectionRuntime) -> CheckResult:
    started = time.perf_counter()
    try:
        snapshot = runtime.metrics_snapshot()
        expected = ("anima_active_sessions", "anima_trace_outcomes_total")
        detail = {f"has_{name}": name in snapshot for name in expected}
        detail["body_length"] = len(snapshot)
        return _result(
            "metrics_projection",
            all(detail[f"has_{name}"] for name in expected),
            started,
            detail,
        )
    except Exception as exc:
        return _exception_result("metrics_projection", started, exc)


def _result(name: str, ok: bool, started: float, detail: dict[str, Any]) -> CheckResult:
    duration_ms = (time.perf_counter() - started) * 1000
    if ok:
        return CheckResult.passed(name, duration_ms=duration_ms, **detail)
    return CheckResult.failed(
        name, duration_ms=duration_ms, error="runtime health degraded", **detail
    )


def _exception_result(name: str, started: float, exc: BaseException) -> CheckResult:
    return CheckResult.failed(
        name,
        duration_ms=(time.perf_counter() - started) * 1000,
        error=f"{type(exc).__name__}: {exc}",
    )


async def refresh_llm_connectivity_cache() -> None:
    """Compatibility hook; connectivity is already cached by ServicePool."""
    return None
