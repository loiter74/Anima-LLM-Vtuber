"""Deterministic schema and golden fixtures for mission contract v1."""

from __future__ import annotations

from typing import Any

from animetta.tools.gamebot.contracts.v2 import canonical_json_hash
from animetta.tools.minecraft.voyager.budget import BudgetUsage
from animetta.tools.minecraft.voyager.goal_models import DiscoverGoal

from .models import (
    AutonomyPolicy,
    CheckpointIO,
    EvidenceRef,
    ExecutionPolicy,
    GoalAdmissionDecision,
    GoalProposal,
    MissionObjective,
    MissionReport,
    MissionSpec,
    StageDefinition,
    StageIO,
    StageMedia,
    WalkthroughManifest,
)

_CONTRACT_MODELS = (
    MissionSpec,
    MissionObjective,
    DiscoverGoal,
    AutonomyPolicy,
    ExecutionPolicy,
    GoalProposal,
    GoalAdmissionDecision,
    EvidenceRef,
    CheckpointIO,
    StageDefinition,
    StageIO,
    WalkthroughManifest,
    MissionReport,
)


def _stable_schema(value: object) -> object:
    if isinstance(value, dict):
        normalized = {key: _stable_schema(item) for key, item in value.items()}
        if normalized.get("uniqueItems") is True:
            default = normalized.get("default")
            if isinstance(default, list):
                normalized["default"] = sorted(default, key=str)
        return normalized
    if isinstance(value, list):
        return [_stable_schema(item) for item in value]
    return value


def build_schema_bundle() -> dict[str, object]:
    """Build the complete deterministic JSON Schema bundle."""

    return {
        "schema_version": "1",
        "contracts": {
            model.__name__: _stable_schema(model.model_json_schema()) for model in _CONTRACT_MODELS
        },
    }


def schema_digest(bundle: dict[str, object]) -> str:
    """Hash one schema bundle using the shared canonical JSON algorithm."""

    return canonical_json_hash(bundle)


def _goal() -> dict[str, object]:
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


def _cost() -> dict[str, object]:
    return {
        "max_actions": 2,
        "max_strategy_attempts": 1,
        "max_travel_distance": 32.0,
        "max_blocks_changed": 0,
        "max_damage_taken": 1.0,
        "resource_consumption": {},
    }


def build_golden_fixture() -> dict[str, Any]:
    """Build one valid example of every versioned mission contract."""

    mission = MissionSpec.model_validate(
        {
            "mission_id": "golden-mission-001",
            "objectives": [
                {
                    "objective_id": "discover-copper",
                    "goal": _goal(),
                    "budget": _cost(),
                }
            ],
            "allowed_domains": ["discovery", "skill"],
            "completion_rule": "all_required",
            "completion_predicates": [
                {"kind": "novel_facts_acquired_at_least", "count": 1},
                {"kind": "trusted_skills_created_at_least", "count": 1},
                {"kind": "vanilla_advancements_added_at_least", "count": 2},
            ],
            "budget": {
                "queue_timeout_ms": 5_000,
                "execution_timeout_ms": 300_000,
                "max_actions": 12,
                "max_strategy_attempts": 8,
                "max_travel_distance": 128.0,
                "max_blocks_changed": 32,
                "max_damage_taken": 6.0,
                "protected_items": [],
                "resource_consumption": {},
            },
            "autonomy": {
                "mode": "bounded",
                "allowed_domains": ["discovery", "skill"],
                "max_child_goals": 3,
                "max_new_skills": 1,
                "max_duration_ms": 180_000,
                "max_travel_distance": 96.0,
                "max_damage_taken": 4.0,
                "max_blocks_changed": 16,
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
    )
    proposal = GoalProposal.model_validate(
        {
            "proposal_id": "golden-proposal-001",
            "mission_id": mission.mission_id,
            "origin": "curriculum",
            "parent_objective_id": "discover-copper",
            "goal": _goal(),
            "rationale_code": "DISCOVERY_GAP",
            "evidence_refs": ["observation:golden-observation-001"],
            "conservative_cost": _cost(),
            "expected_value": 0.8,
        }
    )
    decision = GoalAdmissionDecision(
        proposal_id=proposal.proposal_id,
        outcome="accepted",
        reason_code="ADMITTED",
        reserved_budget=proposal.conservative_cost,
    )
    stage_definition = StageDefinition(stage_id="mission-admission", ordinal=4)
    dialogue_ref = EvidenceRef(
        artifact_id="dialogue",
        artifact_kind="dialogue",
        json_pointer="/tool_calls/0",
        content_hash="d" * 64,
    )
    mission_ref = EvidenceRef(
        artifact_id="mission",
        artifact_kind="mission",
        json_pointer="/",
        content_hash="e" * 64,
    )
    transition_ref = EvidenceRef(
        artifact_id="mission-transition",
        artifact_kind="mission_transition",
        json_pointer="/",
        content_hash="f" * 64,
    )
    media_ref = EvidenceRef(
        artifact_id="screenshot-04",
        artifact_kind="screenshot",
        json_pointer="/",
        content_hash="1" * 64,
    )
    stage = StageIO(
        run_id="golden-run-001",
        mission_id=mission.mission_id,
        stage_id="mission-admission",
        ordinal=stage_definition.ordinal,
        gameplay_evidence_eligible=True,
        lifecycle="passed",
        started_at_ms=1_000,
        finished_at_ms=2_000,
        input_refs=(dialogue_ref,),
        decision_source="goal-admission",
        reason_code="ADMITTED",
        output_refs=(mission_ref,),
        evidence_refs=(transition_ref,),
        media=(StageMedia(evidence_ref=media_ref, captured_at_ms=1_500),),
    )
    walkthrough = WalkthroughManifest(
        run_id=stage.run_id,
        mission_id=stage.mission_id,
        projection_hash=canonical_json_hash([stage.model_dump(mode="json")]),
        stages=(stage,),
        bundle_valid=True,
        acceptance_passed=True,
    )
    report = MissionReport(
        mission_id=mission.mission_id,
        status="completed",
        objective_counts={"completed": 1},
        proposal_counts={"accepted": 1},
        budget_used=BudgetUsage(max_actions=1, max_strategy_attempts=1),
        evidence_refs=("receipt:golden-receipt-001",),
        stage_ids=(stage.stage_id,),
    )
    payload: dict[str, Any] = {
        "mission_spec": mission.canonical_payload(),
        "mission_objective": mission.objectives[0].canonical_payload(),
        "discover_goal": mission.objectives[0].goal.model_dump(mode="json", exclude_none=True),
        "autonomy_policy": mission.autonomy.canonical_payload(),
        "execution_policy": mission.execution.canonical_payload(),
        "goal_proposal": proposal.canonical_payload(),
        "admission_decision": decision.canonical_payload(),
        "stage_definition": stage_definition.canonical_payload(),
        "stage_io": stage.canonical_payload(),
        "walkthrough_manifest": walkthrough.canonical_payload(),
        "mission_report": report.canonical_payload(),
    }
    payload["canonical_hashes"] = {
        "mission_spec": mission.canonical_hash,
        "goal_proposal": proposal.canonical_hash,
        "admission_decision": decision.canonical_hash,
        "stage_io": stage.canonical_hash,
        "mission_report": report.canonical_hash,
    }
    return payload
