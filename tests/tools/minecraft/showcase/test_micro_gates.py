from __future__ import annotations

from animetta.tools.minecraft.blueprint import starter_shelter_blueprint
from animetta.tools.minecraft.showcase.micro_gates import (
    build_acquisition_mission,
    build_combat_mission,
    build_construction_mission,
    stage_receipts_passed,
)


def test_combat_micro_mission_has_one_typed_target_without_autonomy() -> None:
    mission = build_combat_mission(
        mission_id="r7-zombie-01",
        entity="minecraft:zombie",
    )

    assert len(mission.objectives) == 1
    assert mission.objectives[0].goal.intent == "combat"
    assert mission.objectives[0].goal.target == "minecraft:zombie"
    assert mission.autonomy.mode == "off"
    assert mission.execution.allow_skill_learning is False


def test_construction_micro_mission_uses_the_approved_exact_blueprint() -> None:
    mission = build_construction_mission(mission_id="r7-construction-01")
    predicate = mission.objectives[0].goal.success_predicates[0]

    assert predicate.kind == "structure_matches_blueprint"
    assert predicate.blueprint_id == "starter-shelter-v1"
    assert predicate.blueprint_hash == starter_shelter_blueprint().canonical_hash
    assert mission.objectives[0].budget.max_blocks_changed >= 85


def test_acquisition_micro_missions_select_policy_phase_not_runtime_strategy() -> None:
    learning, reuse = build_acquisition_mission(mission_prefix="r7-acquisition-01")

    assert learning.objectives[0].goal.constraints == {
        "adaptive_phase": "learn_validate",
        "source_block": "minecraft:copper_ore",
    }
    assert reuse.objectives[0].goal.constraints == {
        "adaptive_phase": "reuse",
        "source_block": "minecraft:copper_ore",
    }
    assert learning.execution.allow_skill_learning is True
    assert reuse.execution.reuse_trusted_skill is True
    serialized = learning.model_dump_json() + reuse.model_dump_json()
    assert '"strategy"' not in serialized
    assert '"mode":"learn"' not in serialized


def test_receipt_gate_requires_success_stable_observation_and_accepted_reconciliation() -> None:
    accepted = {
        "passed": True,
        "receipts": (
            {
                "capability": "attack",
                "outcome": "success",
                "post_observation": "stable",
                "reconciliation": "accepted",
                "settlement_trace": ({"sample_index": 0},),
            },
        ),
    }
    pending = {
        **accepted,
        "receipts": (
            {
                **accepted["receipts"][0],
                "post_observation": "unstable",
                "reconciliation": "pending",
            },
        ),
    }

    assert stage_receipts_passed(accepted, "attack") is True
    assert stage_receipts_passed(pending, "attack") is False
