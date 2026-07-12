from __future__ import annotations

import asyncio

from animetta.inspection.checks.health import ComponentCheck, _run_single_probe


async def test_component_check_passes_and_records_duration() -> None:
    async def probe() -> bool:
        return True

    result = await _run_single_probe(ComponentCheck("ready", probe, 1.0))
    assert result.ok is True
    assert result.duration_ms >= 0


async def test_component_check_fails_closed_on_exception() -> None:
    async def probe() -> bool:
        raise RuntimeError("unavailable")

    result = await _run_single_probe(ComponentCheck("failed", probe, 1.0))
    assert result.ok is False
    assert "RuntimeError" in (result.error or "")


async def test_component_check_timeout_does_not_escape() -> None:
    async def probe() -> bool:
        await asyncio.sleep(1)
        return True

    result = await _run_single_probe(ComponentCheck("slow", probe, 0.001))
    assert result.ok is False
    assert "timeout" in (result.error or "")
