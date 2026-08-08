"""Typed missions for the lowest-layer real Minecraft acceptance scenes."""

from __future__ import annotations

from collections.abc import Mapping

from animetta.tools.minecraft.blueprint import (
    BlueprintBinding,
    BlueprintCompiler,
    starter_shelter_blueprint,
)
from animetta.tools.minecraft.mission.models import MissionSpec
from animetta.tools.minecraft.voyager.budget import BudgetUsage, ExecutionBudget


def stage_receipts_passed(stage: Mapping[str, object], capability: str) -> bool:
    if stage.get("passed") is not True:
        return False
    raw_receipts = stage.get("receipts")
    if not isinstance(raw_receipts, (list, tuple)):
        return False
    relevant = tuple(
        receipt
        for receipt in raw_receipts
        if isinstance(receipt, dict) and receipt.get("capability") == capability
    )
    return bool(relevant) and all(
        receipt.get("outcome") == "success"
        and receipt.get("post_observation") == "stable"
        and receipt.get("reconciliation") == "accepted"
        and bool(receipt.get("settlement_trace"))
        for receipt in relevant
    )


def _execution_budget(
    usage: BudgetUsage,
    *,
    queue_timeout_ms: int = 30_000,
    execution_timeout_ms: int = 600_000,
) -> ExecutionBudget:
    return ExecutionBudget(
        queue_timeout_ms=queue_timeout_ms,
        execution_timeout_ms=execution_timeout_ms,
        max_actions=usage.max_actions,
        max_strategy_attempts=usage.max_strategy_attempts,
        max_travel_distance=usage.max_travel_distance,
        max_blocks_changed=usage.max_blocks_changed,
        max_damage_taken=usage.max_damage_taken,
        resource_consumption=usage.resource_consumption,
    )


def _mission(
    *,
    mission_id: str,
    objective_id: str,
    goal: dict[str, object],
    usage: BudgetUsage,
    allow_skill_learning: bool = False,
    completion_predicates: tuple[dict[str, object], ...] = (),
) -> MissionSpec:
    return MissionSpec.model_validate(
        {
            "mission_id": mission_id,
            "objectives": (
                {
                    "objective_id": objective_id,
                    "goal": goal,
                    "budget": usage.model_dump(mode="python"),
                },
            ),
            "completion_predicates": completion_predicates,
            "budget": _execution_budget(usage).model_dump(mode="python"),
            "execution": {
                "reuse_trusted_skill": True,
                "allow_skill_learning": allow_skill_learning,
                "allow_deterministic_fallback": False,
            },
        }
    )


def build_combat_mission(*, mission_id: str, entity: str) -> MissionSpec:
    usage = BudgetUsage(
        max_actions=8,
        max_strategy_attempts=3,
        max_travel_distance=96,
        max_blocks_changed=0,
        max_damage_taken=6,
    )
    return _mission(
        mission_id=mission_id,
        objective_id="defeat-target",
        goal={
            "intent": "combat",
            "target": entity,
            "quantity": 1,
            "constraints": {},
            "success_predicates": ({"kind": "entity_defeated", "entity": entity, "quantity": 1},),
        },
        usage=usage,
    )


def build_construction_mission(*, mission_id: str) -> MissionSpec:
    blueprint = starter_shelter_blueprint()
    static_cost = (
        BlueprintCompiler()
        .compile(
            blueprint,
            BlueprintBinding(origin=(0, 0, 0), materials={}),
        )
        .static_cost
    )
    usage = static_cost.model_copy(update={"max_strategy_attempts": 2})
    return _mission(
        mission_id=mission_id,
        objective_id="build-starter-shelter",
        goal={
            "intent": "build",
            "target": blueprint.blueprint_id,
            "quantity": 1,
            "constraints": {},
            "success_predicates": (
                {
                    "kind": "structure_matches_blueprint",
                    "blueprint_id": blueprint.blueprint_id,
                    "blueprint_hash": blueprint.canonical_hash,
                },
            ),
        },
        usage=usage,
    )


def build_acquisition_mission(*, mission_prefix: str) -> tuple[MissionSpec, MissionSpec]:
    usage = BudgetUsage(
        max_actions=12,
        max_strategy_attempts=4,
        max_travel_distance=160,
        max_blocks_changed=4,
        max_damage_taken=2,
    )

    def acquire(*, suffix: str, phase: str, quantity: int, learning: bool) -> MissionSpec:
        return _mission(
            mission_id=f"{mission_prefix}-{suffix}",
            objective_id=f"acquire-{suffix}",
            goal={
                "intent": "acquire",
                "target": "minecraft:raw_copper",
                "quantity": quantity,
                "constraints": {
                    "adaptive_phase": phase,
                    "source_block": "minecraft:copper_ore",
                },
                "success_predicates": (
                    {
                        "kind": "inventory_at_least",
                        "item": "minecraft:raw_copper",
                        "quantity": quantity,
                    },
                ),
            },
            usage=usage,
            allow_skill_learning=learning,
            completion_predicates=(
                ({"kind": "trusted_skills_created_at_least", "count": 1},) if learning else ()
            ),
        )

    return (
        acquire(suffix="learn-validate", phase="learn_validate", quantity=1, learning=True),
        acquire(suffix="reuse", phase="reuse", quantity=5, learning=False),
    )
