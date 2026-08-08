from __future__ import annotations

from importlib import import_module

from animetta.tools.minecraft.skill.applicability import (
    ObservationPrerequisite,
    ParameterBinding,
    SkillApplicability,
    TargetPattern,
)
from animetta.tools.minecraft.skill.ir import SkillProgram, SkillRevision
from animetta.tools.minecraft.skill.trust import SkillEnvironmentTrust
from animetta.tools.minecraft.voyager.budget import BudgetUsage
from animetta.tools.minecraft.voyager.goal_models import AcquireGoal, InventoryAtLeast


def _module():
    return import_module("animetta.tools.minecraft.skill.selection")


def _goal() -> AcquireGoal:
    return AcquireGoal(
        intent="acquire",
        target="minecraft:raw_copper",
        quantity=2,
        success_predicates=(
            InventoryAtLeast(
                kind="inventory_at_least",
                item="minecraft:raw_copper",
                quantity=2,
            ),
        ),
    )


def _candidate(
    selection,
    *,
    name: str,
    target: str,
    successes: int,
    failures: int = 0,
    expected_cost: float = 1,
    environment: str = "e" * 64,
    required_capabilities: frozenset[str] = frozenset({"collect"}),
    observation_prerequisites: tuple[ObservationPrerequisite, ...] = (),
):
    program = SkillProgram.model_validate(
        {
            "name": name,
            "parameters": [
                {"name": "resource", "value_type": "string"},
                {"name": "count", "value_type": "integer"},
            ],
            "steps": [
                {
                    "kind": "action",
                    "step_id": "collect",
                    "capability": "collect",
                    "parameters": {"count": {"kind": "goal_input", "name": "count"}},
                }
            ],
            "postconditions": [
                {
                    "op": "gte",
                    "left": {"kind": "observation", "path": "inventory.target"},
                    "right": {"kind": "goal_input", "name": "count"},
                }
            ],
        }
    )
    revision = SkillRevision(
        definition_id=name,
        revision_hash=program.canonical_hash,
        program=program,
        static_cost=BudgetUsage(max_actions=2),
        source_command_id=f"learn-{name}",
    )
    applicability = SkillApplicability(
        revision_hash=revision.revision_hash,
        intents=frozenset({"acquire"}),
        target_patterns=(TargetPattern(kind="exact", value=target),),
        parameter_bindings=(
            ParameterBinding(parameter="resource", source="goal_target"),
            ParameterBinding(parameter="count", source="goal_quantity"),
        ),
        required_capabilities=required_capabilities,
        observation_prerequisites=observation_prerequisites,
    )
    trust = SkillEnvironmentTrust.trusted(
        revision.revision_hash,
        environment,
        successes=successes,
        failures=failures,
        expected_cost=expected_cost,
    )
    return selection.SkillSelectionCandidate(
        revision=revision,
        applicability=applicability,
        trust=trust,
    )


def _context(selection, **updates: object):
    payload: dict[str, object] = {
        "goal": _goal(),
        "environment_fingerprint": "e" * 64,
        "available_capabilities": frozenset({"collect", "observe"}),
        "discovery_states": {},
        "technology_nodes": frozenset(),
        "observation": {"nearby_blocks": {"copper_ore": True}},
        "allow_skill_reuse": True,
    }
    payload.update(updates)
    return selection.SkillSelectionContext.model_validate(payload)


def test_unrelated_high_trust_revision_is_excluded_before_ranking() -> None:
    selection = _module()
    applicable = _candidate(
        selection,
        name="acquire_copper",
        target="minecraft:raw_copper",
        successes=2,
        failures=1,
        expected_cost=3,
    )
    unrelated = _candidate(
        selection,
        name="acquire_diamond",
        target="minecraft:diamond",
        successes=100,
        expected_cost=1,
    )

    result = selection.select_applicable_skill((unrelated, applicable), _context(selection))

    assert result.selected_revision_hash == applicable.revision.revision_hash
    assert result.ordered_revision_hashes == (applicable.revision.revision_hash,)
    assert result.bound_parameters == {
        "resource": "minecraft:raw_copper",
        "count": 2,
    }
    assert result.exclusions[0].revision_hash == unrelated.revision.revision_hash
    assert result.exclusions[0].reason_code == "TARGET_MISMATCH"


def test_environment_capability_observation_and_policy_mismatches_are_excluded() -> None:
    selection = _module()
    candidates = (
        _candidate(
            selection,
            name="wrong_environment",
            target="minecraft:raw_copper",
            successes=20,
            environment="f" * 64,
        ),
        _candidate(
            selection,
            name="missing_capability",
            target="minecraft:raw_copper",
            successes=20,
            required_capabilities=frozenset({"attack"}),
        ),
        _candidate(
            selection,
            name="missing_observation",
            target="minecraft:raw_copper",
            successes=20,
            observation_prerequisites=(
                ObservationPrerequisite(
                    path="nearby_blocks.copper_ore",
                    op="equals",
                    value=True,
                ),
            ),
        ),
        _candidate(
            selection,
            name="policy_forbidden",
            target="minecraft:raw_copper",
            successes=20,
        ),
    )

    result = selection.select_applicable_skill(
        candidates,
        _context(
            selection,
            observation={"nearby_blocks": {}},
            allow_skill_reuse=False,
        ),
    )

    assert result.selected_revision_hash is None
    assert {item.revision_hash: item.reason_code for item in result.exclusions} == {
        candidates[0].revision.revision_hash: "ENVIRONMENT_TRUST_MISSING",
        candidates[1].revision.revision_hash: "CAPABILITY_MISSING",
        candidates[2].revision.revision_hash: "OBSERVATION_PRECONDITION_MISSING",
        candidates[3].revision.revision_hash: "POLICY_FORBIDDEN",
    }


def test_applicable_candidates_use_trust_then_conservative_cost_ranking() -> None:
    selection = _module()
    costly = _candidate(
        selection,
        name="costly_copper",
        target="minecraft:raw_copper",
        successes=8,
        failures=2,
        expected_cost=5,
    )
    cheaper = _candidate(
        selection,
        name="cheap_copper",
        target="minecraft:raw_copper",
        successes=8,
        failures=2,
        expected_cost=2,
    )

    result = selection.select_applicable_skill((costly, cheaper), _context(selection))

    assert result.ordered_revision_hashes == (
        cheaper.revision.revision_hash,
        costly.revision.revision_hash,
    )
