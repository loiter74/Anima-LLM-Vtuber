"""Project committed GameBot v2 evidence into world-scoped discovery facts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from animetta.tools.gamebot.contracts.v2 import ActionReceipt, Observation, ReceiptOutcome
from animetta.tools.minecraft.skill.trust import stable_environment_fingerprint
from animetta.tools.minecraft.voyager.goal_models import GoalSpec

from .models import (
    AcquisitionEvidence,
    DiscoveryObservation,
    FactKind,
    ObservedFact,
    WorldFact,
    WorldFactIdentity,
)
from .projector import DiscoveryProjector
from .store import WorldFactStore


class RuntimeDiscoveryResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    observed: tuple[WorldFact, ...] = ()
    acquired: tuple[WorldFact, ...] = ()


def _resource_id(value: str) -> str:
    return value if ":" in value else f"minecraft:{value}"


def _coarse_location(observation: Observation) -> str | None:
    if observation.position is None:
        return None
    return (
        f"{observation.profile.dimension}:chunk:"
        f"{int(observation.position.x) // 16}:{int(observation.position.z) // 16}"
    )


def _observed_facts(observation: Observation) -> tuple[ObservedFact, ...]:
    coarse = _coarse_location(observation)
    by_identity: dict[tuple[str, str], ObservedFact] = {}

    def add(kind: FactKind, key: str, metadata: dict[str, object] | None = None) -> None:
        fact = ObservedFact(
            fact_kind=kind,
            fact_key=_resource_id(key),
            coarse_location=coarse,
            metadata=metadata or {},
        )
        by_identity[(fact.fact_kind, fact.fact_key)] = fact

    for item, count in observation.inventory.items():
        if count > 0:
            add("item", item, {"source": "inventory", "count": count})
    for block in observation.visible_blocks:
        add(
            "block",
            block.block_id,
            {
                "source": "visible_block",
                "position": block.position.model_dump(mode="json"),
            },
        )
    for entity in observation.visible_entities:
        add(
            "entity",
            entity.entity_type,
            {
                "source": "visible_entity",
                "entity_id": entity.entity_id,
                "position": entity.position.model_dump(mode="json"),
            },
        )
    if observation.biome:
        add("biome", observation.biome, {"source": "observation"})
    for advancement in observation.active_advancements:
        add("advancement", advancement, {"source": "version_adapter_projection"})
    return tuple(by_identity[key] for key in sorted(by_identity))


class RuntimeDiscoveryProjector:
    """Translate only committed observation/receipt evidence into discovery state."""

    def __init__(self, *, store: WorldFactStore) -> None:
        self._store = store
        self._projector = DiscoveryProjector(store=store)

    async def project_goal(
        self,
        *,
        goal: GoalSpec,
        command_id: str,
        initial: Observation,
        final: Observation,
        receipts: tuple[ActionReceipt, ...],
        fallback_only: bool,
    ) -> RuntimeDiscoveryResult:
        environment = stable_environment_fingerprint(final.profile)
        projected = await self._projector.project_observation(
            DiscoveryObservation(
                runtime_instance_id=final.runtime_instance_id,
                world_identity_hash=final.profile.world_identity_hash,
                environment_fingerprint=environment,
                observation_id=final.observation_id,
                observation_hash=final.content_hash,
                captured_at_ms=final.captured_at_ms,
                tick=final.tick,
                facts=_observed_facts(final),
            )
        )
        observed = tuple(
            sorted(
                (*projected.new_facts, *projected.updated_facts),
                key=lambda fact: fact.fact_id,
            )
        )
        acquired: list[WorldFact] = []
        if fallback_only or goal.intent not in {"acquire", "discover"}:
            return RuntimeDiscoveryResult(observed=observed)
        for receipt in receipts:
            if receipt.outcome is not ReceiptOutcome.SUCCESS:
                continue
            for mutation in receipt.explained_mutations:
                if mutation.kind != "inventory" or (mutation.delta or 0) <= 0:
                    continue
                identity = WorldFactIdentity(
                    world_identity_hash=final.profile.world_identity_hash,
                    environment_fingerprint=environment,
                    fact_kind="item",
                    fact_key=_resource_id(mutation.subject),
                )
                if await self._store.get(identity.fact_id) is None:
                    continue
                acquired.append(
                    await self._projector.project_acquisition(
                        AcquisitionEvidence(
                            fact_id=identity.fact_id,
                            runtime_instance_id=final.runtime_instance_id,
                            world_identity_hash=final.profile.world_identity_hash,
                            environment_fingerprint=environment,
                            command_id=command_id,
                            receipt_id=receipt.receipt_id,
                            correlation_id=receipt.correlation_id,
                            before_observation_id=initial.observation_id,
                            after_observation_id=final.observation_id,
                            inventory_delta=int(mutation.delta or 0),
                            committed=True,
                            fallback_only=fallback_only,
                            explained_inventory_delta=True,
                            observed_at_ms=max(final.captured_at_ms, receipt.finished_at_ms),
                        )
                    )
                )
        return RuntimeDiscoveryResult(
            observed=observed,
            acquired=tuple(sorted(acquired, key=lambda fact: fact.fact_id)),
        )
