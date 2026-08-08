from __future__ import annotations

from copy import deepcopy

import pytest

from animetta.tools.minecraft.discovery.models import (
    AcquisitionEvidence,
    DiscoveryObservation,
    ObservedFact,
)
from animetta.tools.minecraft.discovery.projector import DiscoveryProjector
from animetta.tools.minecraft.discovery.store import InMemoryWorldFactStore


def _observation(*, tick: int = 10, captured_at_ms: int = 1_000) -> DiscoveryObservation:
    return DiscoveryObservation(
        runtime_instance_id="runtime-001",
        world_identity_hash="w" * 64,
        environment_fingerprint="e" * 64,
        observation_id=f"obs-{tick}",
        observation_hash="a" * 64,
        captured_at_ms=captured_at_ms,
        tick=tick,
        facts=(ObservedFact(fact_kind="item", fact_key="minecraft:copper_ingot"),),
    )


def _acquisition(fact_id: str) -> dict[str, object]:
    return {
        "fact_id": fact_id,
        "runtime_instance_id": "runtime-001",
        "world_identity_hash": "w" * 64,
        "environment_fingerprint": "e" * 64,
        "command_id": "command-001",
        "receipt_id": "receipt-001",
        "correlation_id": "correlation-001",
        "before_observation_id": "obs-10",
        "after_observation_id": "obs-20",
        "inventory_delta": 1,
        "committed": True,
        "fallback_only": False,
        "explained_inventory_delta": True,
        "observed_at_ms": 1_020,
    }


async def test_stale_observation_cannot_update_last_seen_or_novelty() -> None:
    store = InMemoryWorldFactStore()
    projector = DiscoveryProjector(store=store)
    created = await projector.project_observation(_observation())
    original = created.new_facts[0]

    with pytest.raises(ValueError, match="STALE_DISCOVERY_EVIDENCE"):
        await projector.project_observation(_observation(tick=5, captured_at_ms=900))

    unchanged = await store.get(original.fact_id)
    assert unchanged == original


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("committed", False, "ACQUISITION_EVIDENCE_INELIGIBLE"),
        ("fallback_only", True, "ACQUISITION_EVIDENCE_INELIGIBLE"),
        ("explained_inventory_delta", False, "ACQUISITION_EVIDENCE_INELIGIBLE"),
        ("world_identity_hash", "x" * 64, "ACQUISITION_WORLD_MISMATCH"),
        ("runtime_instance_id", "runtime-002", "ACQUISITION_RUNTIME_MISMATCH"),
        ("observed_at_ms", 900, "STALE_DISCOVERY_EVIDENCE"),
    ],
)
async def test_ineligible_acquisition_evidence_cannot_promote_world_fact(
    field: str, value: object, reason: str
) -> None:
    store = InMemoryWorldFactStore()
    projector = DiscoveryProjector(store=store)
    created = await projector.project_observation(_observation())
    original = created.new_facts[0]
    payload = deepcopy(_acquisition(original.fact_id))
    payload[field] = value

    with pytest.raises(ValueError, match=reason):
        await projector.project_acquisition(AcquisitionEvidence.model_validate(payload))

    unchanged = await store.get(original.fact_id)
    assert unchanged is not None
    assert unchanged.state == "observed"
    assert unchanged.acquisition_receipt_ref is None
