from __future__ import annotations

from animetta.tools.gamebot.contracts.v2 import (
    ActionReceipt,
    AdvancementObservedEvent,
    BudgetVector,
    CombatTerminalEvidence,
    EnvironmentProfile,
    Observation,
    RegionInspection,
    WorldIdentitySnapshot,
)
from animetta.tools.minecraft.blueprint import (
    BlueprintBinding,
    BlueprintCompiler,
    BlueprintDimensions,
    PaletteEntry,
    RelativePlacement,
    StructureBlueprint,
)
from animetta.tools.minecraft.discovery import (
    WorldFact,
    WorldFactIdentity,
    WorldFactState,
)
from animetta.tools.minecraft.voyager.goal_models import (
    AcquireGoal,
    BuildGoal,
    CombatGoal,
    DiscoverGoal,
    EntityDefeated,
    InventoryAtLeast,
    StructureMatchesBlueprint,
    VanillaAdvancementObserved,
    WorldFactAcquired,
)
from animetta.tools.minecraft.voyager.goal_verifier import GoalVerifier


def _world() -> WorldIdentitySnapshot:
    return WorldIdentitySnapshot(
        runtime_instance_id="runtime-instance-1",
        server_identity_hash="b" * 64,
        world_identity_hash="c" * 64,
        dimension="minecraft:overworld",
    )


def _observation(*, inventory: dict[str, int]) -> Observation:
    profile = EnvironmentProfile(
        runtime_protocol="2.0",
        minecraft_version="1.21",
        capability_schema_digest="a" * 64,
        skill_api_version="1",
        policy_version="1",
        server_identity_hash="b" * 64,
        world_identity_hash="c" * 64,
        dimension="minecraft:overworld",
        modset_digest="d" * 64,
    )
    return Observation(
        observation_id="observation-inventory-1",
        correlation_id="correlation-inventory-1",
        runtime_instance_id="runtime-instance-1",
        captured_at_ms=1_799_999_999_000,
        tick=42,
        action_sequence=7,
        content_hash="e" * 64,
        profile=profile,
        world_identity=_world(),
        position={"x": 0.0, "y": 64.0, "z": 0.0},
        health=20.0,
        food=20,
        inventory=inventory,
        equipment={},
        environment={"weather": "clear"},
    )


def test_inventory_verifier_matches_vanilla_namespaced_goal_to_runtime_item_key() -> None:
    goal = AcquireGoal(
        intent="acquire",
        target="minecraft:raw_copper",
        quantity=1,
        success_predicates=(
            InventoryAtLeast(
                kind="inventory_at_least",
                item="minecraft:raw_copper",
                quantity=1,
            ),
        ),
    )

    result = GoalVerifier().verify(
        goal=goal,
        final=_observation(inventory={"raw_copper": 4}),
    )

    assert result["satisfied"] is True
    assert result["predicate_results"][0]["inventory_count"] == 4


def _combat_receipt(
    *,
    receipt_id: str,
    entity_id: str,
    entity_type: str,
    combat_outcome: str,
) -> ActionReceipt:
    combat = CombatTerminalEvidence(
        target_entity_id=entity_id,
        target_entity_type=entity_type,
        outcome=combat_outcome,
        bot_health_before=20,
        bot_health_after=18,
        target_health_before=20,
        target_health_after=0 if combat_outcome == "defeated" else 7,
        started_tick=100,
        finished_tick=120,
    )
    return ActionReceipt(
        receipt_id=receipt_id,
        command_id="command-combat-1",
        step_id=f"step-{receipt_id}",
        correlation_id=f"correlation-{receipt_id}",
        runtime_instance_id="runtime-instance-1",
        capability="attack",
        parameter_hash="a" * 64,
        action_sequence=int(receipt_id.rsplit("-", maxsplit=1)[-1]),
        started_at_ms=1_799_999_999_100,
        finished_at_ms=1_799_999_999_900,
        started_tick=100,
        finished_tick=120,
        outcome="success",
        post_observation="stable",
        reconciliation="accepted",
        goal_verification="unknown",
        reconciliation_error=None,
        settlement_trace=(),
        before_observation_hash="f" * 64,
        after_observation_hash="e" * 64,
        explained_mutations=(
            {
                "kind": "combat",
                "subject": entity_id,
                "details": {"outcome": combat_outcome},
            },
        ),
        combat=combat,
        budget_usage=BudgetVector(
            max_actions=1,
            max_strategy_attempts=0,
            max_travel_distance=0,
            max_blocks_changed=0,
            max_damage_taken=2,
        ),
        content_hash=(receipt_id[-1] * 64),
    )


def test_combat_verifier_counts_only_distinct_defeated_target_evidence() -> None:
    goal = CombatGoal(
        intent="combat",
        target="minecraft:zombie",
        quantity=2,
        success_predicates=(
            EntityDefeated(kind="entity_defeated", entity="minecraft:zombie", quantity=2),
        ),
    )
    defeated = _combat_receipt(
        receipt_id="receipt-1",
        entity_id="zombie-1",
        entity_type="minecraft:zombie",
        combat_outcome="defeated",
    )
    escaped = _combat_receipt(
        receipt_id="receipt-2",
        entity_id="zombie-2",
        entity_type="minecraft:zombie",
        combat_outcome="escaped",
    )
    interrupted = _combat_receipt(
        receipt_id="receipt-3",
        entity_id="skeleton-1",
        entity_type="minecraft:skeleton",
        combat_outcome="interrupted",
    )

    result = GoalVerifier().verify(
        goal=goal,
        receipts=[defeated, defeated, escaped, interrupted],
    )

    assert result["satisfied"] is False
    assert result["predicate_results"][0]["distinct_defeated_targets"] == ["zombie-1"]


def test_structure_verifier_requires_exact_region_not_placement_count() -> None:
    blueprint = StructureBlueprint(
        blueprint_id="tiny-shelter-v1",
        dimensions=BlueprintDimensions(width=2, height=1, depth=1),
        palette={
            "shell": PaletteEntry(
                default_block="minecraft:oak_planks",
                allowed_blocks=("minecraft:oak_planks",),
            )
        },
        placements=(
            RelativePlacement(x=0, y=0, z=0, material="shell"),
            RelativePlacement(x=1, y=0, z=0, material="shell"),
        ),
    )
    compiled = BlueprintCompiler().compile(
        blueprint,
        BlueprintBinding(origin=(10, 64, 20)),
    )
    goal = BuildGoal(
        intent="build",
        target=blueprint.blueprint_id,
        success_predicates=(
            StructureMatchesBlueprint(
                kind="structure_matches_blueprint",
                blueprint_id=blueprint.blueprint_id,
                blueprint_hash=blueprint.canonical_hash,
            ),
        ),
    )
    inspection = RegionInspection(
        inspection_id="inspection-1",
        correlation_id="correlation-region-1",
        runtime_instance_id="runtime-instance-1",
        world_identity=_world(),
        captured_at_ms=1_799_999_999_900,
        tick=200,
        observation_id="observation-region-1",
        observation_hash="e" * 64,
        bounds=compiled.bounds,
        blocks={
            "10,64,20": "minecraft:oak_planks",
            "11,64,20": "minecraft:air",
        },
        content_hash="4" * 64,
    )

    result = GoalVerifier(compiled_blueprints={compiled.blueprint_hash: compiled}).verify(
        goal=goal,
        receipts=[object(), object()],
        region_inspections=[inspection],
    )

    assert result["satisfied"] is False
    assert result["predicate_results"][0]["missing_positions"] == [(11, 64, 20)]

    completed_inspection = inspection.model_copy(
        update={
            "inspection_id": "inspection-2",
            "captured_at_ms": inspection.captured_at_ms + 1,
            "blocks": {
                "10,64,20": "minecraft:oak_planks",
                "11,64,20": "minecraft:oak_planks",
            },
            "content_hash": "6" * 64,
        }
    )
    completed = GoalVerifier(compiled_blueprints={compiled.blueprint_hash: compiled}).verify(
        goal=goal, region_inspections=[inspection, completed_inspection]
    )

    assert completed["satisfied"] is True
    assert completed["predicate_results"][0]["missing_positions"] == []


def _world_fact(state: WorldFactState) -> WorldFact:
    identity = WorldFactIdentity(
        world_identity_hash="c" * 64,
        environment_fingerprint="d" * 64,
        fact_kind="item",
        fact_key="minecraft:copper_ingot",
    )
    return WorldFact(
        fact_id=identity.fact_id,
        runtime_instance_id="runtime-instance-1",
        identity=identity,
        state=state,
        first_observation_ref="observation-1",
        first_observation_hash="e" * 64,
        last_observation_ref="observation-2",
        last_observation_hash="f" * 64,
        first_seen_at_ms=100,
        last_seen_at_ms=200,
        first_seen_tick=10,
        last_seen_tick=20,
        observation_count=2,
        acquisition_command_ref="command-1" if state is WorldFactState.ACQUIRED else None,
        acquisition_receipt_ref="receipt-1" if state is WorldFactState.ACQUIRED else None,
        acquisition_observation_ref="observation-2" if state is WorldFactState.ACQUIRED else None,
    )


def test_discovery_acquisition_requires_acquired_world_fact() -> None:
    goal = DiscoverGoal(
        intent="discover",
        target="minecraft:copper_ingot",
        discovery_kind="item",
        success_predicates=(
            WorldFactAcquired(
                kind="world_fact_acquired",
                fact_kind="item",
                fact_key="minecraft:copper_ingot",
            ),
        ),
    )

    observed = GoalVerifier().verify(goal=goal, world_facts=[_world_fact(WorldFactState.OBSERVED)])
    acquired = GoalVerifier().verify(goal=goal, world_facts=[_world_fact(WorldFactState.ACQUIRED)])

    assert observed["satisfied"] is False
    assert acquired["satisfied"] is True


def test_vanilla_advancement_uses_packet_event_and_ignores_internal_technology() -> None:
    goal = DiscoverGoal(
        intent="discover",
        target="minecraft:story/mine_stone",
        discovery_kind="advancement",
        success_predicates=(
            VanillaAdvancementObserved(
                kind="vanilla_advancement_observed",
                advancement_id="minecraft:story/mine_stone",
            ),
        ),
    )
    event = AdvancementObservedEvent(
        event_id="advancement-event-001",
        runtime_instance_id="runtime-instance-1",
        world_identity=_world(),
        advancement_id="minecraft:story/mine_stone",
        action="add",
        observation_id="observation-advancement-001",
        observation_hash="e" * 64,
        observed_at_ms=1_799_999_999_950,
        tick=220,
        source="version_adapter",
        content_hash="5" * 64,
    )

    internal_only = GoalVerifier().verify(
        goal=goal,
        technology_evidence=[{"id": "minecraft:story/mine_stone"}],
    )
    vanilla = GoalVerifier().verify(goal=goal, advancement_events=[event])

    assert internal_only["satisfied"] is False
    assert vanilla["satisfied"] is True
