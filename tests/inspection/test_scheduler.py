"""Regression tests for the background inspection schedule."""

from unittest.mock import AsyncMock, patch

import pytest

from animetta.inspection.scheduler import InspectionScheduler


@pytest.mark.asyncio
async def test_full_inspection_waits_for_daily_interval_after_startup() -> None:
    """A fresh process must not contend with acceptance traffic after warmup."""
    runtime = AsyncMock()
    scheduler = InspectionScheduler(runtime=runtime, interval_hours=24)
    sleep_durations: list[float] = []

    async def controlled_sleep(duration: float) -> None:
        sleep_durations.append(duration)
        if len(sleep_durations) == 2:
            scheduler._stop_event.set()

    with (
        patch(
            "animetta.inspection.scheduler.asyncio.sleep",
            side_effect=controlled_sleep,
        ),
        patch(
            "animetta.inspection.scheduler.refresh_llm_connectivity_cache",
            new_callable=AsyncMock,
        ),
        patch(
            "animetta.inspection.scheduler.run_full_inspection",
            new_callable=AsyncMock,
        ) as run_full_inspection,
    ):
        await scheduler._loop()

    assert sleep_durations == [120, 5.0]
    run_full_inspection.assert_not_awaited()
