from __future__ import annotations

"""Tests for MetabolismScheduler integration with LivingMemorySystem."""

from datetime import UTC, datetime

import pytest

from animetta.memory.v2.atom import Layer, MemoryAtom
from animetta.memory.v2.metabolism import MetabolismScheduler
from animetta.memory.v2.system import LivingMemorySystem


@pytest.mark.asyncio
class TestMetabolismIntegration:
    async def test_metabolism_tick_decays_salience(self):
        """Running a tick should recalculate salience for all atoms."""
        system = LivingMemorySystem(db_path=":memory:")
        await system.initialize()

        # Create atoms with varying confidence
        await system.store.create(
            MemoryAtom(
                id="high",
                layer=Layer.RAW,
                content="important",
                occurred_at=datetime.now(UTC),
                confidence=0.9,
                salience=0.9,
            )
        )
        await system.store.create(
            MemoryAtom(
                id="low",
                layer=Layer.RAW,
                content="trivial",
                occurred_at=datetime.now(UTC),
                confidence=0.1,
                salience=0.1,
            )
        )

        # Run tick
        await system.run_metabolism_tick()

        high = await system.store.get("high")
        low = await system.store.get("low")
        assert high.salience > low.salience  # High confidence → higher salience

        await system.shutdown()

    async def test_public_metabolism_tick_api_decays_salience(self):
        """Callers outside memory should use the public metabolism tick API."""
        system = LivingMemorySystem(db_path=":memory:")
        await system.initialize()

        await system.store.create(
            MemoryAtom(
                id="public-high",
                layer=Layer.RAW,
                content="important",
                occurred_at=datetime.now(UTC),
                confidence=0.9,
                salience=0.9,
            )
        )
        await system.store.create(
            MemoryAtom(
                id="public-low",
                layer=Layer.RAW,
                content="trivial",
                occurred_at=datetime.now(UTC),
                confidence=0.1,
                salience=0.1,
            )
        )

        await system.run_metabolism_tick()

        high = await system.store.get("public-high")
        low = await system.store.get("public-low")
        assert high.salience > low.salience

        await system.shutdown()

    async def test_metabolism_archives_low_salience(self):
        """Very low salience atoms should be archived."""
        system = LivingMemorySystem(db_path=":memory:")
        await system.initialize()

        # Create a very low salience atom
        await system.store.create(
            MemoryAtom(
                id="doomed",
                layer=Layer.RAW,
                content="very old and trivial",
                occurred_at=datetime.now(UTC),
                confidence=0.01,
                salience=0.01,
            )
        )

        # Run tick with forced low threshold
        count = await system.store.count_active()
        threshold = MetabolismScheduler.adaptive_threshold(count)
        await system.store.archive_below_threshold(threshold)

        doomed = await system.store.get("doomed")
        assert doomed.is_archived

        await system.shutdown()

    async def test_start_stop_metabolism(self):
        system = LivingMemorySystem(db_path=":memory:")
        await system.initialize()

        await system.start_metabolism()
        assert system._metabolism_task is not None
        assert not system._metabolism_task.done()

        await system.stop_metabolism()
        # Task should be cancelled/done
        assert system._metabolism_task.done()

        await system.shutdown()
