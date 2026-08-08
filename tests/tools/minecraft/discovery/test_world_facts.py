from __future__ import annotations

from importlib import import_module
from pathlib import Path


def _modules():
    return (
        import_module("animetta.tools.minecraft.discovery.models"),
        import_module("animetta.tools.minecraft.discovery.projector"),
        import_module("animetta.tools.minecraft.discovery.store"),
    )


def _observation(models, *, world: str, observation_id: str, tick: int):
    return models.DiscoveryObservation(
        runtime_instance_id="runtime-001",
        world_identity_hash=world,
        environment_fingerprint="e" * 64,
        observation_id=observation_id,
        observation_hash=("a" if observation_id.endswith("1") else "b") * 64,
        captured_at_ms=1_000 + tick,
        tick=tick,
        facts=(
            models.ObservedFact(
                fact_kind="item",
                fact_key="minecraft:copper_ingot",
                coarse_location="overworld:chunk:0:0",
                metadata={"source": "inventory_or_nearby"},
            ),
        ),
    )


async def _exercise_store(store, models, projector_module) -> None:
    await store.connect()
    projector = projector_module.DiscoveryProjector(store=store)
    first = await projector.project_observation(
        _observation(models, world="w" * 64, observation_id="obs-001", tick=10)
    )
    repeated = await projector.project_observation(
        _observation(models, world="w" * 64, observation_id="obs-002", tick=20)
    )
    other_world = await projector.project_observation(
        _observation(models, world="x" * 64, observation_id="obs-001", tick=10)
    )

    assert len(first.new_facts) == 1
    original = first.new_facts[0]
    assert original.state == "observed"
    assert original.first_observation_ref == "observation:obs-001"
    assert original.last_observation_ref == "observation:obs-001"
    assert original.observation_count == 1
    assert repeated.new_facts == ()
    updated = repeated.updated_facts[0]
    assert updated.fact_id == original.fact_id
    assert updated.last_observation_ref == "observation:obs-002"
    assert updated.observation_count == 2
    assert other_world.new_facts[0].fact_id != original.fact_id

    acquired = await projector.project_acquisition(
        models.AcquisitionEvidence(
            fact_id=original.fact_id,
            runtime_instance_id="runtime-001",
            world_identity_hash="w" * 64,
            environment_fingerprint="e" * 64,
            command_id="command-001",
            receipt_id="receipt-001",
            correlation_id="correlation-001",
            before_observation_id="obs-001",
            after_observation_id="obs-003",
            inventory_delta=1,
            committed=True,
            fallback_only=False,
            explained_inventory_delta=True,
            observed_at_ms=1_030,
        )
    )

    assert acquired.state == "acquired"
    assert acquired.acquisition_receipt_ref == "receipt:receipt-001"
    scoped = await store.list_scope(
        world_identity_hash="w" * 64,
        environment_fingerprint="e" * 64,
    )
    acquired_only = await store.list_scope(
        world_identity_hash="w" * 64,
        environment_fingerprint="e" * 64,
        state=models.WorldFactState.ACQUIRED,
    )
    assert tuple(item.fact_id for item in scoped) == (original.fact_id,)
    assert tuple(item.fact_id for item in acquired_only) == (original.fact_id,)
    assert "mastered" not in type(acquired).model_fields
    assert {state.value for state in models.WorldFactState} == {"observed", "acquired"}
    await store.close()


async def test_world_facts_are_world_scoped_deduplicated_and_evidence_backed(
    tmp_path: Path,
) -> None:
    models, projector, store = _modules()

    await _exercise_store(store.InMemoryWorldFactStore(), models, projector)
    await _exercise_store(
        store.SQLiteWorldFactStore(tmp_path / "minecraft-journal.db"), models, projector
    )
