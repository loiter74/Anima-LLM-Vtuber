"""Pure-evidence projection into the world discovery catalog."""

from __future__ import annotations

from .models import (
    AcquisitionEvidence,
    DiscoveryObservation,
    DiscoveryProjectionResult,
    WorldFact,
    WorldFactIdentity,
)
from .store import WorldFactStore


class DiscoveryProjector:
    def __init__(self, *, store: WorldFactStore) -> None:
        self._store = store

    async def project_observation(
        self, observation: DiscoveryObservation
    ) -> DiscoveryProjectionResult:
        new_facts: list[WorldFact] = []
        updated_facts: list[WorldFact] = []
        for observed in observation.facts:
            identity = WorldFactIdentity(
                world_identity_hash=observation.world_identity_hash,
                environment_fingerprint=observation.environment_fingerprint,
                fact_kind=observed.fact_kind,
                fact_key=observed.fact_key,
            )
            existing = await self._store.get(identity.fact_id)
            if existing is not None and (
                observation.tick < existing.last_seen_tick
                or observation.captured_at_ms < existing.last_seen_at_ms
            ):
                raise ValueError("STALE_DISCOVERY_EVIDENCE")
            fact, created = await self._store.upsert_observed(identity, observed, observation)
            (new_facts if created else updated_facts).append(fact)
        return DiscoveryProjectionResult(
            new_facts=tuple(new_facts),
            updated_facts=tuple(updated_facts),
        )

    async def project_acquisition(self, evidence: AcquisitionEvidence) -> WorldFact:
        return await self._store.mark_acquired(evidence)
