from __future__ import annotations

from copy import deepcopy
from importlib import import_module

import pytest
from pydantic import ValidationError

from animetta.tools.gamebot.contracts.v2 import (
    BudgetVector,
    CapabilityDefinition,
    CapabilityGuarantees,
    EnvironmentProfile,
    RuntimeManifest,
)
from animetta.tools.minecraft.mission.models import GoalProposal, MissionSpec
from animetta.tools.minecraft.voyager.budget import BudgetAccount, BudgetUsage
from animetta.tools.minecraft.voyager.goal_models import AcquireGoal, InventoryAtLeast

from .test_models import _cost, _discover_goal, _mission_payload


def _admission_module():
    return import_module("animetta.tools.minecraft.mission.admission")


def _manifest(*capabilities: tuple[str, str]) -> RuntimeManifest:
    maximum = BudgetVector(
        max_actions=1,
        max_strategy_attempts=1,
        max_travel_distance=64,
        max_blocks_changed=16,
        max_damage_taken=4,
        protected_items=(),
        resource_consumption={},
    )
    return RuntimeManifest(
        runtime_instance_id="runtime-001",
        profile=EnvironmentProfile(
            runtime_protocol="2.0",
            minecraft_version="1.21.4",
            capability_schema_digest="a" * 64,
            skill_api_version="1",
            policy_version="1",
            server_identity_hash="b" * 64,
            world_identity_hash="c" * 64,
            dimension="minecraft:overworld",
            modset_digest="d" * 64,
        ),
        guarantees=CapabilityGuarantees(
            single_flight=True,
            correlation_idempotency=True,
            cooperative_cancellation=True,
            action_budget_enforcement=True,
            receipt_chains=True,
            correlation_inspection=True,
        ),
        capabilities=tuple(
            CapabilityDefinition(
                name=name,
                risk=risk,
                effect_class="read_only" if risk == "read_only" else "state_changing",
                parameters_schema={"type": "object"},
                receipt_schema_version="2",
                requires_post_observation=risk != "read_only",
                maximum_cost=maximum,
            )
            for name, risk in capabilities
        ),
    )


def _mission(**updates: object) -> MissionSpec:
    payload = _mission_payload()
    payload["allowed_domains"] = ["gameplay", "discovery", "skill"]
    payload.update(updates)
    return MissionSpec.model_validate(payload)


def _proposal(**updates: object) -> GoalProposal:
    payload: dict[str, object] = {
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
    payload.update(updates)
    return GoalProposal.model_validate(payload)


def _context(
    *,
    mission: MissionSpec | None = None,
    manifest: RuntimeManifest | None = None,
    completed: frozenset[str] = frozenset({"discover-copper"}),
    proposal_ids: frozenset[str] = frozenset(),
    goal_hashes: frozenset[str] = frozenset(),
    quarantined: bool = False,
):
    admission = _admission_module()
    current_mission = mission or _mission()
    return admission.AdmissionContext(
        mission=current_mission,
        manifest=manifest or _manifest(("observe", "read_only")),
        budget_account=BudgetAccount(limit=current_mission.budget),
        completed_objective_ids=completed,
        seen_proposal_ids=proposal_ids,
        admitted_goal_hashes=goal_hashes,
        runtime_quarantined=quarantined,
    )


def test_goal_proposal_uses_closed_origin_and_rationale_without_private_reasoning() -> None:
    payload = _proposal().model_dump(mode="json")

    for field, value in (
        ("origin", "model_whim"),
        ("rationale_code", "because I felt like it"),
        ("private_reasoning", "hidden chain of thought"),
    ):
        invalid = deepcopy(payload)
        invalid[field] = value
        with pytest.raises(ValidationError):
            GoalProposal.model_validate(invalid)


def test_admission_accepts_and_reserves_conservative_parent_budget() -> None:
    admission = _admission_module()
    proposal = _proposal()
    context = _context()

    result = admission.GoalAdmission().admit(proposal, context)

    assert result.decision.outcome == "accepted"
    assert result.decision.reason_code == "ADMITTED"
    assert result.context.budget_account.reservations[proposal.proposal_id] == (
        proposal.conservative_cost
    )
    assert result.context.budget_account.remaining.max_actions == 18


def test_admission_attributes_discovery_acquisition_and_skill_reuse_to_policy_source() -> None:
    admission = _admission_module()
    acquire = AcquireGoal(
        intent="acquire",
        target="minecraft:raw_copper",
        constraints={"source_block": "minecraft:copper_ore"},
        success_predicates=(
            InventoryAtLeast(
                kind="inventory_at_least",
                item="minecraft:raw_copper",
                quantity=1,
            ),
        ),
    )
    discovery = _proposal(
        proposal_id="proposal-discovery-acquire",
        parent_objective_id=None,
        goal=acquire,
        rationale_code="DISCOVERY_GAP",
        conservative_cost=_cost(max_actions=2),
    )
    reuse = discovery.model_copy(
        update={
            "proposal_id": "proposal-skill-reuse",
            "rationale_code": "SKILL_GAP",
            "goal": acquire.model_copy(
                update={
                    "quantity": 3,
                    "constraints": {
                        **acquire.constraints,
                        "adaptive_phase": "reuse",
                    },
                }
            ),
        }
    )
    context = _context(manifest=_manifest(("collect", "survival_safe")))

    discovered = admission.GoalAdmission().admit(discovery, context)
    reused = admission.GoalAdmission().admit(reuse, discovered.context)

    assert discovered.decision.outcome == "accepted"
    assert reused.decision.outcome == "accepted"


def test_admission_rejects_mission_domain_and_source_policy_violations() -> None:
    admission = _admission_module()
    domain_forbidden = _mission(allowed_domains=["gameplay", "skill"])
    autonomy_off_payload = _mission_payload()
    autonomy_off_payload["allowed_domains"] = ["gameplay", "discovery", "skill"]
    autonomy_off_payload["autonomy"] = {"mode": "off"}
    autonomy_off = MissionSpec.model_validate(autonomy_off_payload)

    domain_result = admission.GoalAdmission().admit(_proposal(), _context(mission=domain_forbidden))
    source_result = admission.GoalAdmission().admit(_proposal(), _context(mission=autonomy_off))

    assert (domain_result.decision.outcome, domain_result.decision.reason_code) == (
        "rejected",
        "DOMAIN_FORBIDDEN",
    )
    assert (source_result.decision.outcome, source_result.decision.reason_code) == (
        "rejected",
        "SOURCE_FORBIDDEN",
    )


def test_admission_checks_manifest_capability_and_runtime_risk_before_budget() -> None:
    admission = _admission_module()
    missing = admission.GoalAdmission().admit(_proposal(), _context(manifest=_manifest()))

    payload = _mission_payload()
    payload["allowed_domains"] = ["gameplay", "discovery", "skill"]
    payload["autonomy"] = {
        **payload["autonomy"],
        "max_risk": "read_only",
    }
    low_risk_mission = MissionSpec.model_validate(payload)
    risky = admission.GoalAdmission().admit(
        _proposal(),
        _context(
            mission=low_risk_mission,
            manifest=_manifest(("observe", "survival_safe")),
        ),
    )

    assert (missing.decision.outcome, missing.decision.reason_code) == (
        "rejected",
        "MANIFEST_CAPABILITY_MISSING",
    )
    assert (risky.decision.outcome, risky.decision.reason_code) == (
        "rejected",
        "RISK_FORBIDDEN",
    )


def test_admission_rejects_duplicates_and_defers_unready_runtime_or_parent() -> None:
    admission = _admission_module()
    proposal = _proposal()

    duplicate = admission.GoalAdmission().admit(
        proposal,
        _context(proposal_ids=frozenset({proposal.proposal_id})),
    )
    quarantined = admission.GoalAdmission().admit(
        proposal,
        _context(quarantined=True),
    )
    parent_wait = admission.GoalAdmission().admit(
        proposal,
        _context(completed=frozenset()),
    )

    assert (duplicate.decision.outcome, duplicate.decision.reason_code) == (
        "rejected",
        "DUPLICATE_PROPOSAL",
    )
    assert (quarantined.decision.outcome, quarantined.decision.reason_code) == (
        "deferred",
        "RUNTIME_QUARANTINED",
    )
    assert (parent_wait.decision.outcome, parent_wait.decision.reason_code) == (
        "deferred",
        "DEPENDENCY_UNSATISFIED",
    )


def test_admission_rejects_duplicate_goal_and_exhausted_parent_budget() -> None:
    admission = _admission_module()
    proposal = _proposal()
    duplicate_goal = admission.GoalAdmission().admit(
        proposal,
        _context(goal_hashes=frozenset({proposal.goal.canonical_hash})),
    )
    expensive = _proposal(conservative_cost=_cost(max_actions=21))
    exhausted = admission.GoalAdmission().admit(expensive, _context())

    assert duplicate_goal.decision.reason_code == "DUPLICATE_PROPOSAL"
    assert exhausted.decision.reason_code == "BUDGET_EXHAUSTED"
    assert exhausted.context.budget_account.reservations == {}


def test_admission_settles_actual_usage_and_releases_unused_reservation() -> None:
    admission = _admission_module()
    proposal = _proposal()
    accepted = admission.GoalAdmission().admit(proposal, _context())

    settled = admission.GoalAdmission().settle(
        accepted.context,
        proposal.proposal_id,
        BudgetUsage(max_actions=1, max_strategy_attempts=1),
    )

    assert proposal.proposal_id not in settled.budget_account.reservations
    assert settled.budget_account.used.max_actions == 1
    assert settled.budget_account.remaining.max_actions == 19
