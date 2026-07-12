"""Consistency checks over the canonical ledger and memory runtime."""

from __future__ import annotations

import time

from ..models import CheckResult
from ..runtime import InspectionRuntime


async def observation_ledger_responds(runtime: InspectionRuntime | None = None) -> bool:
    if runtime is None:
        return False
    try:
        health = await runtime.observation_query.observation_health()
        overview = await runtime.observation_query.overview()
        return bool(health.ready and overview.get("schema_version") == 2)
    except Exception:
        return False


async def has_trace_in_last(
    minutes: int, runtime: InspectionRuntime | None = None
) -> bool:
    del minutes
    if runtime is None:
        return False
    try:
        return bool(await runtime.observation_query.recent_traces(1, 0))
    except Exception:
        return False


async def chroma_responds(runtime: InspectionRuntime | None = None) -> bool:
    if runtime is None:
        return False
    try:
        health = await runtime.memory_runtime.health()
        return bool(health.get("ready") and not health.get("last_error"))
    except Exception:
        return False


def log_file_stale(minutes: int) -> bool:
    """Obsolete compatibility probe; logs are not a canonical health source."""
    del minutes
    return False


async def check_data_consistency(
    runtime: InspectionRuntime | None = None,
) -> CheckResult:
    started = time.perf_counter()
    if runtime is None:
        return CheckResult.failed(
            "data_consistency", error="inspection runtime not configured"
        )
    ledger_ok, recent_trace, memory_ok = (
        await observation_ledger_responds(runtime),
        await has_trace_in_last(60, runtime),
        await chroma_responds(runtime),
    )
    detail = {
        "canonical_ledger_ok": ledger_ok,
        "has_recent_trace": recent_trace,
        "memory_runtime_ok": memory_ok,
    }
    duration_ms = (time.perf_counter() - started) * 1000
    if ledger_ok and memory_ok:
        return CheckResult.passed(
            "data_consistency", duration_ms=duration_ms, **detail
        )
    return CheckResult.failed(
        "data_consistency",
        duration_ms=duration_ms,
        error="canonical runtime consistency failed",
        **detail,
    )
