"""Side-effect-free bounded atomic, live, fallback, and learn strategies."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from animetta.tools.gamebot.contracts.v2 import Observation, RuntimeManifest
from animetta.tools.minecraft.skill.applicability import applicability_for_goal
from animetta.tools.minecraft.skill.ir import SkillDefinition, SkillProgram, compile_skill_program
from animetta.tools.minecraft.skill.trust import (
    SkillEnvironmentTrust,
    stable_environment_fingerprint,
)
from animetta.tools.minecraft.survival.registry import WorkflowRegistry
from animetta.tools.minecraft.survival.workflows import (
    diamond_survival_workflow,
    iron_survival_workflow,
)
from animetta.tools.minecraft.voyager.budget import BudgetUsage, ExecutionBudget
from animetta.tools.minecraft.voyager.goal_models import AtomicAction, GoalSpec
from animetta.tools.minecraft.voyager.strategies.atomic import AtomicStrategy
from animetta.tools.minecraft.voyager.strategies.builtin import BuiltinMissionStrategy
from animetta.tools.minecraft.voyager.strategies.fallback import FallbackStrategy
from animetta.tools.minecraft.voyager.strategies.learn import LearnStrategy
from animetta.tools.minecraft.voyager.strategies.live import LiveStrategy
from animetta.tools.minecraft.voyager.strategies.mission import MissionStrategy

ROOT = Path(__file__).resolve().parents[4]
MESSAGES = json.loads(
    (ROOT / "contracts/gamebot/v2/fixtures/golden.json").read_text(encoding="utf-8")
)["messages"]


def goal(target: str = "iron_ingot"):
    return TypeAdapter(GoalSpec).validate_python(
        {
            "intent": "acquire",
            "target": target,
            "quantity": 1,
            "success_predicates": [{"kind": "inventory_at_least", "item": target, "quantity": 1}],
        }
    )


def budget() -> ExecutionBudget:
    return ExecutionBudget(
        queue_timeout_ms=1_000,
        execution_timeout_ms=10_000,
        max_actions=16,
        max_strategy_attempts=4,
        max_travel_distance=256,
        max_blocks_changed=64,
        max_damage_taken=4,
    )


def test_atomic_strategy_proposes_exactly_one_manifest_valid_action() -> None:
    manifest = RuntimeManifest.model_validate(MESSAGES["RuntimeManifest"])
    strategy = AtomicStrategy(
        action=AtomicAction(capability="collect", parameters={"count": 1}),
        manifest=manifest,
    )
    state = strategy.prepare(None)

    first = strategy.propose(state, Observation.model_validate(MESSAGES["Observation"]))
    state = strategy.accept_result(state, {"outcome": "success"})
    second = strategy.propose(state, Observation.model_validate(MESSAGES["Observation"]))

    assert first.kind == "execute" and first.capability == "collect"
    assert second.kind == "complete"


def test_fallback_registry_resolves_exact_goal_and_never_discards_it() -> None:
    registry = WorkflowRegistry()
    registry.register(iron_survival_workflow())
    registry.register(diamond_survival_workflow())
    strategy = FallbackStrategy(registry=registry)
    state = strategy.prepare(goal())

    first = strategy.propose(state, Observation.model_validate(MESSAGES["Observation"]))
    diamond = strategy.prepare(goal("diamond"))
    unsupported = strategy.prepare(goal("emerald"))

    assert first.kind == "execute"
    assert state["goal_hash"] == goal().canonical_hash
    assert state["learning_evidence_eligible"] is False
    assert diamond["workflow"].workflow_id == "survival:diamond"
    assert diamond["workflow"].steps[-1].capability == "collect"
    assert diamond["workflow"].steps[-1].parameters == {
        "block_type": "diamond_ore",
        "count": 1,
    }
    assert unsupported["failure_code"] == "UNSUPPORTED_FALLBACK_GOAL"


def test_diamond_fallback_resumes_from_fresh_underground_inventory_checkpoint() -> None:
    registry = WorkflowRegistry()
    registry.register(diamond_survival_workflow())
    strategy = FallbackStrategy(registry=registry)
    state = strategy.prepare(goal("diamond"))
    observation = Observation.model_validate(
        {
            **MESSAGES["Observation"],
            "position": {"x": 3, "y": 59, "z": 65},
            "inventory": {
                "oak_log": 6,
                "oak_planks": 46,
                "stick": 4,
                "crafting_table": 1,
                "wooden_pickaxe": 2,
                "cobblestone": 17,
            },
        }
    )

    decision = strategy.propose(state, observation)

    assert decision.kind == "execute"
    assert decision.capability == "craft"
    assert decision.parameters == {"recipe": "stone_pickaxe", "count": 1}
    assert state["step_index"] == 6


def test_diamond_fallback_resumes_descent_at_the_first_unreached_layer() -> None:
    registry = WorkflowRegistry()
    registry.register(diamond_survival_workflow())
    strategy = FallbackStrategy(registry=registry)
    state = strategy.prepare(goal("diamond"))
    observation = Observation.model_validate(
        {
            **MESSAGES["Observation"],
            "position": {"x": 3, "y": -16, "z": 65},
            "inventory": {"iron_pickaxe": 1},
        }
    )

    decision = strategy.propose(state, observation)

    assert decision.kind == "execute"
    assert decision.capability == "mine_shaft"
    assert decision.parameters == {"target_y": -24, "minimum_cobblestone": 0}


def test_diamond_workflow_uses_deterministic_carried_planks_instead_of_optional_coal() -> None:
    workflow = diamond_survival_workflow()

    assert not any(
        step.capability == "collect" and step.parameters.get("block_type") == "coal_ore"
        for step in workflow.steps
    )
    smelt = next(step for step in workflow.steps if step.capability == "smelt")
    assert smelt.parameters == {"item": "raw_iron", "fuel": "oak_planks", "count": 3}


def test_live_requires_exact_environment_trust_and_never_falls_back() -> None:
    manifest = RuntimeManifest.model_validate(MESSAGES["RuntimeManifest"])
    program = SkillProgram.model_validate(
        {
            "name": "collect_one",
            "steps": [
                {
                    "kind": "action",
                    "step_id": "collect",
                    "capability": "collect",
                    "parameters": {"count": {"kind": "literal", "value": 1}},
                }
            ],
            "postconditions": [
                {
                    "op": "gte",
                    "left": {"kind": "observation", "path": "inventory.oak_log"},
                    "right": {"kind": "literal", "value": 1},
                }
            ],
        }
    )
    compiled = compile_skill_program(
        program,
        capabilities={
            "collect": {
                "parameters_schema": manifest.capability("collect").parameters_schema,
                "maximum_cost": BudgetUsage(max_actions=1),
            }
        },
        budget=budget(),
    )
    revision = compiled.to_revision(
        SkillDefinition(definition_id="collect", name="collect", description=""),
        source_command_id="learn-1",
    )
    environment = stable_environment_fingerprint(manifest.profile)
    trusted = SkillEnvironmentTrust.trusted(revision.revision_hash, environment)
    live = LiveStrategy(
        revisions={revision.revision_hash: revision},
        applicabilities={revision.revision_hash: applicability_for_goal(revision, goal("oak_log"))},
        trusts=[trusted],
        manifest=manifest,
    )
    decision = live.propose(
        live.prepare(goal("oak_log")), Observation.model_validate(MESSAGES["Observation"])
    )
    no_trust = LiveStrategy(
        revisions={revision.revision_hash: revision},
        applicabilities={revision.revision_hash: applicability_for_goal(revision, goal("oak_log"))},
        trusts=[],
        manifest=manifest,
    )
    failure = no_trust.propose(
        no_trust.prepare(goal("oak_log")), Observation.model_validate(MESSAGES["Observation"])
    )

    assert decision.kind == "execute"
    assert failure.kind == "failure" and failure.code == "NO_ELIGIBLE_SKILL"


def test_live_resolves_namespaced_inventory_postcondition_against_runtime_key() -> None:
    manifest = RuntimeManifest.model_validate(MESSAGES["RuntimeManifest"])
    program = SkillProgram.model_validate(
        {
            "name": "collect_raw_copper",
            "steps": [
                {
                    "kind": "action",
                    "step_id": "collect",
                    "capability": "collect",
                    "parameters": {"count": {"kind": "literal", "value": 1}},
                }
            ],
            "postconditions": [
                {
                    "op": "gte",
                    "left": {
                        "kind": "observation",
                        "path": "inventory.minecraft:raw_copper",
                    },
                    "right": {"kind": "literal", "value": 5},
                }
            ],
        }
    )
    revision = compile_skill_program(
        program,
        capabilities={
            "collect": {
                "parameters_schema": manifest.capability("collect").parameters_schema,
                "maximum_cost": BudgetUsage(max_actions=1),
            }
        },
        budget=budget(),
    ).to_revision(
        SkillDefinition(definition_id="copper", name="copper", description=""),
        source_command_id="learn-copper",
    )
    environment = stable_environment_fingerprint(manifest.profile)
    copper_goal = goal("minecraft:raw_copper").model_copy(update={"quantity": 5})
    strategy = LiveStrategy(
        revisions={revision.revision_hash: revision},
        applicabilities={revision.revision_hash: applicability_for_goal(revision, copper_goal)},
        trusts=[SkillEnvironmentTrust.trusted(revision.revision_hash, environment)],
        manifest=manifest,
    )
    state = strategy.prepare(copper_goal)
    first = strategy.propose(state, Observation.model_validate(MESSAGES["Observation"]))
    state = strategy.accept_result(state, {"outcome": "success"})
    runtime_observation = Observation.model_validate(MESSAGES["Observation"]).model_copy(
        update={"inventory": {"raw_copper": 7}}
    )

    complete = strategy.propose(state, runtime_observation)

    assert first.kind == "execute"
    assert complete.kind == "complete"


def test_mission_strategy_selects_learning_only_after_live_has_no_eligible_skill() -> None:
    observation = Observation.model_validate(MESSAGES["Observation"])

    class StubStrategy:
        def __init__(self, decisions):
            self.decisions = list(decisions)

        def prepare(self, selected_goal):
            return {"goal": selected_goal}

        def propose(self, state, current_observation):
            del state, current_observation
            return self.decisions.pop(0)

        def accept_result(self, state, result):
            return {**state, "result": result}

    from animetta.tools.minecraft.voyager.strategies.base import Complete, StrategyFailure

    strategy = MissionStrategy(
        live=StubStrategy([StrategyFailure(code="NO_ELIGIBLE_SKILL", message="missing")]),
        learn=StubStrategy([Complete(output={"revision_hash": "a" * 64})]),
        fallback=None,
    )
    state = strategy.prepare(goal("oak_log"))

    result = strategy.propose(state, observation)

    assert result.kind == "complete"
    assert result.output["selected_strategy"] == "learn"
    assert state["selection_transitions"] == ("live", "learn")


def test_mission_strategy_executes_typed_combat_with_builtin_capability_first() -> None:
    manifest = RuntimeManifest.model_validate(MESSAGES["RuntimeManifest"])
    observation_payload = Observation.model_validate(MESSAGES["Observation"]).model_dump(
        mode="json"
    )
    observation_payload["visible_entities"] = [
        {
            "entity_id": "entity-zombie-7",
            "entity_type": "minecraft:zombie",
            "position": {"x": 4, "y": 64, "z": 4},
            "health": 20,
        }
    ]
    observation = Observation.model_validate(observation_payload)
    combat = TypeAdapter(GoalSpec).validate_python(
        {
            "intent": "combat",
            "target": "minecraft:zombie",
            "success_predicates": [
                {
                    "kind": "entity_defeated",
                    "entity": "minecraft:zombie",
                    "quantity": 1,
                }
            ],
        }
    )
    strategy = MissionStrategy(
        builtin=BuiltinMissionStrategy(manifest=manifest),
        live=None,
        learn=None,
        fallback=None,
    )
    state = strategy.prepare(combat)

    decision = strategy.propose(state, observation)

    assert decision.kind == "execute"
    assert decision.capability == "attack"
    assert decision.parameters == {"target_entity_id": "entity-zombie-7"}
    assert state["selection_transitions"] == ("builtin",)


def test_builtin_combat_navigates_to_approved_zone_before_attacking() -> None:
    manifest = RuntimeManifest.model_validate(MESSAGES["RuntimeManifest"])
    goto = manifest.capability("collect").model_copy(
        update={
            "name": "goto",
            "parameters_schema": {
                "type": "object",
                "required": ["x", "y", "z"],
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "z": {"type": "number"},
                },
                "additionalProperties": False,
            },
        }
    )
    manifest = manifest.model_copy(update={"capabilities": (*manifest.capabilities, goto)})
    observation = Observation.model_validate(MESSAGES["Observation"]).model_copy(
        update={"visible_entities": ()}
    )
    combat = TypeAdapter(GoalSpec).validate_python(
        {
            "intent": "combat",
            "target": "minecraft:skeleton",
            "success_predicates": [
                {
                    "kind": "entity_defeated",
                    "entity": "minecraft:skeleton",
                    "quantity": 1,
                }
            ],
        }
    )
    strategy = BuiltinMissionStrategy(
        manifest=manifest,
        entity_origins={"minecraft:skeleton": (0, 65, 16)},
    )
    state = strategy.prepare(combat)

    travel = strategy.propose(state, observation)
    state = strategy.accept_result(state, {"outcome": "success"})
    visible_payload = observation.model_dump(mode="json")
    visible_payload["visible_entities"] = [
        {
            "entity_id": "entity-skeleton-1",
            "entity_type": "minecraft:skeleton",
            "position": {"x": 0, "y": 65, "z": 16},
            "health": 20,
        }
    ]
    visible = Observation.model_validate(visible_payload)
    attack = strategy.propose(state, visible)
    state = strategy.accept_result(state, {"outcome": "defeated"})

    assert travel.kind == "execute"
    assert travel.capability == "goto"
    assert travel.parameters == {"x": 0, "y": 65, "z": 13}
    assert attack.kind == "execute"
    assert attack.capability == "attack"
    assert strategy.propose(state, visible).kind == "complete"


def test_builtin_starter_shelter_compiles_at_approved_origin() -> None:
    manifest = RuntimeManifest.model_validate(MESSAGES["RuntimeManifest"])
    shelter = __import__(
        "animetta.tools.minecraft.blueprint", fromlist=["starter_shelter_blueprint"]
    ).starter_shelter_blueprint()
    build = TypeAdapter(GoalSpec).validate_python(
        {
            "intent": "build",
            "target": "starter shelter",
            "success_predicates": [
                {
                    "kind": "structure_matches_blueprint",
                    "blueprint_id": shelter.blueprint_id,
                    "blueprint_hash": shelter.canonical_hash,
                }
            ],
        }
    )
    strategy = BuiltinMissionStrategy(
        manifest=manifest,
        blueprint_origins={shelter.blueprint_id: (4, 65, 4)},
    )
    state = strategy.prepare(build)

    first = strategy.propose(state, Observation.model_validate(MESSAGES["Observation"]))

    assert first.kind == "execute"
    assert first.capability == "place"
    assert first.parameters["x"] == 4
    assert first.parameters["y"] == 65
    assert first.parameters["z"] == 4
    assert state["compiled_blueprint"].origin == (4, 65, 4)


def test_builtin_starter_shelter_requires_every_compiled_step_before_complete() -> None:
    manifest = RuntimeManifest.model_validate(MESSAGES["RuntimeManifest"])
    shelter = __import__(
        "animetta.tools.minecraft.blueprint", fromlist=["starter_shelter_blueprint"]
    ).starter_shelter_blueprint()
    build = TypeAdapter(GoalSpec).validate_python(
        {
            "intent": "build",
            "target": shelter.blueprint_id,
            "success_predicates": [
                {
                    "kind": "structure_matches_blueprint",
                    "blueprint_id": shelter.blueprint_id,
                    "blueprint_hash": shelter.canonical_hash,
                }
            ],
        }
    )
    strategy = BuiltinMissionStrategy(
        manifest=manifest,
        blueprint_origins={shelter.blueprint_id: (4, 65, 4)},
    )
    state = strategy.prepare(build)
    observation = Observation.model_validate(MESSAGES["Observation"])
    first = strategy.propose(state, observation)
    compiled = state["compiled_blueprint"]

    assert len(compiled.steps) == 83
    assert first.kind == "execute"
    for index in range(len(compiled.steps)):
        decision = strategy.propose(state, observation)
        assert decision.kind == "execute", index
        state = strategy.accept_result(state, {"outcome": "success"})

    complete = strategy.propose(state, observation)
    assert complete.kind == "complete"
    assert complete.output["compiled_blueprints"] == (compiled,)


def test_builtin_travel_uses_typed_location_predicate_without_caller_steps() -> None:
    manifest = RuntimeManifest.model_validate(MESSAGES["RuntimeManifest"])
    goto = manifest.capability("collect").model_copy(
        update={
            "name": "goto",
            "parameters_schema": {
                "type": "object",
                "required": ["x", "y", "z"],
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "z": {"type": "number"},
                },
                "additionalProperties": False,
            },
        }
    )
    manifest = manifest.model_copy(update={"capabilities": (*manifest.capabilities, goto)})
    travel = TypeAdapter(GoalSpec).validate_python(
        {
            "intent": "travel",
            "target": "unvisited frontier",
            "success_predicates": [
                {
                    "kind": "location_reached",
                    "x": 20,
                    "y": 63,
                    "z": 20,
                    "tolerance": 3,
                }
            ],
        }
    )
    strategy = BuiltinMissionStrategy(manifest=manifest)

    decision = strategy.propose(
        strategy.prepare(travel), Observation.model_validate(MESSAGES["Observation"])
    )

    assert decision.kind == "execute"
    assert decision.capability == "goto"
    assert decision.parameters == {"x": 20.0, "y": 63.0, "z": 20.0}


def test_live_interprets_branch_and_rechecks_bounded_repeat_against_fresh_observation() -> None:
    manifest = RuntimeManifest.model_validate(MESSAGES["RuntimeManifest"])
    program = SkillProgram.model_validate(
        {
            "name": "conditional_collection",
            "preconditions": [
                {
                    "op": "gte",
                    "left": {"kind": "observation", "path": "health"},
                    "right": {"kind": "literal", "value": 10},
                }
            ],
            "steps": [
                {
                    "kind": "branch",
                    "step_id": "health_branch",
                    "condition": {
                        "op": "gte",
                        "left": {"kind": "observation", "path": "health"},
                        "right": {"kind": "literal", "value": 10},
                    },
                    "then_steps": [
                        {
                            "kind": "action",
                            "step_id": "healthy_collect",
                            "capability": "collect",
                            "parameters": {"count": {"kind": "literal", "value": 1}},
                        }
                    ],
                    "else_steps": [
                        {
                            "kind": "fail",
                            "step_id": "unsafe",
                            "code": "HEALTH_TOO_LOW",
                            "message": "health gate failed",
                        }
                    ],
                },
                {
                    "kind": "repeat",
                    "step_id": "collect_until_two",
                    "max_iterations": 3,
                    "condition": {
                        "op": "lt",
                        "left": {"kind": "observation", "path": "inventory.oak_log"},
                        "right": {"kind": "literal", "value": 2},
                    },
                    "steps": [
                        {
                            "kind": "action",
                            "step_id": "repeat_collect",
                            "capability": "collect",
                            "parameters": {"count": {"kind": "literal", "value": 1}},
                        }
                    ],
                },
            ],
            "postconditions": [
                {
                    "op": "gte",
                    "left": {"kind": "observation", "path": "inventory.oak_log"},
                    "right": {"kind": "literal", "value": 2},
                }
            ],
        }
    )
    compiled = compile_skill_program(
        program,
        capabilities={
            "collect": {
                "parameters_schema": manifest.capability("collect").parameters_schema,
                "maximum_cost": BudgetUsage(max_actions=1),
            }
        },
        budget=budget(),
    )
    revision = compiled.to_revision(
        SkillDefinition(definition_id="conditional", name="conditional", description=""),
        source_command_id="learn-branch",
    )
    environment = stable_environment_fingerprint(manifest.profile)
    strategy = LiveStrategy(
        revisions={revision.revision_hash: revision},
        applicabilities={revision.revision_hash: applicability_for_goal(revision, goal("oak_log"))},
        trusts=[SkillEnvironmentTrust.trusted(revision.revision_hash, environment)],
        manifest=manifest,
    )
    base = Observation.model_validate(MESSAGES["Observation"])
    first_observation = base.model_copy(update={"health": 20, "inventory": {"oak_log": 0}})
    state = strategy.prepare(goal("oak_log"))

    first = strategy.propose(state, first_observation)
    state = strategy.accept_result(state, {"outcome": "success"})
    repeated = strategy.propose(
        state, first_observation.model_copy(update={"inventory": {"oak_log": 1}})
    )
    state = strategy.accept_result(state, {"outcome": "success"})
    complete = strategy.propose(
        state, first_observation.model_copy(update={"inventory": {"oak_log": 2}})
    )

    assert first.kind == "execute" and first.parameters == {"count": 1}
    assert repeated.kind == "execute" and repeated.parameters == {"count": 1}
    assert complete.kind == "complete"

    rejected = strategy.propose(
        strategy.prepare(goal("oak_log")),
        first_observation.model_copy(update={"health": 5}),
    )
    assert rejected.kind == "failure" and rejected.code == "SKILL_PRECONDITION_FAILED"


def test_learn_strategy_bounds_frontier_attempts_and_separates_evidence_chains() -> None:
    strategy = LearnStrategy(
        resolve_frontier=lambda _goal: ("wood_collection", "crafting_table", "iron_ingot"),
        propose_node=lambda node: {
            "capability": "collect",
            "parameters": {"count": 1},
            "maximum_cost": BudgetUsage(max_actions=1),
            "node": node,
        },
        max_frontier_nodes=2,
        max_attempts=2,
    )
    state = strategy.prepare(goal())
    first = strategy.propose(state, Observation.model_validate(MESSAGES["Observation"]))
    state = strategy.accept_result(state, {"outcome": "success", "receipt_hash": "a" * 64})
    validation = strategy.propose(state, Observation.model_validate(MESSAGES["Observation"]))

    assert state["frontier"] == ("wood_collection", "crafting_table")
    assert first.kind == "execute"
    assert validation.kind == "execute"
    assert state["learning_receipts"] == ("a" * 64,)
    assert state["validation_receipts"] == ()
    assert state["phase"] == "validation"


def test_learn_compiles_candidate_ir_before_independent_validation() -> None:
    manifest = RuntimeManifest.model_validate(MESSAGES["RuntimeManifest"])
    strategy = LearnStrategy(
        resolve_frontier=lambda _goal: ("wood_collection",),
        propose_node=lambda node: {
            "capability": "collect",
            "parameters": {"count": 1},
            "maximum_cost": BudgetUsage(max_actions=1),
            "node": node,
        },
        max_frontier_nodes=1,
        max_attempts=2,
        manifest=manifest,
        compilation_budget=budget(),
        source_command_id="command-1",
    )
    observation = Observation.model_validate(MESSAGES["Observation"])
    state = strategy.prepare(goal())
    state = strategy.accept_result(
        state,
        {
            "outcome": "success",
            "receipt_hash": "a" * 64,
            "command_id": "command-1",
            "correlation_id": "learning-correlation",
            "start_state_hash": "1" * 64,
            "resource_instance_ref": "block:overworld:10:64:10",
        },
    )
    revision = state["candidate_revisions"][0]
    state = strategy.accept_result(
        state,
        {
            "outcome": "success",
            "receipt_hash": "b" * 64,
            "command_id": "command-1",
            "correlation_id": "validation-correlation",
            "start_state_hash": "2" * 64,
            "resource_instance_ref": "block:overworld:24:63:18",
        },
    )
    complete = strategy.propose(state, observation)

    assert revision.source_command_id == "command-1"
    assert revision.program.steps[0].kind == "action"
    assert revision.program.postconditions[0].left.path == "inventory.iron_ingot"
    assert complete.kind == "complete"
    assert complete.output["trust_outcomes"] == ("environment_trusted",)
    assert complete.output["learning_evidence"] == ("a" * 64,)
    assert complete.output["validation_evidence"] == ("b" * 64,)
