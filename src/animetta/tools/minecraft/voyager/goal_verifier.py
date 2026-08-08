"""Independent typed goal verification from authoritative evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from animetta.tools.gamebot.contracts.v2 import (
    ActionReceipt,
    AdvancementObservedEvent,
    Observation,
    ReceiptOutcome,
    RegionInspection,
    canonical_json_hash,
)
from animetta.tools.minecraft.blueprint.models import CompiledBlueprint
from animetta.tools.minecraft.blueprint.verifier import BlueprintVerifier
from animetta.tools.minecraft.discovery.models import WorldFact, WorldFactState

from .goal_models import (
    BlocksPlaced,
    EntityDefeated,
    GoalSpec,
    HealthAtLeast,
    InventoryAtLeast,
    LocationReached,
    StructureMatchesBlueprint,
    SurvivedDuration,
    VanillaAdvancementObserved,
    WorldFactAcquired,
    WorldFactObserved,
)


def _resource_id(value: str) -> str:
    return value if ":" in value else f"minecraft:{value}"


class GoalVerifier:
    def __init__(
        self,
        *,
        compiled_blueprints: Mapping[str, CompiledBlueprint] | None = None,
    ) -> None:
        self._compiled_blueprints = dict(compiled_blueprints or {})
        self._blueprint_verifier = BlueprintVerifier()

    def verify(
        self,
        *,
        goal: GoalSpec,
        initial: Observation | None = None,
        final: Observation | None = None,
        receipts: list[Any] | None = None,
        evidence: list[Any] | None = None,
        region_inspections: Sequence[RegionInspection] | None = None,
        world_facts: Sequence[WorldFact] | None = None,
        advancement_events: Sequence[AdvancementObservedEvent] | None = None,
        technology_evidence: Sequence[Any] | None = None,
        compiled_blueprints: Sequence[CompiledBlueprint] | None = None,
    ) -> dict[str, Any]:
        del technology_evidence  # Internal technology evidence is never vanilla evidence.
        receipt_list = receipts if receipts is not None else (evidence or [])
        inspections = tuple(region_inspections or ())
        facts = tuple(world_facts or ())
        advancement_state = self._advancement_state(advancement_events or ())
        blueprint_catalog = dict(self._compiled_blueprints)
        blueprint_catalog.update(
            {blueprint.blueprint_hash: blueprint for blueprint in compiled_blueprints or ()}
        )
        results: list[dict[str, Any]] = []
        for predicate in goal.success_predicates:
            satisfied = False
            details: dict[str, Any] = {}
            evidence_refs: list[str] = []
            if isinstance(predicate, InventoryAtLeast) and final is not None:
                inventory_count = max(
                    (
                        count
                        for item, count in final.inventory.items()
                        if _resource_id(item) == _resource_id(predicate.item)
                    ),
                    default=0,
                )
                satisfied = inventory_count >= predicate.quantity
                details["inventory_count"] = inventory_count
            elif isinstance(predicate, HealthAtLeast) and final is not None:
                satisfied = (final.health or 0) >= predicate.health
            elif isinstance(predicate, LocationReached) and final is not None and final.position:
                distance = (
                    (final.position.x - predicate.x) ** 2
                    + (final.position.y - predicate.y) ** 2
                    + (final.position.z - predicate.z) ** 2
                ) ** 0.5
                satisfied = distance <= predicate.tolerance
            elif isinstance(predicate, EntityDefeated):
                defeated = {
                    receipt.combat.target_entity_id
                    for receipt in receipt_list
                    if isinstance(receipt, ActionReceipt)
                    and receipt.outcome is ReceiptOutcome.SUCCESS
                    and receipt.combat is not None
                    and receipt.combat.outcome == "defeated"
                    and receipt.combat.target_entity_type == predicate.entity
                }
                satisfied = len(defeated) >= predicate.quantity
                details["distinct_defeated_targets"] = sorted(defeated)
            elif isinstance(predicate, BlocksPlaced):
                satisfied = (
                    sum(
                        mutation.delta or 0
                        for receipt in receipt_list
                        for mutation in getattr(receipt, "explained_mutations", ())
                        if mutation.kind == "block" and mutation.subject == predicate.block
                    )
                    >= predicate.quantity
                )
            elif isinstance(predicate, SurvivedDuration) and initial and final:
                satisfied = final.captured_at_ms - initial.captured_at_ms >= predicate.duration_ms
            elif isinstance(predicate, StructureMatchesBlueprint):
                compiled = blueprint_catalog.get(predicate.blueprint_hash)
                if compiled is not None and compiled.blueprint_id == predicate.blueprint_id:
                    candidates = [
                        inspection
                        for inspection in inspections
                        if inspection.bounds == compiled.bounds
                    ]
                    if candidates:
                        inspection = max(
                            candidates,
                            key=lambda item: (item.captured_at_ms, item.tick, item.inspection_id),
                        )
                        verification = self._blueprint_verifier.verify(compiled, inspection)
                        satisfied = verification.satisfied
                        details.update(
                            missing_positions=list(verification.missing_positions),
                            conflicting_positions=list(verification.conflicting_positions),
                            unknown_positions=list(verification.unknown_positions),
                            feature_results=verification.feature_results,
                        )
                        evidence_refs.extend(
                            (verification.inspection_hash, verification.evidence_hash)
                        )
            elif isinstance(predicate, (WorldFactObserved, WorldFactAcquired)):
                matching = [
                    fact
                    for fact in facts
                    if fact.identity.fact_kind == predicate.fact_kind
                    and fact.identity.fact_key == predicate.fact_key
                ]
                if isinstance(predicate, WorldFactAcquired):
                    satisfied = any(fact.state is WorldFactState.ACQUIRED for fact in matching)
                else:
                    satisfied = bool(matching)
                evidence_refs.extend(fact.fact_id for fact in matching)
            elif isinstance(predicate, VanillaAdvancementObserved):
                satisfied = advancement_state.get(predicate.advancement_id) == predicate.action
                evidence_refs.extend(
                    event.content_hash
                    for event in advancement_events or ()
                    if event.advancement_id == predicate.advancement_id
                )
            results.append(
                {
                    "kind": predicate.kind,
                    "satisfied": satisfied,
                    "evidence_hash": canonical_json_hash(
                        {
                            "predicate": predicate.model_dump(mode="json"),
                            "final": final.content_hash if final else None,
                            "receipts": [
                                getattr(receipt, "content_hash", "") for receipt in receipt_list
                            ],
                            "evidence_refs": sorted(set(evidence_refs)),
                            "details": details,
                        }
                    ),
                    **details,
                }
            )
        return {
            "satisfied": bool(results) and all(item["satisfied"] for item in results),
            "predicate_results": results,
            "evidence_hashes": [item["evidence_hash"] for item in results],
        }

    @staticmethod
    def _advancement_state(
        events: Sequence[AdvancementObservedEvent],
    ) -> dict[str, str]:
        state: dict[str, str] = {}
        seen: set[str] = set()
        for event in sorted(
            events,
            key=lambda item: (item.observed_at_ms, item.tick, item.event_id),
        ):
            if event.content_hash in seen:
                continue
            seen.add(event.content_hash)
            state[event.advancement_id] = event.action
        return state
