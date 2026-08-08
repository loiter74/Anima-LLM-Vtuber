from __future__ import annotations

from copy import deepcopy
from importlib import import_module

import pytest
from pydantic import ValidationError


def _models():
    return import_module("animetta.tools.minecraft.mission.models")


def _budget(**overrides: object) -> dict[str, object]:
    budget: dict[str, object] = {
        "queue_timeout_ms": 5_000,
        "execution_timeout_ms": 300_000,
        "max_actions": 20,
        "max_strategy_attempts": 12,
        "max_travel_distance": 256.0,
        "max_blocks_changed": 128,
        "max_damage_taken": 10.0,
        "protected_items": ["minecraft:diamond_pickaxe"],
        "resource_consumption": {"minecraft:oak_planks": 64},
    }
    budget.update(overrides)
    return budget


def _cost(**overrides: object) -> dict[str, object]:
    cost: dict[str, object] = {
        "max_actions": 4,
        "max_strategy_attempts": 2,
        "max_travel_distance": 32.0,
        "max_blocks_changed": 0,
        "max_damage_taken": 2.0,
        "resource_consumption": {},
    }
    cost.update(overrides)
    return cost


def _combat_goal(entity: str = "minecraft:zombie") -> dict[str, object]:
    return {
        "intent": "combat",
        "target": entity,
        "quantity": 1,
        "constraints": {},
        "success_predicates": [{"kind": "entity_defeated", "entity": entity, "quantity": 1}],
    }


def _discover_goal() -> dict[str, object]:
    return {
        "intent": "discover",
        "discovery_kind": "item",
        "target": "minecraft:copper_ingot",
        "quantity": 1,
        "constraints": {},
        "success_predicates": [
            {
                "kind": "world_fact_observed",
                "fact_kind": "item",
                "fact_key": "minecraft:copper_ingot",
            }
        ],
    }


def _objective(
    objective_id: str,
    *,
    goal: dict[str, object] | None = None,
    dependencies: list[str] | None = None,
    budget: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "objective_id": objective_id,
        "goal": goal or _combat_goal(),
        "dependencies": dependencies or [],
        "required": True,
        "priority": 50,
        "budget": budget or _cost(),
    }


def _mission_payload() -> dict[str, object]:
    return {
        "schema_version": "1",
        "mission_id": "showcase-001",
        "objectives": [
            _objective("fight-zombie"),
            _objective(
                "discover-copper",
                goal=_discover_goal(),
                dependencies=["fight-zombie"],
            ),
        ],
        "completion_rule": "all_required",
        "completion_predicates": [
            {"kind": "novel_facts_acquired_at_least", "count": 1},
            {"kind": "trusted_skills_created_at_least", "count": 1},
            {"kind": "vanilla_advancements_added_at_least", "count": 2},
        ],
        "budget": _budget(),
        "autonomy": {
            "mode": "bounded",
            "allowed_domains": ["discovery", "skill"],
            "max_child_goals": 4,
            "max_new_skills": 1,
            "max_duration_ms": 240_000,
            "max_travel_distance": 128.0,
            "max_damage_taken": 6.0,
            "max_blocks_changed": 32,
            "max_risk": "survival_safe",
            "stop_conditions": [
                "mission_complete",
                "novelty_exhausted",
                "budget_exhausted",
                "user_stop",
                "unknown_world_state",
            ],
        },
        "execution": {
            "reuse_trusted_skill": True,
            "allow_skill_learning": True,
            "allow_deterministic_fallback": False,
        },
    }


def test_mission_models_module_exists() -> None:
    module = _models()

    assert module.__name__ == "animetta.tools.minecraft.mission.models"


def test_mission_spec_accepts_typed_leaf_goals_and_open_ended_predicates() -> None:
    models = _models()

    mission = models.MissionSpec.model_validate(_mission_payload())

    assert mission.objectives[0].goal.intent == "combat"
    assert mission.objectives[1].goal.intent == "discover"
    assert mission.objectives[1].goal.discovery_kind == "item"
    assert [predicate.kind for predicate in mission.completion_predicates] == [
        "novel_facts_acquired_at_least",
        "trusted_skills_created_at_least",
        "vanilla_advancements_added_at_least",
    ]


def test_mission_spec_is_immutable_and_has_a_stable_canonical_hash() -> None:
    models = _models()
    first = models.MissionSpec.model_validate(_mission_payload())
    reordered = deepcopy(_mission_payload())
    reordered["budget"] = dict(reversed(list(reordered["budget"].items())))
    second = models.MissionSpec.model_validate(reordered)
    round_trip = models.MissionSpec.model_validate(first.model_dump(mode="json"))

    assert first.canonical_hash == second.canonical_hash == round_trip.canonical_hash
    assert len(first.canonical_hash) == 64
    with pytest.raises(ValidationError):
        first.mission_id = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("objective_id", ["", "UPPER", "has space", "a" * 65])
def test_mission_spec_rejects_invalid_objective_ids(objective_id: str) -> None:
    models = _models()
    payload = _mission_payload()
    payload["objectives"] = [_objective(objective_id)]

    with pytest.raises(ValidationError):
        models.MissionSpec.model_validate(payload)


def test_mission_spec_rejects_duplicate_objective_ids() -> None:
    models = _models()
    payload = _mission_payload()
    payload["objectives"] = [_objective("same"), _objective("same")]

    with pytest.raises(ValidationError, match="duplicate objective"):
        models.MissionSpec.model_validate(payload)


def test_mission_spec_rejects_missing_dependency_references() -> None:
    models = _models()
    payload = _mission_payload()
    payload["objectives"] = [_objective("child", dependencies=["missing"])]

    with pytest.raises(ValidationError, match="unknown dependency"):
        models.MissionSpec.model_validate(payload)


def test_mission_spec_rejects_dependency_cycles() -> None:
    models = _models()
    payload = _mission_payload()
    payload["objectives"] = [
        _objective("first", dependencies=["second"]),
        _objective("second", dependencies=["first"]),
    ]

    with pytest.raises(ValidationError, match="dependency cycle"):
        models.MissionSpec.model_validate(payload)


def test_mission_spec_rejects_any_or_completion_in_v1() -> None:
    models = _models()
    payload = _mission_payload()
    payload["completion_rule"] = "any"

    with pytest.raises(ValidationError):
        models.MissionSpec.model_validate(payload)


def test_mission_spec_rejects_required_child_reservations_above_parent() -> None:
    models = _models()
    payload = _mission_payload()
    payload["budget"] = _budget(max_actions=5)
    payload["objectives"] = [
        _objective("first", budget=_cost(max_actions=3)),
        _objective("second", budget=_cost(max_actions=3)),
    ]

    with pytest.raises(ValidationError, match="child budgets exceed parent"):
        models.MissionSpec.model_validate(payload)


def test_bounded_autonomy_requires_finite_authority() -> None:
    models = _models()
    policy = models.AutonomyPolicy.model_validate(_mission_payload()["autonomy"])

    assert policy.mode == "bounded"
    assert policy.max_child_goals == 4

    invalid = deepcopy(_mission_payload()["autonomy"])
    invalid["max_child_goals"] = 0
    with pytest.raises(ValidationError, match="bounded autonomy"):
        models.AutonomyPolicy.model_validate(invalid)


def test_supporting_contracts_are_typed_frozen_and_serializable() -> None:
    models = _models()
    proposal = models.GoalProposal.model_validate(
        {
            "schema_version": "1",
            "proposal_id": "proposal-001",
            "mission_id": "showcase-001",
            "origin": "curriculum",
            "parent_objective_id": "discover-copper",
            "goal": _discover_goal(),
            "rationale_code": "DISCOVERY_GAP",
            "evidence_refs": ["observation:obs-001"],
            "conservative_cost": _cost(max_actions=2),
            "expected_value": 0.8,
        }
    )
    decision = models.GoalAdmissionDecision.model_validate(
        {
            "schema_version": "1",
            "proposal_id": "proposal-001",
            "outcome": "accepted",
            "reason_code": "ADMITTED",
            "reserved_budget": _cost(max_actions=2),
        }
    )
    stage = models.StageIO.model_validate(
        {
            "schema_version": "2",
            "run_id": "showcase-run-001",
            "mission_id": "showcase-001",
            "stage_id": "mission-admission",
            "ordinal": 4,
            "gameplay_evidence_eligible": True,
            "lifecycle": "passed",
            "started_at_ms": 10,
            "finished_at_ms": 20,
            "input_refs": [
                {
                    "artifact_id": "dialogue",
                    "artifact_kind": "dialogue",
                    "json_pointer": "/tool_calls/0",
                    "content_hash": "a" * 64,
                }
            ],
            "decision_source": "goal-admission",
            "reason_code": "ADMITTED",
            "output_refs": [
                {
                    "artifact_id": "mission",
                    "artifact_kind": "mission",
                    "json_pointer": "/",
                    "content_hash": "b" * 64,
                }
            ],
            "evidence_refs": [
                {
                    "artifact_id": "mission-transition",
                    "artifact_kind": "mission_transition",
                    "json_pointer": "/",
                    "content_hash": "c" * 64,
                }
            ],
            "media": [
                {
                    "evidence_ref": {
                        "artifact_id": "screenshot-04",
                        "artifact_kind": "screenshot",
                        "json_pointer": "/",
                        "content_hash": "d" * 64,
                    },
                    "captured_at_ms": 15,
                }
            ],
        }
    )
    report = models.MissionReport.model_validate(
        {
            "schema_version": "1",
            "mission_id": "showcase-001",
            "status": "completed",
            "objective_counts": {"completed": 2},
            "proposal_counts": {"accepted": 1},
            "budget_used": _cost(max_actions=6),
            "evidence_refs": ["receipt:receipt-001"],
            "stage_ids": ["mission-admission"],
        }
    )

    assert proposal.goal.intent == "discover"
    assert decision.outcome == "accepted"
    assert stage.finished_at_ms >= stage.started_at_ms
    assert report.status == "completed"
    with pytest.raises(ValidationError):
        stage.stage_id = "changed"  # type: ignore[misc]


def test_stage_io_v2_uses_evidence_pointers_checkpoints_and_separate_verdicts() -> None:
    models = _models()
    input_ref = models.EvidenceRef(
        artifact_id="dialogue",
        artifact_kind="dialogue",
        json_pointer="/tool_calls/0",
        content_hash="a" * 64,
    )
    output_ref = models.EvidenceRef(
        artifact_id="mission-report",
        artifact_kind="mission_report",
        json_pointer="/objectives/combat-zombie",
        content_hash="b" * 64,
    )
    checkpoint = models.CheckpointIO(
        checkpoint_id="zombie",
        label="Zombie",
        lifecycle="blocked",
        input_refs=(input_ref,),
        decision_source="voyager-controller",
        reason_code="POST_ACTION_RECONCILIATION_PENDING",
        selected_capability="attack",
        output_refs=(output_ref,),
        verifier="EntityDefeated",
        predicates=(
            models.VerificationPredicate(
                predicate_id="zombie-defeated",
                expected={"outcome": "defeated"},
                actual={"outcome": "defeated", "reconciliation": "pending"},
                status="unknown",
            ),
        ),
        evidence_refs=(output_ref,),
        failure=models.StageFailure(
            code="POST_ACTION_RECONCILIATION_PENDING",
            layer="reconciliation",
            retryable=True,
            operator_action="wait for a stable observation",
        ),
    )
    stage = models.StageIO(
        run_id="showcase-run-001",
        mission_id="adaptive-showcase-001",
        stage_id="combat",
        ordinal=5,
        gameplay_evidence_eligible=True,
        lifecycle="blocked",
        started_at_ms=1_000,
        finished_at_ms=2_000,
        input_refs=(input_ref,),
        decision_source="voyager-controller",
        reason_code="POST_ACTION_RECONCILIATION_PENDING",
        selected_strategy="trusted-skill",
        selected_capability="attack",
        budget_ref=input_ref,
        output_refs=(output_ref,),
        state_deltas=(
            models.StageStateDelta(
                path="combat.zombie.health",
                before=20,
                after=0,
            ),
        ),
        verifier="EntityDefeated",
        predicates=checkpoint.predicates,
        checkpoints=(checkpoint,),
        evidence_refs=(output_ref,),
        media=(),
        failure=models.StageFailure(
            code="POST_ACTION_RECONCILIATION_PENDING",
            layer="reconciliation",
            retryable=True,
            operator_action="wait for a stable observation",
        ),
    )
    manifest = models.WalkthroughManifest(
        run_id=stage.run_id,
        mission_id=stage.mission_id,
        projection_hash="c" * 64,
        stages=(stage,),
        bundle_valid=True,
        acceptance_passed=False,
    )

    assert stage.schema_version == "2"
    assert stage.checkpoints[0].predicates[0].status == "unknown"
    assert manifest.bundle_valid is True
    assert manifest.acceptance_passed is False
    assert "decision_summary" not in stage.model_dump()

    with pytest.raises(ValidationError, match="acceptance cannot pass"):
        models.WalkthroughManifest.model_validate(
            manifest.model_copy(update={"acceptance_passed": True}).model_dump()
        )
