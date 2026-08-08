"""Closed, typed mission primitives owned by the Voyager control plane."""

from __future__ import annotations

from collections.abc import Mapping
from math import floor, hypot

from animetta.tools.gamebot.contracts.v2 import Observation, RuntimeManifest
from animetta.tools.minecraft.blueprint import (
    BlueprintBinding,
    BlueprintCompiler,
    CompiledBlueprint,
    starter_shelter_blueprint,
)

from ..budget import BudgetUsage
from ..goal_models import (
    EntityDefeated,
    GoalSpec,
    LocationReached,
    StructureMatchesBlueprint,
)
from .base import Complete, ExecuteStep, StrategyDecision, StrategyFailure


class BuiltinMissionStrategy:
    """Execute only reviewed combat and blueprint primitives.

    The public boundary remains a typed goal: callers cannot provide these
    concrete action steps or select this strategy themselves.
    """

    def __init__(
        self,
        *,
        manifest: RuntimeManifest,
        blueprint_origins: Mapping[str, tuple[int, int, int]] | None = None,
        entity_origins: Mapping[str, tuple[int, int, int]] | None = None,
    ) -> None:
        self._manifest = manifest
        self._blueprint_origins = dict(blueprint_origins or {})
        self._entity_origins = dict(entity_origins or {})
        shelter = starter_shelter_blueprint()
        self._blueprints = {shelter.blueprint_id: shelter}

    def prepare(self, goal: GoalSpec | None) -> dict:
        if goal is None:
            raise ValueError("builtin mission strategy requires a structured goal")
        combat = next(
            (
                predicate
                for predicate in goal.success_predicates
                if isinstance(predicate, EntityDefeated)
            ),
            None,
        )
        structure = next(
            (
                predicate
                for predicate in goal.success_predicates
                if isinstance(predicate, StructureMatchesBlueprint)
            ),
            None,
        )
        location = next(
            (
                predicate
                for predicate in goal.success_predicates
                if isinstance(predicate, LocationReached)
            ),
            None,
        )
        if goal.intent == "combat" and combat is not None:
            return {
                "goal": goal,
                "kind": "combat",
                "predicate": combat,
                "completed_steps": 0,
                "zone_attempted": False,
                "pending_kind": None,
            }
        if goal.intent == "build" and structure is not None:
            blueprint = self._blueprints.get(structure.blueprint_id)
            if blueprint is None or blueprint.canonical_hash != structure.blueprint_hash:
                return {"goal": goal, "failure_code": "BLUEPRINT_NOT_APPROVED"}
            return {
                "goal": goal,
                "kind": "blueprint",
                "blueprint": blueprint,
                "compiled_blueprint": None,
                "completed_steps": 0,
            }
        if goal.intent == "travel" and location is not None:
            return {
                "goal": goal,
                "kind": "travel",
                "predicate": location,
                "completed_steps": 0,
            }
        return {"goal": goal, "failure_code": "UNSUPPORTED_BUILTIN_GOAL"}

    def propose(self, state: dict, observation: Observation) -> StrategyDecision:
        failure = state.get("failure_code")
        if failure is not None:
            return StrategyFailure(
                code=str(failure),
                message="Goal is not handled by the closed builtin catalog",
            )
        if state["kind"] == "combat":
            return self._propose_combat(state, observation)
        if state["kind"] == "travel":
            return self._propose_travel(state)
        return self._propose_blueprint(state, observation)

    def _propose_travel(self, state: dict) -> StrategyDecision:
        predicate: LocationReached = state["predicate"]
        if state["completed_steps"] >= 1:
            return Complete(output={"builtin_kind": "travel"})
        try:
            self._manifest.capability("goto")
        except KeyError:
            return StrategyFailure(
                code="CAPABILITY_NOT_AUTHORIZED",
                message="Runtime does not expose the typed goto capability",
            )
        return ExecuteStep(
            capability="goto",
            parameters={"x": predicate.x, "y": predicate.y, "z": predicate.z},
            maximum_cost=BudgetUsage(
                max_actions=1,
                max_strategy_attempts=1,
                max_travel_distance=64,
            ),
        )

    def _propose_combat(self, state: dict, observation: Observation) -> StrategyDecision:
        predicate: EntityDefeated = state["predicate"]
        if state["completed_steps"] >= predicate.quantity:
            return Complete(output={"builtin_kind": "combat"})
        try:
            capability = self._manifest.capability("attack")
        except KeyError:
            return StrategyFailure(
                code="CAPABILITY_NOT_AUTHORIZED",
                message="Runtime does not expose the typed attack capability",
            )
        matching = tuple(
            entity
            for entity in observation.visible_entities
            if entity.entity_type == predicate.entity
        )
        if not matching:
            origin = self._entity_origins.get(predicate.entity)
            if origin is not None and not state["zone_attempted"]:
                try:
                    self._manifest.capability("goto")
                except KeyError:
                    return StrategyFailure(
                        code="CAPABILITY_NOT_AUTHORIZED",
                        message="Runtime does not expose typed travel to the combat zone",
                    )
                target = origin
                if observation.position is not None:
                    dx = origin[0] - observation.position.x
                    dz = origin[2] - observation.position.z
                    distance = hypot(dx, dz)
                    if distance > 3:
                        scale = (distance - 3) / distance
                        target = (
                            round(observation.position.x + dx * scale),
                            origin[1],
                            round(observation.position.z + dz * scale),
                        )
                state["pending_kind"] = "combat_travel"
                return ExecuteStep(
                    capability="goto",
                    parameters={"x": target[0], "y": target[1], "z": target[2]},
                    maximum_cost=BudgetUsage(
                        max_actions=1,
                        max_strategy_attempts=1,
                        max_travel_distance=32,
                    ),
                )
            return StrategyFailure(
                code="COMBAT_TARGET_NOT_OBSERVED",
                message=f"No committed observation contains {predicate.entity}",
            )
        properties = capability.parameters_schema.get("properties", {})
        if isinstance(properties, dict) and "target_entity_id" in properties:
            parameters: dict[str, object] = {
                "target_entity_id": matching[0].entity_id,
            }
        else:
            parameters = {"target": predicate.entity.removeprefix("minecraft:")}
        state["pending_kind"] = "combat_attack"
        return ExecuteStep(
            capability="attack",
            parameters=parameters,
            maximum_cost=BudgetUsage(
                max_actions=1,
                max_strategy_attempts=1,
                max_travel_distance=32,
                max_damage_taken=2,
            ),
        )

    def _propose_blueprint(self, state: dict, observation: Observation) -> StrategyDecision:
        compiled: CompiledBlueprint | None = state["compiled_blueprint"]
        if compiled is None:
            blueprint = state["blueprint"]
            origin = self._blueprint_origins.get(blueprint.blueprint_id)
            if origin is None:
                if observation.position is None:
                    return StrategyFailure(
                        code="BUILD_ORIGIN_UNAVAILABLE",
                        message="A committed position is required to bind the blueprint",
                    )
                origin = (
                    floor(observation.position.x),
                    floor(observation.position.y),
                    floor(observation.position.z),
                )
            compiled = BlueprintCompiler().compile(
                blueprint,
                BlueprintBinding(origin=origin, materials={}),
            )
            state["compiled_blueprint"] = compiled
        index = state["completed_steps"]
        if index >= len(compiled.steps):
            return Complete(
                output={
                    "builtin_kind": "blueprint",
                    "compiled_blueprints": (compiled,),
                }
            )
        placement = compiled.steps[index]
        return ExecuteStep(
            capability="place",
            parameters=placement.parameters,
            maximum_cost=BudgetUsage(
                max_actions=1,
                max_blocks_changed=len(placement.effect_positions),
            ),
        )

    def accept_result(self, state: dict, result: object) -> dict:
        del result
        if state.get("pending_kind") == "combat_travel":
            return {**state, "zone_attempted": True, "pending_kind": None}
        return {
            **state,
            "completed_steps": state["completed_steps"] + 1,
            "pending_kind": None,
        }
