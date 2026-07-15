"""Background-owned, content-free readiness cache for local runtime components."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from animetta.inspection.checks.health import check_all_components
from animetta.inspection.models import CheckResult
from animetta.inspection.runtime import InspectionRuntime

_COMPONENT_NAMES = (
    "observation_ledger",
    "memory_runtime",
    "metrics_projection",
)
_SAFE_DETAIL_FIELDS = {
    "observation_ledger": (
        "queue_depth",
        "dropped_records",
        "writer_errors",
        "schema_version",
        "write_probe",
    ),
    "memory_runtime": (
        "ingestion_queue_depth",
        "ingestion_queue",
        "index_backlog",
        "ingestion_failed",
    ),
    "metrics_projection": (
        "has_anima_readiness_probe_total",
        "anima_readiness_probe_total_delta",
    ),
    "remote_tts": ("contract_valid",),
}


class ComponentReadinessCache:
    """Refresh component probes in the background; snapshots never perform I/O."""

    def __init__(
        self,
        runtime: InspectionRuntime,
        *,
        refresh_interval_seconds: float = 30.0,
        max_age_seconds: float = 90.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.runtime = runtime
        self.refresh_interval_seconds = max(1.0, float(refresh_interval_seconds))
        self.max_age_seconds = max(1.0, float(max_age_seconds))
        self._clock = clock
        self._component_names = _COMPONENT_NAMES + (
            ("remote_tts",) if runtime.remote_tts_probe is not None else ()
        )
        self._refreshed_at: float | None = None
        self._components = self._unavailable_components("cache_unavailable")
        self._refresh_lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None

    async def refresh(self) -> None:
        """Run all probes once and atomically publish their sanitized results."""
        async with self._refresh_lock:
            results = await check_all_components(self.runtime)
            self._components = {
                name: self._sanitize_result(name, results.get(name))
                for name in self._component_names
            }
            self._refreshed_at = self._clock()

    def snapshot(self) -> dict[str, Any]:
        """Return cached JSON-safe state without awaiting or touching dependencies."""
        refreshed_at = self._refreshed_at
        if refreshed_at is None:
            components = self._unavailable_components("cache_unavailable")
            return {"ready": False, "age_seconds": None, "components": components}

        age = max(0.0, self._clock() - refreshed_at)
        if age > self.max_age_seconds:
            components = self._unavailable_components("stale_status")
            return {
                "ready": False,
                "age_seconds": round(age, 3),
                "components": components,
            }

        components = {name: dict(value) for name, value in self._components.items()}
        return {
            "ready": all(component["ready"] for component in components.values()),
            "age_seconds": round(age, 3),
            "components": components,
        }

    async def start(self) -> None:
        """Start periodic refresh without blocking application startup."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(
                self._refresh_loop(),
                name="animetta-component-readiness",
            )

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _refresh_loop(self) -> None:
        while True:
            try:
                await self.refresh()
            except asyncio.CancelledError:
                raise
            except Exception:
                self._components = self._unavailable_components("probe_failed")
                self._refreshed_at = self._clock()
            await asyncio.sleep(self.refresh_interval_seconds)

    def _unavailable_components(self, reason: str) -> dict[str, dict[str, Any]]:
        return {
            name: {"state": "failed", "ready": False, "reason": reason}
            for name in self._component_names
        }

    @staticmethod
    def _sanitize_result(
        name: str,
        result: CheckResult | None,
    ) -> dict[str, Any]:
        ready = bool(result is not None and result.ok)
        component: dict[str, Any] = {
            "state": "ready" if ready else "failed",
            "ready": ready,
            "reason": None if ready else "component_degraded",
        }
        if result is None:
            return component
        for field in _SAFE_DETAIL_FIELDS[name]:
            value = result.detail.get(field)
            if isinstance(value, (bool, int, float)):
                component[field] = value
        return component
